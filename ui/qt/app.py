"""
NEXUS AI — Qt Uygulama Girişi

Sorumluluklar:
  - QApplication + yüksek DPI + stil sayfası
  - Denetleyiciyi (motorlar) kurmak
  - Ana pencereyi açmak
  - Global kısayolları güvenli biçimde UI'a bağlamak (thread → signal)
  - İlk açılışta sihirbazı göstermek
"""
import os
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from core.theme import F, qss
from ui.qt.controller import Controller
from ui.qt.main_window import MainWindow


class HotkeyBridge(QObject):
    """Kısayol thread'inden gelen çağrıları GUI thread'ine taşır."""

    start_toggle = Signal()
    reselect = Signal()
    settings = Signal()
    lock = Signal()
    quit_app = Signal()


def configure_app_env():
    """Qt'den önce ayarlanması gereken ortam değişkenleri."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # Windows'ta görev çubuğunda ayrı ikon grubu (AppUserModelID)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NexusAI.Translator.2")
        except Exception:
            pass


def exclude_app_windows_from_capture():
    """
    Uygulamanın TÜM pencerelerini ekran yakalamadan gizler.
    Böylece OCR kendi arayüzünü (HUD, ayarlar, panel) hiçbir zaman okumaz.
    """
    from PySide6.QtWidgets import QApplication
    from core.windows import exclude_widget_from_capture

    count = 0
    for w in QApplication.topLevelWidgets():
        try:
            if not w.isVisible():
                continue
            if getattr(w, "_capture_excluded_done", False):
                continue
            if exclude_widget_from_capture(w, True):
                w._capture_excluded_done = True
                count += 1
        except Exception:
            pass
    return count


def main() -> int:
    configure_app_env()

    # DİKKAT: Yüksek DPI politikası QApplication'dan ÖNCE ayarlanmalı
    try:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("NEXUS AI")
    app.setApplicationDisplayName("NEXUS AI")
    app.setOrganizationName("NexusAI")
    app.setFont(QFont(F.FAMILY, 10))
    app.setStyleSheet(qss())

    controller = Controller()
    win = MainWindow(controller)

    # --- kısayollar ---
    bridge = HotkeyBridge()

    def do_lock():
        if controller.hud:
            controller.hud.set_locked(not controller.hud.locked)

    bridge.start_toggle.connect(controller.toggle)
    bridge.reselect.connect(win._select_area)
    bridge.settings.connect(win._open_settings)
    bridge.lock.connect(do_lock)
    bridge.quit_app.connect(win._quit)

    s = controller.settings
    controller.start_hotkeys({
        s.get("hotkey_start", "f9"): bridge.start_toggle.emit,
        s.get("hotkey_reselect", "f10"): bridge.reselect.emit,
        s.get("hotkey_settings", "f11"): bridge.settings.emit,
        s.get("hotkey_lock", "f8"): bridge.lock.emit,
        s.get("hotkey_exit", "f12"): bridge.quit_app.emit,
    })

    # Son alanı geri yükle
    if s.get("last_roi"):
        try:
            controller.set_roi(tuple(s["last_roi"]))
        except Exception:
            pass

    win.show()

    # Tüm Nexus pencerelerini ekran yakalamadan gizle (OCR kendi UI'ını okumasın)
    QTimer.singleShot(400, exclude_app_windows_from_capture)
    _guard = QTimer()
    _guard.timeout.connect(exclude_app_windows_from_capture)
    _guard.start(1500)
    win._capture_guard = _guard

    # OCR'ı arka planda hazırla (ilk 'Başlat'ta bekleme olmasın)
    QTimer.singleShot(1200, controller.warmup_ocr)

    # İlk açılış → sihirbaz
    if not s.get("onboarding_done", False):
        from ui.qt.onboarding import OnboardingWindow
        win._onboarding = OnboardingWindow(controller, win)
        win._onboarding.show()
        win._onboarding.raise_()

    # Kaydet: pencere konumu + alan
    def on_about_to_quit():
        try:
            if controller.roi:
                s["last_roi"] = list(controller.roi)
            controller.shutdown()
        except Exception:
            pass

    app.aboutToQuit.connect(on_about_to_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
