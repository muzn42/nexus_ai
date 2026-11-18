"""
NEXUS AI — Uygulama Denetleyicisi

Tüm motorları (OCR, sözlük, çeviri, hat) tek yerde tutar ve arayüze
signal'lerle haber verir. Arayüz pencereleri birbirinden bağımsız kalır;
hepsi bu denetleyiciyi konuşur.

İş parçacığı kuralı: pipeline kendi thread'inde çalışır, sonuçları
signal ile yayınlar; Qt bunları otomatik olarak ana thread'e taşır.
"""
import threading

from PySide6.QtCore import QObject, Signal

from core.config_manager import DATA_DIR, ConfigManager, SettingsManager
from core.db_catalog import DictionaryLibrary, ensure_seed_catalog
from core.db_manager import AutoLearnDB, DBManager
from core.ocr_engine import OCREngine
from core.pipeline import TranslationPipeline
from core.theme import DEFAULT_PRESET, preset
from core.translation_engine import TranslationEngine


class Controller(QObject):
    """Motorlar + ayarlar + hat yönetimi."""

    text_ready = Signal(str, str)           # çeviri, kaynak etiketi
    partial_ready = Signal(str)             # SSE kısmi çeviri
    boxes_ready = Signal(list, object, object)  # tracked boxes, origin, frame_size
    state_changed = Signal(str)             # idle | running | paused | error
    stats_changed = Signal(dict)
    toast = Signal(str, str)                # mesaj, ton
    roi_changed = Signal(object)            # (x,y,w,h) veya None
    dict_changed = Signal(str)              # aktif sözlük yolu
    mode_changed = Signal(str)              # full_patch | hybrid | subtitle_only
    freeze_changed = Signal(bool)           # Dondur & Oku durumu

    def __init__(self):
        super().__init__()
        ensure_seed_catalog()

        self.settings = SettingsManager.load()
        self.library = DictionaryLibrary()

        self.db_manager = DBManager(self.settings.get("db_path", ""))
        self.auto_learn = AutoLearnDB(DATA_DIR)
        self.ocr_engine = self._build_ocr()
        self.world_ocr_engine = self._build_world_ocr()
        self.translator = self._build_translator()

        self.pipeline = None
        last_roi = self.settings.get("last_roi")
        self.roi = tuple(last_roi) if isinstance(last_roi, (list, tuple)) and len(last_roi) == 4 else None
        self.hud = None
        self.patch_overlay = None
        self.window_handle = int(self.settings.get("window_handle", 0) or 0)
        self._hotkey_stop = threading.Event()

        self.boxes_ready.connect(self._on_boxes_ready)

    # ------------------------------------------------------------ motorlar
    def _build_ocr(self) -> OCREngine:
        s = self.settings
        return OCREngine(
            version=s.get("paddle_version", "PP-OCRv6"),
            use_mkldnn=s.get("use_mkldnn", True),
            model_size=s.get("ocr_model_size", "small"),
            device=s.get("ocr_device", "gpu"),
        )

    def _build_world_ocr(self) -> OCREngine:
        s = self.settings
        if not s.get("dual_ocr_enabled", True):
            return self.ocr_engine
        w_ver = s.get("world_paddle_version", "PP-OCRv6")
        w_size = s.get("world_ocr_model_size", "small")
        w_dev = s.get("world_ocr_device", "cpu")
        if (w_ver, w_size, w_dev) == (
            s.get("paddle_version", "PP-OCRv6"),
            s.get("ocr_model_size", "small"),
            s.get("ocr_device", "gpu"),
        ):
            return self.ocr_engine
        return OCREngine(
            version=w_ver,
            use_mkldnn=s.get("use_mkldnn", True),
            model_size=w_size,
            device=w_dev,
        )

    def _build_translator(self) -> TranslationEngine:
        s = self.settings
        return TranslationEngine(
            db_manager=self.db_manager,
            auto_learn_db=self.auto_learn,
            fallback_engine=s.get("fallback_engine", "Akıllı Zincir (GPT-OSS → Gemini)"),
            target_language=s.get("target_language", "Türkçe"),
            gemini_api_key=s.get("gemini_api_key", ""),
            groq_api_key=s.get("groq_api_key", ""),
            evren_api_key=s.get("evren_api_key", ""),
            auto_learn_enabled=s.get("auto_learn_enabled", False),
        )

    def rebuild_ocr(self):
        self.ocr_engine = self._build_ocr()
        self.world_ocr_engine = self._build_world_ocr()
        if self.pipeline:
            self.pipeline.ocr = self.ocr_engine
            self.pipeline.world_ocr = self.world_ocr_engine

    def rebuild_translator(self):
        self.translator = self._build_translator()
        if self.pipeline:
            self.pipeline.translator = self.translator

    # ------------------------------------------------------------ ayarlar
    def save(self):
        SettingsManager.save(self.settings)

    def set_setting(self, key, value, autosave=True):
        self.settings[key] = value
        if autosave:
            self.save()
        if self.pipeline:
            self.pipeline.update_settings(self.settings)
        if self.patch_overlay and key in ("font_family", "chameleon_opacity", "auto_text_color"):
            self.patch_overlay.apply_settings(self.settings)

    def style(self) -> dict:
        """HUD görünüm stili (ön ayar + ince ayarlar)."""
        name = self.settings.get("subtitle_preset", DEFAULT_PRESET)
        style = preset(name)
        for k in ("font_family", "font_size", "text_color", "stroke_color",
                  "stroke_width", "bg_color", "opacity_mode", "bg_opacity",
                  "line_spacing", "max_lines"):
            if k in self.settings:
                style[k] = self.settings[k]
        return style

    # ------------------------------------------------------------ sözlük
    def active_dictionary(self):
        return self.library.find_by_path(self.settings.get("db_path", ""))

    def set_dictionary(self, db_path: str, announce=True):
        self.settings["db_path"] = db_path or ""
        self.save()
        self.db_manager.reload(self.settings["db_path"])
        entry = self.library.find_by_path(db_path)
        if announce and entry:
            self.toast.emit(f"Aktif sözlük: {entry.game}", "ok")
        self.dict_changed.emit(db_path or "")
        return entry

    # ------------------------------------------------------------ alan
    def set_roi(self, roi, profile_name: str = ""):
        self.roi = tuple(roi) if roi else None
        self.settings["last_roi"] = list(self.roi) if self.roi else []
        self.save()
        if self.pipeline:
            self.pipeline.set_roi(self.roi)
        if profile_name and self.roi:
            ConfigManager.save_profile(profile_name, list(self.roi))
        self.roi_changed.emit(self.roi)

    # ------------------------------------------------------------ yama katmanı & modlar
    def ensure_patch_overlay(self):
        if self.patch_overlay is None:
            from ui.qt.patch_overlay import PatchOverlayWindow
            self.patch_overlay = PatchOverlayWindow(
                self.settings.get("font_family", "Segoe UI")
            )
            self.patch_overlay.apply_settings(self.settings)
        return self.patch_overlay

    def _on_boxes_ready(self, boxes, origin, frame_size):
        if not boxes and (self.patch_overlay is None or not self.patch_overlay.isVisible()):
            return
        overlay = self.ensure_patch_overlay()
        overlay.apply_settings(self.settings)
        overlay.set_freeze_active(bool(self.pipeline and self.pipeline.is_frozen))
        overlay.set_boxes(boxes, origin, frame_size)

    def set_patch_mode(self, mode: str):
        if mode not in ("full_patch", "hybrid", "subtitle_only"):
            mode = "full_patch"
        self.set_setting("patch_mode", mode)
        if mode == "subtitle_only" and self.patch_overlay:
            self.patch_overlay.clear_boxes()
            self.patch_overlay.hide()
        if mode == "full_patch" and self.hud:
            self.hud.hide()
        names = {
            "full_patch": "Tam Yama (Her Yer)",
            "hybrid": "Hibrit (Altyazı HUD + Yama)",
            "subtitle_only": "Sadece Altyazı",
        }
        self.mode_changed.emit(mode)
        self.toast.emit(f"Mod: {names.get(mode, mode)}", "info")

    def cycle_patch_mode(self):
        order = ("full_patch", "hybrid", "subtitle_only")
        cur = self.settings.get("patch_mode", "full_patch")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "full_patch"
        self.set_patch_mode(nxt)

    def toggle_freeze_scan(self):
        p = self._ensure_pipeline()
        p.update_settings(self.settings)
        overlay = self.ensure_patch_overlay()
        frozen = p.trigger_freeze_scan()
        overlay.set_freeze_active(frozen)
        if frozen:
            overlay.show()
            overlay.ensure_topmost(force_style=True)
            self.toast.emit("Anlık Dondur & Oku aktif (F7 ile dön)", "info")
        else:
            overlay.clear_boxes()
            self.toast.emit("Canlı yama moduna dönüldü", "ok")
        self.freeze_changed.emit(frozen)

    # ------------------------------------------------------------ hat
    def _ensure_pipeline(self) -> TranslationPipeline:
        if self.pipeline is None:
            self.pipeline = TranslationPipeline(
                ocr_engine=self.ocr_engine,
                translation_engine=self.translator,
                settings=self.settings,
                callbacks={
                    "on_text": lambda t, s: self.text_ready.emit(t, s),
                    "on_partial": lambda t: self.partial_ready.emit(t),
                    "on_boxes": lambda b, o, fs: self.boxes_ready.emit(b, o, fs),
                    "on_stats": lambda d: self.stats_changed.emit(d),
                    "on_state": lambda s: self.state_changed.emit(s),
                    "on_error": lambda m: self.toast.emit(m, "danger"),
                },
                world_ocr_engine=self.world_ocr_engine,
            )
            self.pipeline.set_source(
                self.settings.get("source_type", "screen"),
                self.settings.get("camera_index", 0),
                self.window_handle,
            )
            if self.roi:
                self.pipeline.set_roi(self.roi)
        return self.pipeline

    def start(self) -> bool:
        p = self._ensure_pipeline()
        p.update_settings(self.settings)
        if self.settings.get("patch_mode", "full_patch") != "subtitle_only":
            self.ensure_patch_overlay()
        p.start()
        return True

    def pause(self):
        if self.pipeline:
            self.pipeline.pause()
        if self.patch_overlay:
            self.patch_overlay.clear_boxes()
            self.patch_overlay.hide()
        self.freeze_changed.emit(False)

    def stop(self):
        if self.pipeline:
            self.pipeline.stop()
        if self.patch_overlay:
            self.patch_overlay.clear_boxes()
            self.patch_overlay.hide()
        self.freeze_changed.emit(False)

    def toggle(self):
        p = self._ensure_pipeline()
        if p.is_running:
            self.pause()
        else:
            self.start()

    def apply_source(self, source_type: str, camera_index: int = 0,
                     window_handle: int = 0):
        self.settings["source_type"] = source_type
        self.settings["camera_index"] = camera_index
        if window_handle:
            self.settings["window_handle"] = int(window_handle)
            self.window_handle = int(window_handle)
        self.save()
        if self.pipeline:
            self.pipeline.update_settings(self.settings)
            self.pipeline.set_source(source_type, camera_index, self.window_handle)

    def select_window(self, hwnd: int, title: str = ""):
        """
        Belirli bir pencereyi kaynak yapar. ROI o pencereye GÖRELİ olur,
        yani pencere taşınsa bile takip edilir.
        """
        self.window_handle = int(hwnd)
        self.apply_source("window", 0, hwnd)
        if title:
            self.settings["window_title"] = title
            self.save()
        self.roi = None
        if self.pipeline:
            self.pipeline.set_roi(None)
        self.roi_changed.emit(None)
        return True

    # ------------------------------------------------------------ kısayollar
    def start_hotkeys(self, handlers: dict):
        """
        handlers: {"f9": callable, "f10": callable, ...}
        `keyboard` paketi yoksa sessizce devre dışı kalır.
        """
        try:
            import keyboard
        except Exception as e:
            print(f"[HOTKEY] keyboard paketi yok: {e}")
            return False

        def loop():
            import time
            keys = {k.lower(): v for k, v in handlers.items() if k}
            pressed = set()
            while not self._hotkey_stop.is_set():
                try:
                    for k, fn in keys.items():
                        # `keyboard.is_pressed` yalnızca tam adla çalışır
                        if keyboard.is_pressed(k):
                            if k not in pressed:
                                pressed.add(k)
                                try:
                                    fn()
                                except Exception as ex:
                                    print(f"[HOTKEY] {k} hatası: {ex}")
                        else:
                            pressed.discard(k)
                except Exception:
                    pass
                time.sleep(0.03)

        self._hotkey_thread = threading.Thread(target=loop, name="nexus-hotkeys",
                                               daemon=True)
        self._hotkey_thread.start()
        return True

    # ------------------------------------------------------------ ısınma
    def warmup_ocr(self):
        """
        OCR motorunu arka planda hazırlar. İlk okuma 8-20 sn sürebildiği için
        kullanıcı 'Başlat'a bastığında beklemesin.
        """
        import threading

        def run():
            try:
                import time
                import numpy as np
                # Sözlük yüklemesi bitene kadar bekle (GIL/disk çekişmesi
                # OCR açılışını 30 sn'ye çıkarabiliyor)
                waited = 0.0
                while not getattr(self.db_manager, "is_loaded", True) and waited < 30:
                    time.sleep(0.2)
                    waited += 0.2
                img = np.full((80, 480, 3), 255, dtype=np.uint8)
                t0 = time.time()
                self.ocr_engine.read_text(img)
                dt = time.time() - t0
                msg = f"OCR hazır ({dt:.1f} sn) · {self.ocr_engine.status()}"
                if self.world_ocr_engine is not self.ocr_engine:
                    self.world_ocr_engine.read_text(img)
                    msg += f" | Dünya: {self.world_ocr_engine.status()}"
                self.toast.emit(msg, "ok")
            except Exception as e:
                self.toast.emit(f"OCR ısınma hatası: {e}", "danger")

        threading.Thread(target=run, name="nexus-ocr-warmup", daemon=True).start()

    # ------------------------------------------------------------ kapanış
    def shutdown(self):
        try:
            self.stop()
        except Exception:
            pass
        self._hotkey_stop.set()
        try:
            if self.pipeline and self.pipeline.source:
                self.pipeline.source.release()
        except Exception:
            pass
        try:
            if self.patch_overlay:
                self.patch_overlay.close()
            if self.hud:
                self.settings["hud_geometry"] = self.hud.geometry_string()
            self.save()
        except Exception:
            pass
