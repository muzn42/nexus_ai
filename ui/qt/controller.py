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

    text_ready = Signal(str, str)      # çeviri, kaynak etiketi
    partial_ready = Signal(str)        # SSE kısmi çeviri
    state_changed = Signal(str)        # idle | running | paused | error
    stats_changed = Signal(dict)
    toast = Signal(str, str)           # mesaj, ton
    roi_changed = Signal(object)       # (x,y,w,h) veya None
    dict_changed = Signal(str)         # aktif sözlük yolu

    def __init__(self):
        super().__init__()
        ensure_seed_catalog()

        self.settings = SettingsManager.load()
        self.library = DictionaryLibrary()

        self.db_manager = DBManager(self.settings.get("db_path", ""))
        self.auto_learn = AutoLearnDB(DATA_DIR)
        self.ocr_engine = self._build_ocr()
        self.translator = self._build_translator()

        self.pipeline = None
        last_roi = self.settings.get("last_roi")
        self.roi = tuple(last_roi) if isinstance(last_roi, (list, tuple)) and len(last_roi) == 4 else None
        self.hud = None
        self.window_handle = int(self.settings.get("window_handle", 0) or 0)
        self._hotkey_stop = threading.Event()

    # ------------------------------------------------------------ motorlar
    def _build_ocr(self) -> OCREngine:
        s = self.settings
        return OCREngine(
            version=s.get("paddle_version", "PP-OCRv5"),
            use_mkldnn=s.get("use_mkldnn", True),
            model_size=s.get("ocr_model_size", "small"),
            device=s.get("ocr_device", "cpu"),
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
            auto_learn_enabled=s.get("auto_learn_enabled", True),
        )

    def rebuild_ocr(self):
        self.ocr_engine = self._build_ocr()
        if self.pipeline:
            self.pipeline.ocr = self.ocr_engine

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
                    "on_stats": lambda d: self.stats_changed.emit(d),
                    "on_state": lambda s: self.state_changed.emit(s),
                    "on_error": lambda m: self.toast.emit(m, "danger"),
                },
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
        if not self.roi:
            self.toast.emit("Önce altyazı alanını seçin.", "warn")
            return False
        p = self._ensure_pipeline()
        p.update_settings(self.settings)
        p.start()
        return True

    def pause(self):
        if self.pipeline:
            self.pipeline.pause()

    def stop(self):
        if self.pipeline:
            self.pipeline.stop()

    def toggle(self):
        p = self._ensure_pipeline()
        if p.is_running:
            p.pause()
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
                self.toast.emit(f"OCR hazır ({dt:.1f} sn) · "
                                f"{self.ocr_engine.status()}", "ok")
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
            if self.hud:
                self.settings["hud_geometry"] = self.hud.geometry_string()
            self.save()
        except Exception:
            pass
