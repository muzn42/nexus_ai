"""
NEXUS AI — Çeviri Hattı (Pipeline)

Ekranı yakala → değişti mi? → OCR → çevir → HUD'a bildir.

Tasarım: Saf Python, UI'dan bağımsız. UI katmanı bunu bir iş parçacığında
çalıştırır ve callback'lerle sonuç alır (Qt signal köprüsü üzerinden).

Callback sözleşmesi:
  on_state(state: str)                        → "idle" | "running" | "paused" | "error"
  on_partial(text: str)                       → SSE ile gelen kısmi çeviri
  on_text(translated: str, source: str)       → nihai altyazı
  on_stats(dict)                              → {"ocr_ms", "tr_ms", "source", "total"}
  on_error(message: str)
"""
import difflib
import threading
import time

import numpy as np

from core.capture import make_source
from core.ocr_engine import OCREngine
from core.translation_engine import TranslationEngine


class TranslationPipeline:
    """OCR + çeviri döngüsünün tamamı."""

    def __init__(self, ocr_engine: OCREngine, translation_engine: TranslationEngine,
                 settings: dict, callbacks: dict = None):
        self.ocr = ocr_engine
        self.translator = translation_engine
        self.settings = settings or {}
        self.cb = callbacks or {}

        self.roi = None
        self.source = None

        self._thread = None
        self._stop = threading.Event()
        self._pause = threading.Event()

        self._last_text = ""
        self._prev_img = None
        self._last_state = ""

        self.stats = {"ocr_ms": 0.0, "tr_ms": 0.0, "source": "", "total": 0,
                      "loops": 0, "skipped": 0}

    # ------------------------------------------------------------ kontrol
    def set_roi(self, roi):
        self.roi = tuple(roi) if roi else None
        self._prev_img = None

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
        self._prev_img = None

    def start(self):
        if self._thread and self._thread.is_alive():
            self._pause.clear()
            self._emit_state("running")
            return
        self._stop.clear()
        self._pause.clear()
        self._thread = threading.Thread(target=self._loop, name="nexus-pipeline",
                                        daemon=True)
        self._thread.start()
        self._emit_state("running")

    def pause(self):
        self._pause.set()
        self._emit_state("paused")

    def stop(self):
        self._stop.set()
        self._pause.set()
        th = self._thread
        if th and th.is_alive():
            th.join(timeout=2.0)
        self._thread = None
        self._emit_state("idle")

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._pause.is_set())

    def update_settings(self, settings: dict):
        """Ayarlar değişince motorları yeniden kurmadan güncelle."""
        self.settings = settings or {}
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
            if not self.roi or self.source is None:
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
        frame = self.source.grab(self.roi)
        if frame is None or not getattr(frame, "size", 0):
            return

        # --- değişim algılama (ucuz) ---
        if not self._has_changed(self._prev_img, frame):
            self.stats["skipped"] += 1
            return
        self._prev_img = frame.copy()

        # --- OCR ---
        # Çok geniş bölgelerde OCR süresi alanla birlikte büyür.
        # 960 px üstünü orantılı küçültmek doğruluk kaybı olmadan hız kazandırır.
        ocr_frame = frame
        max_w = int(self.settings.get("ocr_max_width", 960) or 960)
        if max_w and frame.shape[1] > max_w:
            try:
                import cv2
                ratio = max_w / float(frame.shape[1])
                ocr_frame = cv2.resize(
                    frame, (max_w, max(1, int(frame.shape[0] * ratio))),
                    interpolation=cv2.INTER_AREA)
            except Exception:
                ocr_frame = frame

        t0 = time.time()
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

        # --- çeviri ---
        t1 = time.time()
        on_partial = self.cb.get("on_partial")
        translated, source = self.translator.translate(text, on_partial=on_partial)
        self.stats["tr_ms"] = round((time.time() - t1) * 1000, 1)
        self.stats["source"] = source
        self.stats["total"] = getattr(self.translator, "total_translations", 0)

        self._emit("on_text", translated, source)
        self._emit("on_stats", dict(self.stats))

    # ------------------------------------------------------------ yardımcı
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
