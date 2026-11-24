"""
NEXUS AI v3 — Çift Hızlı (Altyazı Öncelikli) Çok Modlu Çeviri Hattı (Pipeline)

Üç çalışma modu:
  - full_patch    : Hem altyazılar hem oyundaki tüm yazılar (menü, telefon, görev, ipucu)
                    kendi yerinde (PatchOverlayWindow) Bukalemun + Buzlu Cam yaması ile çevrilir.
  - hybrid        : Altyazı bölgesindeki metinler alt HUD'da, diğer tüm yazılar kendi yerinde görünür.
  - subtitle_only : Yalnızca altyazı bölgesi (seçili ROI veya otomatik alt-orta bant) çevrilir.

Hız mimarisi:
  - Altyazı şeridi her karede 1-2 ms'lik yüksek geçiren piksel kapısıyla kontrol edilir;
    yalnızca altyazı metni değiştiğinde ~680 px şerit üzerinde hızlı GPU OCR + SSE akışı çalışır.
  - Dünya/UI yazıları world_scan_interval aralığında ayrı taranır ve altyazı bandıyla çakışmaz.
"""
import difflib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from core.box_tracker import BoxTracker, TrackedBox
try:
    from core.button_icons import attach_button_icons
except Exception:  # modül yoksa ikon koruma devre dışı, hat çalışmaya devam eder
    attach_button_icons = None
from core.capture import make_source
from core.ocr_engine import OCREngine, merge_nearby_boxes
from core.text_filter import (
    auto_subtitle_roi,
    clean_ocr_game_text,
    has_subtitle_text_changed,
    is_in_auto_subtitle_zone,
    is_translatable_game_text,
    sample_box_style,
    split_speaker_prefix,
    trim_button_icons_from_boxes,
)
from core.translation_engine import TranslationEngine


class TranslationPipeline:
    """Altyazı öncelikli çok modlu OCR + takipçi + akışlı çeviri döngüsü."""

    def __init__(self, ocr_engine: OCREngine, translation_engine: TranslationEngine,
                 settings: dict, callbacks: dict = None,
                 world_ocr_engine: OCREngine = None):
        self.ocr = ocr_engine
        self.world_ocr = world_ocr_engine or ocr_engine
        self.translator = translation_engine
        self.settings = settings or {}
        self.cb = callbacks or {}

        self.roi = None
        self.source = None
        self.window_handle = int(self.settings.get("window_handle", 0) or 0)

        self._thread = None
        self._world_thread = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._freeze_req = threading.Event()
        self._box_lock = threading.Lock()

        self._last_text = ""
        self._last_patch_summary = ""
        self._prev_img = None
        self._prev_full = None
        self._latest_frame = None
        self._latest_origin = (0, 0)
        self._last_state = ""
        self._frozen = False
        self._last_hybrid_sub = ""

        # Altyazı öncelikli paralel çift hat durumu
        self._sub_mask = None
        self._last_sub_text = ""
        self._active_sub_boxes: list[TrackedBox] = []
        self._last_world_ocr_ts = 0.0
        self._sub_box_seq = 1_000_000

        # Dünya çevirisi ayrı iş parçacığında: ağ beklerken dünya OCR döngüsü durmaz.
        # _gen her sıfırlamada artar; eski nesil işler bitince ekrana yazmaz.
        self._tr_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nexus-world-tr")
        self._gen = 0

        self.tracker = BoxTracker()
        self.stats = {
            "ocr_ms": 0.0, "world_ocr_ms": 0.0, "tr_ms": 0.0, "source": "",
            "total": 0, "loops": 0, "skipped": 0, "boxes": 0, "last_text": "",
        }

    @property
    def _active_sub_box(self) -> TrackedBox | None:
        return self._active_sub_boxes[0] if self._active_sub_boxes else None

    # ------------------------------------------------------------ durum & kontrol
    def _reset_runtime_state(self, clear_prev_img: bool = True):
        with self._box_lock:
            self._gen += 1
            self.tracker.clear()
            self._prev_full = None
            self._latest_frame = None
            if clear_prev_img:
                self._prev_img = None
            self._last_hybrid_sub = ""
            self._sub_mask = None
            self._last_sub_text = ""
            self._active_sub_boxes = []
            self._last_world_ocr_ts = 0.0

    def set_roi(self, roi):
        self.roi = tuple(roi) if roi else None
        self._reset_runtime_state()

    def set_source(self, source_type: str, camera_index: int = 0, window_handle: int = 0):
        if self.source is not None:
            try:
                self.source.release()
            except Exception:
                pass
        hwnd = int(window_handle or getattr(self, "window_handle", 0)
                   or self.settings.get("window_handle", 0) or 0)
        self.window_handle = hwnd
        self.source = make_source(
            source_type, camera_index,
            window_handle=hwnd,
            window_title=self.settings.get("window_title", ""),
        )
        self._reset_runtime_state()

    def start(self):
        self._frozen = False
        self._stop.clear()
        self._pause.clear()
        if not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._loop, name="nexus-sub-pipeline",
                                            daemon=True)
            self._thread.start()
        if not (self._world_thread and self._world_thread.is_alive()):
            self._world_thread = threading.Thread(target=self._world_loop,
                                                  name="nexus-world-pipeline",
                                                  daemon=True)
            self._world_thread.start()
        self._emit_state("running")

    def pause(self):
        self._frozen = False
        self._freeze_req.clear()
        self._pause.set()
        self._reset_runtime_state()
        self._emit("on_boxes", [], (0, 0), (0, 0))
        self._emit_state("paused")

    def stop(self):
        self._frozen = False
        self._freeze_req.clear()
        self._stop.set()
        self._pause.set()
        self._reset_runtime_state()
        self._emit("on_boxes", [], (0, 0), (0, 0))
        for th in (self._thread, self._world_thread):
            if th and th.is_alive():
                th.join(timeout=2.0)
        self._thread = None
        self._world_thread = None
        self._emit_state("idle")

    def trigger_freeze_scan(self) -> bool:
        """
        F7 Anlık Dondur & Oku:
          - Dondurulmuş değilse tam çözünürlüklü tam ekran tarama başlatır ve sabitler.
          - Zaten dondurulmuşsa dondurmayı kapatıp normal canlı akışa döner.
        Döner: yeni freeze durumu (True = donduruldu, False = canlı akışa dönüldü).
        """
        if self._frozen:
            self._frozen = False
            self._freeze_req.clear()
            self._reset_runtime_state(clear_prev_img=False)
            self._emit("on_boxes", [], (0, 0), (0, 0))
            return False

        self._freeze_req.set()
        if not self.is_running:
            self.start()
        return True

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._pause.is_set())

    def update_settings(self, settings: dict):
        """Ayarlar değişince motorları yeniden kurmadan güncelle."""
        old_mode = self.settings.get("patch_mode")
        self.settings = settings or {}
        new_mode = self.settings.get("patch_mode")
        if old_mode != new_mode:
            self._reset_runtime_state()
            self._last_text = ""
            if new_mode == "subtitle_only":
                self._emit("on_boxes", [], (0, 0), (0, 0))
        try:
            self.translator.fallback_engine = self.settings.get(
                "fallback_engine", self.translator.fallback_engine)
            self.translator.target_language = self.settings.get(
                "target_language", self.translator.target_language)
            self.translator.auto_learn_enabled = self.settings.get(
                "auto_learn_enabled", self.translator.auto_learn_enabled)
        except Exception:
            pass

    # ------------------------------------------------------------ döngü
    def _loop(self):
        interval = float(self.settings.get("capture_interval", 0.05) or 0.05)
        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.1)
                continue
            if self.source is None:
                time.sleep(0.15)
                continue
            try:
                self._tick()
            except Exception as e:
                self._emit("on_error", f"{e}")
                time.sleep(0.5)
            self.stats["loops"] += 1
            time.sleep(interval)

    def _tick(self):
        mode = self.settings.get("patch_mode", "full_patch")

        # Dondur & Oku isteği geldiyse tam çözünürlükte tarayıp sabitle
        if self._freeze_req.is_set():
            self._freeze_req.clear()
            full_frame = self.source.grab(None)
            if full_frame is not None and getattr(full_frame, "size", 0):
                origin = getattr(self.source, "last_origin", (0, 0))
                self._frozen = True
                self.process_full_frame(full_frame, origin=origin, is_freeze=True)
            return

        if self._frozen:
            time.sleep(0.05)
            return

        if mode == "subtitle_only":
            self._tick_subtitle_only()
            return

        # full_patch / hybrid → kareyi yakalayıp altyazıyı hiç beklemeden işle;
        # son kareyi paralel dünya/menü iş parçacığına aktar.
        full_frame = self.source.grab(None)
        if full_frame is None or not getattr(full_frame, "size", 0):
            return
        origin = getattr(self.source, "last_origin", (0, 0))
        self._latest_frame = full_frame
        self._latest_origin = origin
        fh, fw = full_frame.shape[:2]

        with self._box_lock:
            if self.tracker.check_disappearances(full_frame):
                combined = self._combined_boxes_locked()
                self.stats["boxes"] = len(combined)
                self._emit_active_outputs(mode, combined, origin, (fw, fh))

        self._process_subtitle_band(full_frame, origin, mode, is_freeze=False)

    def _world_loop(self):
        """Paralel Dünya / Menü OCR ve çeviri döngüsü (altyazı hattını bloklamaz)."""
        while not self._stop.is_set():
            if self._pause.is_set() or self._frozen or self.source is None:
                time.sleep(0.1)
                continue
            mode = self.settings.get("patch_mode", "full_patch")
            if mode == "subtitle_only":
                time.sleep(0.12)
                continue

            frame = self._latest_frame
            origin = self._latest_origin
            if frame is None or not getattr(frame, "size", 0):
                time.sleep(0.05)
                continue

            try:
                stab = int(self.settings.get("stabilization_frames", 2) or 2)
                world_interval = float(self.settings.get("world_scan_interval", 0.55) or 0.55)
                now = time.time()
                if self._prev_full is not None and (now - self._last_world_ocr_ts) < world_interval:
                    with self._box_lock:
                        pending = self.tracker.promote_pending(frame, stabilization_frames=stab)
                    if pending:
                        self._translate_world_async(pending)
                    time.sleep(0.05)
                    continue

                self._last_world_ocr_ts = now
                self._process_world_pass(frame, origin, mode, is_freeze=False, stab=stab)
            except Exception as e:
                self._emit("on_error", f"{e}")
                time.sleep(0.3)
            time.sleep(0.05)

    # ------------------------------------------------------------ tek altyazı modu
    def _tick_subtitle_only(self):
        use_auto = not self.roi
        fw = fh = sx = sy = sw = 0
        if self.roi:
            frame = self.source.grab(self.roi)
            if frame is None or not getattr(frame, "size", 0):
                return
            fh, fw = frame.shape[:2]
        else:
            full = self.source.grab(None)
            if full is None or not getattr(full, "size", 0):
                return
            fh, fw = full.shape[:2]
            sx, sy, sw, sh = auto_subtitle_roi(fw, fh)
            frame = full[sy:sy + sh, sx:sx + sw]

        if frame is None or not getattr(frame, "size", 0):
            return

        changed, has_text, self._sub_mask = has_subtitle_text_changed(self._sub_mask, frame)
        if not has_text:
            if self._last_text:
                self._last_text = ""
                self._emit("on_text", "", "")
            return
        if not changed:
            self.stats["skipped"] += 1
            return

        max_w = int(self.settings.get("ocr_max_width_sub", 1080) or 1080)
        ocr_frame, scale_x, scale_y = self._downscale_if_needed(frame, max_w)
        t0 = time.time()
        on_partial = self.cb.get("on_partial")
        if use_auto:
            raw_boxes = self.ocr.read_boxes(
                ocr_frame, offset_x=sx, offset_y=sy,
                scale_x=scale_x, scale_y=scale_y, min_score=0.55)
            use_noise = bool(self.settings.get("noise_filter_enabled", True))
            merged = self._filter_and_merge(raw_boxes, use_noise=use_noise, frame_bgr=full)
            sub_boxes = self._filter_auto_subtitle_boxes(merged, sx, sw, fw, fh)
            sub_boxes.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
            self.stats["ocr_ms"] = round((time.time() - t0) * 1000, 1)

            raw_blocks = [b["text"].strip() for b in sub_boxes if b.get("text", "").strip()]
            raw_key = " | ".join(raw_blocks).strip()
            if not raw_key:
                if self._last_text:
                    self._last_text = ""
                    self._emit("on_text", "", "")
                return
            if self._is_similar(raw_key, self._last_text):
                return
            self._last_text = raw_key

            t1 = time.time()
            translated_parts = []
            last_src = ""
            for i, blk_text in enumerate(raw_blocks):
                cb_p = on_partial if i == len(raw_blocks) - 1 else None
                tr_b, src_b, sp_b, is_prop_b = self.translator.translate_with_speaker(
                    blk_text, on_partial=cb_p)
                if is_prop_b and len(raw_blocks) > 1:
                    continue
                if tr_b:
                    translated_parts.append(f"{sp_b}: {tr_b}" if sp_b else tr_b)
                if src_b:
                    last_src = src_b
            display_text = " ".join(translated_parts).strip()
            source = last_src
            self.stats["tr_ms"] = round((time.time() - t1) * 1000, 1)
        else:
            text = self.ocr.read_text(ocr_frame)
            self.stats["ocr_ms"] = round((time.time() - t0) * 1000, 1)
            if not text:
                if self._last_text:
                    self._last_text = ""
                    self._emit("on_text", "", "")
                return
            if self._is_similar(text, self._last_text):
                return
            self._last_text = text

            t1 = time.time()
            translated, source, speaker, _ = self.translator.translate_with_speaker(
                text, on_partial=on_partial)
            display_text = f"{speaker}: {translated}" if speaker and translated else translated
            self.stats["tr_ms"] = round((time.time() - t1) * 1000, 1)

        self.stats["source"] = source
        self.stats["total"] = getattr(self.translator, "total_translations", 0)
        self.stats["last_text"] = display_text

        self._emit("on_text", display_text, source)
        self._emit("on_stats", dict(self.stats))

    # ------------------------------------------------------------ çift hızlı tam ekran / hibrit
    def _combined_boxes_locked(self) -> list[TrackedBox]:
        return list(self._active_sub_boxes) + self.tracker.active_boxes()

    def _combined_boxes(self) -> list[TrackedBox]:
        with self._box_lock:
            return self._combined_boxes_locked()

    def _subtitle_roi(self, fw: int, fh: int) -> tuple[int, int, int, int]:
        if self.roi:
            rx, ry, rw, rh = [int(v) for v in self.roi]
            x1 = max(0, min(fw - 1, rx))
            y1 = max(0, min(fh - 1, ry))
            x2 = max(x1 + 1, min(fw, rx + max(1, rw)))
            y2 = max(y1 + 1, min(fh, ry + max(1, rh)))
            return (x1, y1, x2 - x1, y2 - y1)
        return auto_subtitle_roi(fw, fh)

    def _filter_and_merge(self, raw_boxes: list[dict], use_noise: bool,
                          frame_bgr=None, strict_icons: bool = False) -> list[dict]:
        filtered = []
        for b in raw_boxes:
            if use_noise and not is_translatable_game_text(b["text"], b["score"], b["bbox"]):
                continue
            item = dict(b)
            cleaned = clean_ocr_game_text(item["text"])
            if cleaned:
                item["text"] = cleaned
            filtered.append(item)

        merged = merge_nearby_boxes(filtered)
        if use_noise:
            merged = [
                b for b in merged
                if is_translatable_game_text(b["text"], b["score"], b["bbox"])
            ]
        kept = trim_button_icons_from_boxes(raw_boxes, merged, frame_bgr=frame_bgr)
        # Satır içi tuş ikonlarının (R2, L1, X...) orijinal piksellerini yama için sakla
        if attach_button_icons is not None and frame_bgr is not None:
            for b in kept:
                try:
                    attach_button_icons(b, frame_bgr, strict=strict_icons)
                except Exception:
                    pass
        return kept

    @staticmethod
    def _filter_auto_subtitle_boxes(boxes: list[dict], sx: int, sw: int,
                                    fw: int, fh: int) -> list[dict]:
        """Otomatik alt-orta bant dışına sarkan kırpılmış kenar etiketlerini eler."""
        kept = []
        edge_right = sx + sw
        half_w = fw * 0.5
        for b in boxes:
            if not is_in_auto_subtitle_zone(b["bbox"], fw, fh, None):
                continue
            bx, _, bw, _ = b["bbox"]
            cx = bx + bw * 0.5
            touches_edge = (bx <= sx + 3) or (bx + bw >= edge_right - 3)
            if touches_edge and len(b["text"].split()) <= 2 and abs(cx - half_w) > fw * 0.22:
                continue
            kept.append(b)
        return kept

    def _clear_active_subtitle(self, mode: str, origin: tuple, frame_size: tuple):
        with self._box_lock:
            if not self._active_sub_boxes and not self._last_sub_text:
                return
            self._active_sub_boxes = []
            self._last_sub_text = ""
            combined = self._combined_boxes_locked()
            self.stats["boxes"] = len(combined)
            self._emit_active_outputs(mode, combined, origin, frame_size)

    def _process_subtitle_band(self, full_frame, origin: tuple, mode: str,
                               is_freeze: bool = False) -> bool:
        """
        Altyazı şeridini öncelikli tarar (~1.5 ms kapı; değişimde 1080 px hızlı OCR + SSE).
        Ayrı dikey blokları (ör. diyalog + altta 'Hold [R] to ...') birbirine yapıştırmadan
        ayrıca takip eder ki DB eşleşmeleri bozulmasın.
        Döner: Bu turda altyazı OCR çalıştıysa True (aynı döngüde ağır dünya taramasını erteler).
        """
        fh, fw = full_frame.shape[:2]
        use_auto = bool(self.settings.get("auto_subtitle_detect", True))
        if not (self.roi or use_auto):
            return False

        sx, sy, sw, sh = self._subtitle_roi(fw, fh)
        if sw <= 2 or sh <= 2:
            return False
        sub_crop = full_frame[sy:sy + sh, sx:sx + sw]

        if not is_freeze:
            changed, has_text, self._sub_mask = has_subtitle_text_changed(
                self._sub_mask, sub_crop)
            if not has_text:
                self._clear_active_subtitle(mode, origin, (fw, fh))
                return False
            if not changed:
                return False

        max_w = 0 if is_freeze else int(self.settings.get("ocr_max_width_sub", 1080) or 1080)
        ocr_sub, scale_x, scale_y = self._downscale_if_needed(sub_crop, max_w)

        t0 = time.time()
        raw_boxes = self.ocr.read_boxes(
            ocr_sub, offset_x=sx, offset_y=sy,
            scale_x=scale_x, scale_y=scale_y, min_score=0.55)
        self.stats["ocr_ms"] = round((time.time() - t0) * 1000, 1)

        use_noise = bool(self.settings.get("noise_filter_enabled", True))
        merged = self._filter_and_merge(raw_boxes, use_noise=use_noise, frame_bgr=full_frame,
                                        strict_icons=True)
        if not self.roi:
            merged = self._filter_auto_subtitle_boxes(merged, sx, sw, fw, fh)

        merged = [b for b in merged if b.get("text", "").strip()]
        if not merged:
            self._clear_active_subtitle(mode, origin, (fw, fh))
            return True

        merged.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        with self._box_lock:
            old_boxes = [] if is_freeze else list(self._active_sub_boxes)
        used_old: set[int] = set()
        new_boxes: list[TrackedBox] = []
        to_translate: list[tuple[TrackedBox, str]] = []
        now_ts = time.time()

        for b in merged:
            text = b["text"].strip()
            bbox = tuple(int(v) for v in b["bbox"])
            line_count = int(b.get("line_count", 1))
            matched = None
            if not is_freeze:
                for idx, old in enumerate(old_boxes):
                    if idx not in used_old and self._is_similar(text, old.original_text, ratio=0.84):
                        used_old.add(idx)
                        old.bbox = bbox
                        old.smoothed_bbox = tuple(float(v) for v in bbox)
                        old.line_count = line_count
                        old.last_seen = now_ts
                        if b.get("icons"):
                            old.icons = list(b["icons"])
                        matched = old
                        break
            if matched is not None:
                new_boxes.append(matched)
                continue

            self._sub_box_seq += 1
            sp_preview, _ = split_speaker_prefix(text)
            style = sample_box_style(full_frame, bbox, frame_w=fw)
            sub_box = TrackedBox(
                id=self._sub_box_seq,
                original_text=text,
                bbox=bbox,
                smoothed_bbox=tuple(float(v) for v in bbox),
                is_subtitle=True,
                line_count=line_count,
                translated_text="",
                speaker=sp_preview,
                source="",
                style=style,
                seen_frames=99,
                missed_frames=0,
                last_seen=now_ts,
                is_proper_noun=False,
                translation_requested=True,
            )
            sub_box.icons = list(b.get("icons") or [])
            new_boxes.append(sub_box)
            to_translate.append((sub_box, text))

        removed_any = len(used_old) < len(old_boxes)
        with self._box_lock:
            self._active_sub_boxes = new_boxes
            self._last_sub_text = " | ".join(b.original_text for b in new_boxes)
            if not to_translate and (removed_any or is_freeze):
                combined = self._combined_boxes_locked()
                self.stats["boxes"] = len(combined)
                self._emit_active_outputs(mode, combined, origin, (fw, fh))
                self._emit("on_stats", dict(self.stats))

        if not to_translate:
            return True

        total_tr_ms = 0.0
        last_src = ""
        for sub_box, text in to_translate:
            sp_preview = sub_box.speaker
            last_partial_ts = [0.0]

            def _on_partial(partial_tr: str, _box=sub_box, _sp=sp_preview, _lts=last_partial_ts):
                if not partial_tr or self._stop.is_set() or self._pause.is_set():
                    return
                now_p = time.time()
                if (now_p - _lts[0]) < 0.03:
                    return
                _lts[0] = now_p
                with self._box_lock:
                    _box.speaker = _sp
                    _box.translated_text = partial_tr
                    _box.source = "ZİNCİR"
                    if mode == "full_patch":
                        self._emit_active_outputs(mode, self._combined_boxes_locked(), origin, (fw, fh))
                    else:
                        parts = [
                            (f"{sb.speaker}: {sb.translated_text}" if sb.speaker else sb.translated_text)
                            for sb in self._active_sub_boxes if sb.translated_text
                        ]
                        if parts:
                            self._emit("on_partial", " ".join(parts))

            t1 = time.time()
            translated, source, speaker, is_proper = self.translator.translate_with_speaker(
                text, on_partial=_on_partial)
            total_tr_ms += (time.time() - t1) * 1000.0

            with self._box_lock:
                sub_box.translated_text = translated
                sub_box.source = source
                sub_box.speaker = speaker
                sub_box.is_proper_noun = is_proper
            if source:
                last_src = source

        with self._box_lock:
            self._update_tr_stats(round(total_tr_ms, 1), last_src)
            combined = self._combined_boxes_locked()
            self.stats["boxes"] = len(combined)
            self._emit_active_outputs(mode, combined, origin, (fw, fh))
            self._emit("on_stats", dict(self.stats))
        return True

    def _update_tr_stats(self, tr_ms: float, last_src: str):
        self.stats["tr_ms"] = tr_ms
        if last_src:
            self.stats["source"] = last_src
        self.stats["total"] = getattr(self.translator, "total_translations", 0)

    def _process_world_pass(self, full_frame, origin: tuple, mode: str,
                            is_freeze: bool, stab: int):
        fh, fw = full_frame.shape[:2]
        use_noise = bool(self.settings.get("noise_filter_enabled", True))
        use_auto_sub = bool(self.settings.get("auto_subtitle_detect", True))

        if not is_freeze:
            dirty_rect = self._find_dirty_region(self._prev_full, full_frame)
            if dirty_rect is None:
                self.stats["skipped"] += 1
                with self._box_lock:
                    pending = self.tracker.promote_pending(full_frame, stabilization_frames=stab)
                if pending:
                    self._translate_world_async(pending)
                return
            rx, ry, rw, rh = dirty_rect
        else:
            rx, ry, rw, rh = 0, 0, fw, fh

        self._prev_full = full_frame.copy()
        scan_crop = full_frame[ry:ry + rh, rx:rx + rw]
        if scan_crop.size == 0:
            return

        max_w = 0 if is_freeze else int(self.settings.get("ocr_max_width_full", 960) or 960)
        ocr_crop, sx, sy = self._downscale_if_needed(scan_crop, max_w)

        world_ocr = self.world_ocr or self.ocr
        t0 = time.time()
        raw_boxes = world_ocr.read_boxes(
            ocr_crop, offset_x=rx, offset_y=ry, scale_x=sx, scale_y=sy, min_score=0.55)
        w_ms = round((time.time() - t0) * 1000, 1)
        self.stats["world_ocr_ms"] = w_ms
        if not self.stats.get("ocr_ms"):
            self.stats["ocr_ms"] = w_ms

        merged = self._filter_and_merge(raw_boxes, use_noise=use_noise, frame_bgr=full_frame)

        # Altyazı bandındaki kutular hızlı şerit motoruna aittir; tracker'da çiftlenmez
        world_candidates = []
        for b in merged:
            if (self.roi or use_auto_sub) and is_in_auto_subtitle_zone(b["bbox"], fw, fh, self.roi):
                continue
            b["is_subtitle"] = False
            world_candidates.append(b)

        scanned_region = None if is_freeze else (rx, ry, rw, rh)
        with self._box_lock:
            visible, need_tr = self.tracker.update(
                world_candidates,
                full_frame,
                is_freeze_mode=is_freeze,
                stabilization_frames=stab,
                scanned_region=scanned_region,
                style_sampler=lambda fr, bb: sample_box_style(fr, bb, frame_w=fw),
            )

        if not is_freeze:
            # Canlı modda çeviri arka planda; şimdilik mevcut (çevrilmiş) kutuları yay
            self._translate_world_async(need_tr)
            with self._box_lock:
                combined = self._combined_boxes_locked()
                self.stats["boxes"] = len(combined)
                self._emit_active_outputs(mode, combined, origin, (fw, fh))
                self._emit("on_stats", dict(self.stats))
            return

        tr_ms, last_src = self._translate_pending_boxes(need_tr)

        with self._box_lock:
            if tr_ms or last_src:
                self._update_tr_stats(tr_ms, last_src)
            if is_freeze:
                for box in need_tr:
                    if box.translated_text and not box.is_proper_noun and box not in visible:
                        visible.append(box)
                combined = list(self._active_sub_boxes) + visible
            else:
                combined = self._combined_boxes_locked()
            self.stats["boxes"] = len(combined)
            self._emit_active_outputs(mode, combined, origin, (fw, fh))
            self._emit("on_stats", dict(self.stats))

    def process_full_frame(self, full_frame, origin: tuple = (0, 0), is_freeze: bool = False):
        """Tek karede altyazı-öncelikli hızlı tarama + aralık dolunca dünya/UI taraması yapar."""
        if full_frame is None or not getattr(full_frame, "size", 0):
            return

        fh, fw = full_frame.shape[:2]
        mode = self.settings.get("patch_mode", "full_patch")
        stab = 1 if is_freeze else int(self.settings.get("stabilization_frames", 2) or 2)
        world_interval = float(self.settings.get("world_scan_interval", 0.55) or 0.55)
        now = time.time()

        # 1) Ekrandan silinen dünya kutularını OCR beklemeden kaldır
        if not is_freeze and self.tracker.check_disappearances(full_frame):
            self.stats["boxes"] = len(self._combined_boxes())
            self._emit_active_outputs(mode, self._combined_boxes(), origin, (fw, fh))

        # 2) Hızlı Altyazı Şeridi Pass (Her karede ilk öncelik)
        did_sub_ocr = self._process_subtitle_band(full_frame, origin, mode, is_freeze=is_freeze)

        # 3) Dünya OCR zamanı geldi mi? (Altyazı OCR çalıştıysa aynı karede ertelenir)
        world_due = is_freeze or (self._prev_full is None) or (
            not did_sub_ocr and (now - self._last_world_ocr_ts) >= world_interval
        )
        if not world_due:
            if not is_freeze and self._prev_full is not None:
                pending = self.tracker.promote_pending(full_frame, stabilization_frames=stab)
                if pending:
                    tr_ms, last_src = self._translate_pending_boxes(pending)
                    self._update_tr_stats(tr_ms, last_src)
                    self.stats["boxes"] = len(self._combined_boxes())
                    self._emit_active_outputs(mode, self._combined_boxes(), origin, (fw, fh))
                    self._emit("on_stats", dict(self.stats))
            return

        # 4) Dünya / UI OCR Pass
        self._last_world_ocr_ts = now
        self._process_world_pass(full_frame, origin, mode, is_freeze=is_freeze, stab=stab)

    def _translate_world_async(self, need_tr: list[TrackedBox]):
        """Dünya kutularını arka planda toplu çevirir; bitince güncel kutuları yayar."""
        if not need_tr:
            return
        for b in need_tr:
            b.translation_requested = True
        gen = self._gen

        def _job():
            try:
                tr_ms, last_src = self._translate_pending_boxes(need_tr)
            except Exception as e:
                self._emit("on_error", f"{e}")
                return
            if self._stop.is_set() or self._frozen or gen != self._gen:
                return
            frame = self._latest_frame
            if frame is None or not getattr(frame, "size", 0):
                return
            fh, fw = frame.shape[:2]
            mode = self.settings.get("patch_mode", "full_patch")
            with self._box_lock:
                if gen != self._gen:
                    return
                self._update_tr_stats(tr_ms, last_src)
                combined = self._combined_boxes_locked()
                self.stats["boxes"] = len(combined)
                self._emit_active_outputs(mode, combined, self._latest_origin, (fw, fh))
                self._emit("on_stats", dict(self.stats))

        try:
            self._tr_executor.submit(_job)
        except RuntimeError:
            # Executor kapatılmışsa eşzamanlı çevir
            _job()

    def _translate_pending_boxes(self, need_tr: list[TrackedBox]) -> tuple[float, str]:
        if not need_tr:
            return 0.0, ""
        for b in need_tr:
            b.translation_requested = True
        t1 = time.time()
        batch_res = self.translator.translate_batch([b.original_text for b in need_tr])
        tr_ms = round((time.time() - t1) * 1000, 1)

        last_src = ""
        for box, res in zip(need_tr, batch_res):
            if not res:
                continue
            box.translated_text = res.get("translated", "")
            box.source = res.get("source", "")
            box.speaker = res.get("speaker", "")
            box.is_proper_noun = bool(res.get("is_proper_noun", False))
            if box.source:
                last_src = box.source
        return tr_ms, last_src

    def _emit_active_outputs(self, mode: str, boxes: list[TrackedBox],
                             origin: tuple, frame_size: tuple):
        ready_boxes = [
            b for b in boxes
            if b.translated_text and not b.is_proper_noun
        ]

        if mode == "hybrid":
            sub_boxes = [b for b in ready_boxes if b.is_subtitle]
            world_boxes = [b for b in ready_boxes if not b.is_subtitle]
            self._emit("on_boxes", world_boxes, origin, frame_size)

            if sub_boxes:
                sub_boxes.sort(key=lambda b: (b.smoothed_bbox[1], b.smoothed_bbox[0]))
                parts = []
                src = ""
                for sb in sub_boxes:
                    parts.append(f"{sb.speaker}: {sb.translated_text}" if sb.speaker else sb.translated_text)
                    if sb.source:
                        src = sb.source
                sub_text = " ".join(parts).strip()
                if sub_text != self._last_hybrid_sub:
                    self._last_hybrid_sub = sub_text
                    self.stats["last_text"] = sub_text
                    self._emit("on_text", sub_text, src)
            else:
                if self._last_hybrid_sub:
                    self._last_hybrid_sub = ""
                    self._emit("on_text", "", "")
        else:
            # full_patch
            self._emit("on_boxes", ready_boxes, origin, frame_size)
            if ready_boxes:
                subs = [b for b in ready_boxes if b.is_subtitle]
                pick = subs[-1] if subs else ready_boxes[-1]
                summary = f"{pick.speaker}: {pick.translated_text}" if pick.speaker else pick.translated_text
                self.stats["last_text"] = summary
            else:
                self.stats["last_text"] = ""

    # ------------------------------------------------------------ yardımcı
    @staticmethod
    def _downscale_if_needed(frame, max_w: int):
        """Genişliği max_w üstündeyse küçültür ve ters ölçek çarpanını döner."""
        if not max_w or frame.shape[1] <= max_w:
            return frame, 1.0, 1.0
        try:
            import cv2
            fh, fw = frame.shape[:2]
            nw = int(max_w)
            nh = max(1, int(round(fh * (nw / float(fw)))))
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            return resized, fw / float(nw), fh / float(nh)
        except Exception:
            return frame, 1.0, 1.0

    def _find_dirty_region(self, prev_frame, cur_frame, cols: int = 4, rows: int = 3):
        """
        Ekranı 4x3 ızgaraya böler, değişen karoları kapsayan dikdörtgeni döner.
        Hiç değişim yoksa None döner.
        """
        fh, fw = cur_frame.shape[:2]
        if prev_frame is None or prev_frame.shape != cur_frame.shape:
            return (0, 0, fw, fh)

        try:
            import cv2
            grid_w, grid_h = cols * 40, rows * 30
            s1 = cv2.resize(prev_frame, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
            s2 = cv2.resize(cur_frame, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
            diff = cv2.absdiff(s1, s2)
            # Piksel kanallarından herhangi birinde >18 fark olan noktalar
            mask = np.max(diff, axis=2) > 18

            changed_cols = []
            changed_rows = []
            cell_w = 40
            cell_h = 30
            for r in range(rows):
                for c in range(cols):
                    tile = mask[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                    if (np.count_nonzero(tile) / float(tile.size)) > 0.025:
                        changed_cols.append(c)
                        changed_rows.append(r)

            if not changed_cols:
                return None

            min_c, max_c = min(changed_cols), max(changed_cols)
            min_r, max_r = min(changed_rows), max(changed_rows)

            x1 = max(0, int(min_c * fw / cols) - 16)
            y1 = max(0, int(min_r * fh / rows) - 16)
            x2 = min(fw, int((max_c + 1) * fw / cols) + 16)
            y2 = min(fh, int((max_r + 1) * fh / rows) + 16)
            return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))
        except Exception:
            return (0, 0, fw, fh)

    @staticmethod
    def _has_changed(img1, img2, threshold: float = 0.96) -> bool:
        """Küçültüp karşılaştırır: 80x40 üzerinde fark oranı."""
        if img1 is None or img2 is None:
            return True
        try:
            import cv2
            if img1.shape != img2.shape:
                return True
            s1 = cv2.resize(img1, (80, 40), interpolation=cv2.INTER_AREA)
            s2 = cv2.resize(img2, (80, 40), interpolation=cv2.INTER_AREA)
            diff = cv2.absdiff(s1, s2)
            return (np.count_nonzero(diff) / float(s1.size)) > (1.0 - threshold)
        except Exception:
            return True

    @staticmethod
    def _is_similar(t1: str, t2: str, ratio: float = 0.80) -> bool:
        if not t1 or not t2:
            return False
        return difflib.SequenceMatcher(None, t1.strip().lower(),
                                       t2.strip().lower()).ratio() > ratio

    def _emit(self, name: str, *args):
        fn = self.cb.get(name)
        if not fn:
            return
        try:
            fn(*args)
        except Exception as e:
            print(f"[PIPELINE] callback '{name}' hatası: {e}")

    def _emit_state(self, state: str):
        if state == self._last_state:
            return
        self._last_state = state
        self._emit("on_state", state)
