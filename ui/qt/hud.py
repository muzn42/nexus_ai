"""
NEXUS AI — HUD (Altyazı Katmanı)

Oyunun üstünde duran, tıklamaları oyuna geçiren şeffaf altyazı penceresi.

Öne çıkanlar:
  - Gerçek piksel-alfa saydamlık (kenarlar tırtıksız)
  - "Kilit" modunda fare tıklamaları oyuna geçer (click-through)
  - Fareyle üzerine gelince ince bir araç çubuğu belirir
  - Tekerlek ile altyazı geçmişinde gezinme
  - Ayarlardan gelen stil ön ayarları anında uygulanır
"""
import ctypes
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from core.theme import C, R
from ui.qt.components import Chip
from ui.qt.subtitle_view import SubtitleView

# Windows: gerçek tıklama-geçirgenlik ve her zaman en üstte kalma stilleri
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def _parse_geometry(s: str):
    """'1100x230+120+620' → (x, y, w, h)"""
    try:
        size, x, y = s.split("+")
        w, h = size.split("x")
        return int(x), int(y), int(w), int(h)
    except Exception:
        return 120, 620, 1100, 230


class HUDWindow(QWidget):
    """Altyazı katmanı penceresi."""

    toggle_requested = Signal()
    reselect_requested = Signal()
    settings_requested = Signal()
    close_requested = Signal()
    locked_changed = Signal(bool)
    geometry_changed = Signal()

    def __init__(self, geometry: str = "1000x200+120+620"):
        super().__init__()
        self.setWindowTitle("NEXUS AI HUD")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Kaza ile küçücük kalmasını engelle (metin görünmez olur)
        self.setMinimumSize(360, 90)
        x, y, w, h = _parse_geometry(geometry)
        self.setGeometry(x, y, max(w, 360), max(h, 90))

        self.locked = False
        self._drag_offset = None
        self._resizing = False
        self._resize_origin = None
        self._resize_start = (0, 0)
        self._capture_excluded = False
        self._bg_mode = "Transparent"
        self._bg_color = "#000000"
        self._bg_opacity = 55
        self.history = []
        self.history_index = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = self._build_toolbar()
        root.addWidget(self.toolbar, 0, Qt.AlignHCenter)

        self.view = SubtitleView(self)
        root.addWidget(self.view, 1)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._maybe_hide_toolbar)
        self.toolbar.hide()

        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(250)
        self._topmost_timer.timeout.connect(self.ensure_topmost)
        self._topmost_timer.start()

        self.setMouseTracking(True)
        self.toolbar.setMouseTracking(True)

    # ------------------------------------------------------------ geometri
    def geometry_string(self) -> str:
        g = self.geometry()
        return f"{g.width()}x{g.height()}+{g.x()}+{g.y()}"

    # ------------------------------------------------------------ araç çubuğu
    def _build_toolbar(self):
        bar = QWidget(self)
        bar.setObjectName("hudBar")
        bar.setStyleSheet(
            f"QWidget#hudBar {{ background-color: rgba(21,26,33,238);"
            f" border: 1px solid {C.BORDER}; border-radius: 19px; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.setSpacing(4)

        self.btn_play = self._tool_button("▶", "Başlat / Durdur (F9)", self.toggle_requested)
        lay.addWidget(self.btn_play)

        self.btn_area = self._tool_button("▣", "Altyazı alanını seç (F10)",
                                          self.reselect_requested)
        lay.addWidget(self.btn_area)

        self.btn_settings = self._tool_button("⚙", "Ayarlar (F11)", self.settings_requested)
        lay.addWidget(self.btn_settings)

        self.state_chip = Chip("Hazır", "neutral", bar)
        lay.addWidget(self.state_chip)

        self.btn_lock = self._tool_button("🔓", "Kilitle: tıklamalar oyuna geçsin (F8)",
                                          self._toggle_lock)
        lay.addWidget(self.btn_lock)

        self.btn_close = self._tool_button("✕", "Kapat (F12)", self.close_requested, danger=True)
        lay.addWidget(self.btn_close)

        bar.adjustSize()
        return bar

    def _tool_button(self, text, tip, signal, danger=False):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(26, 26)
        color = C.DANGER if danger else C.TEXT_DIM
        b.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {color};"
            f" font-size: 10pt; border-radius: 6px; padding: 0; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,30); color: {C.TEXT}; }}")
        if hasattr(signal, "emit"):
            b.clicked.connect(signal.emit)
        else:
            b.clicked.connect(signal)
        return b

    # ------------------------------------------------------------ yakalamadan gizle
    def exclude_from_capture(self, enable: bool = True):
        """
        HUD'u EKRAN YAKALAMADAN gizler (Windows 10 2004+).
        Pencere ekranda görünür kalır ama OCR onu asla okumaz.
        Böylece altyazı katmanı kendi yazdığı metni tekrar çözmez.
        """
        from core.windows import exclude_widget_from_capture
        ok = exclude_widget_from_capture(self, enable)
        self._capture_excluded = ok
        if not ok:
            print("[HUD] Uyarı: yakalamadan gizleme desteklenmiyor "
                  "(Windows 10 2004+ gerekir). HUD okunabilir.")
        return ok

    # ------------------------------------------------------------ durum
    def set_state(self, state: str, detail: str = ""):
        tones = {"running": ("Çalışıyor", "ok"),
                 "paused": ("Duraklatıldı", "warn"),
                 "idle": ("Hazır", "neutral"),
                 "error": ("Hata", "danger")}
        text, tone = tones.get(state, ("Hazır", "neutral"))
        if detail:
            text = f"{text} · {detail}"
        self.state_chip.setText(text)
        self.state_chip.set_tone(tone)
        self.state_chip.adjustSize()
        self.btn_play.setText("■" if state == "running" else "▶")
        self.toolbar.adjustSize()

    def set_running(self, running: bool):
        self.set_state("running" if running else "idle")

    def flash(self):
        """Yeni altyazı geldiğinde katmanı en üstte tut ve görünümü tazele."""
        self.ensure_topmost()
        self.view.update()

    # ------------------------------------------------------------ altyazı
    def set_text(self, text: str, source: str = "", add_history: bool = True):
        self.view.set_text(text)
        if add_history and text:
            if not self.history or self.history[-1][0] != text:
                self.history.append((text, source))
                if len(self.history) > 50:
                    self.history.pop(0)
            self.history_index = -1
            self.flash()
        self.update()
        self.ensure_topmost()

    def apply_style(self, style: dict):
        """Görünüm ayarlarını uygular (canlı önizleme dahil)."""
        self.view.apply_style(style)
        # NOT: WA_TranslucentBackground açıkken setStyleSheet("background:...")
        # Qt tarafından ÇİZİLMEZ. Bu yüzden arka planı paintEvent'te çiziyoruz.
        self._bg_mode = style.get("opacity_mode", "Transparent")
        self._bg_color = style.get("bg_color", "#000000")
        self._bg_opacity = int(style.get("bg_opacity", 55))
        self.update()
        if self.toolbar is not None:
            self.toolbar.setStyleSheet(self._toolbar_qss())
        self.ensure_topmost(force_style=True)

    def background_qcolor(self):
        """Aktif moda göre arka plan rengi (alfa dahil). None = şeffaf."""
        from PySide6.QtGui import QColor
        if self._bg_mode == "Transparent":
            return None
        col = QColor(self._bg_color if self._bg_color else "#000000")
        if not col.isValid():
            col = QColor("#000000")
        if self._bg_mode == "Semi":
            col.setAlpha(max(0, min(255, int(self._bg_opacity * 255 / 100))))
        else:  # Opaque
            col.setAlpha(255)
        return col

    def _toolbar_qss(self) -> str:
        bg = self.background_qcolor()
        yes = bool(bg and bg.alpha() > 120)
        pill = "rgba(255,255,255,22)" if yes else "rgba(21,26,33,238)"
        return (f"QWidget#hudBar {{ background-color: {pill};"
                f" border: 1px solid {C.BORDER}; border-radius: 19px; }}")

    # ------------------------------------------------------------ kilit
    def set_locked(self, locked: bool, silent: bool = False):
        self.locked = bool(locked)
        self._apply_click_through(self.locked)
        self.btn_lock.setText("🔒" if self.locked else "🔓")
        if self.locked:
            self.toolbar.hide()
        self.update()
        if not silent:
            self.locked_changed.emit(self.locked)

    def _toggle_lock(self):
        self.set_locked(not self.locked)

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_click_through(self.locked)
        if not self._capture_excluded:
            self.exclude_from_capture(True)
        self.ensure_topmost(force_style=True)

    def _apply_click_through(self, enable: bool):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enable)
        self.ensure_topmost(force_style=True)

    def ensure_topmost(self, force_style: bool = False):
        """HUD penceresini PotPlayer ve tam ekran pencerelerin üstünde (HWND_TOPMOST) tutar."""
        if sys.platform != "win32" or not self.isVisible():
            return
        try:
            import ctypes.wintypes as wt
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE)
            desired = style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            if self.locked:
                desired |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            else:
                desired &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)

            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            if force_style or desired != style:
                user32.SetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE, desired)
                flags |= SWP_FRAMECHANGED

            SetWindowPos = user32.SetWindowPos
            SetWindowPos.argtypes = [
                wt.HWND, wt.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wt.UINT,
            ]
            SetWindowPos.restype = wt.BOOL
            SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, flags)
        except Exception as e:
            if force_style:
                print(f"[HUD] Topmost/Click-through uygulanamadı: {e}")

    # ------------------------------------------------------------ fare
    def enterEvent(self, e):
        if not self.locked:
            self.toolbar.show()
            self._hide_timer.start(2800)
            self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hide_timer.start(700)
        self.update()
        super().leaveEvent(e)

    def _maybe_hide_toolbar(self):
        if self.underMouse() or self.toolbar.underMouse():
            self._hide_timer.start(900)
            return
        if not self.locked:
            self.toolbar.hide()
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.locked:
            pos = e.position().toPoint()
            # Sağ-alt köşede boyutlandırma tutamacı (24x24)
            if (pos.x() > self.width() - 24 and pos.y() > self.height() - 24):
                self._resizing = True
                self._resize_origin = e.globalPosition().toPoint()
                self._resize_start = (self.width(), self.height())
                self.setCursor(Qt.SizeFDiagCursor)
                e.accept()
                return
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._resizing and e.buttons() & Qt.LeftButton:
            delta = e.globalPosition().toPoint() - self._resize_origin
            w = max(360, self._resize_start[0] + delta.x())
            h = max(90, self._resize_start[1] + delta.y())
            self.resize(w, h)
            self.view.update()
            e.accept()
            return
        if self._drag_offset and e.buttons() & Qt.LeftButton and not self.locked:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        # İmleç geri bildirimi (kilit açıkken)
        if not self.locked:
            pos = e.position().toPoint()
            if pos.x() > self.width() - 24 and pos.y() > self.height() - 24:
                self.setCursor(Qt.SizeFDiagCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        if self._resizing:
            self._resizing = False
            self.setCursor(Qt.ArrowCursor)
            self.geometry_changed.emit()

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # --- dinamik metin kutusu arka planı (yalnızca aktif altyazı boyutunda) ---
        trect = self.view.text_box_rect()
        bg = self.background_qcolor()
        if bg is not None and trect is not None:
            mapped = QRectF(
                trect.x() + self.view.x(),
                trect.y() + self.view.y(),
                trect.width(),
                trect.height(),
            )
            path = QPainterPath()
            path.addRoundedRect(mapped, 12.0, 12.0)
            p.fillPath(path, bg)
            if bg.alpha() > 80:
                p.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)

        # --- kilit açıkken konumlandırma kılavuzu ---
        if not self.locked and (trect is None or self.underMouse() or self.toolbar.isVisible()):
            guide = QPainterPath()
            guide.addRoundedRect(QRectF(self.rect().adjusted(1, 1, -1, -1)), 10.0, 10.0)
            p.fillPath(guide, QColor(21, 26, 33, 60))
            p.setPen(QPen(QColor(255, 255, 255, 45), 1.0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPath(guide)

        # --- boyutlandırma tutamacı (yalnızca kilit açıkken) ---
        if not self.locked:
            pen = QPen(QColor(255, 255, 255, 90))
            pen.setWidth(2)
            p.setPen(pen)
            w, h = self.width(), self.height()
            for i in (0, 5, 10):
                p.drawLine(w - 8 - i, h - 2, w - 2, h - 8 - i)
        p.end()
        super().paintEvent(event)

    def wheelEvent(self, e):
        if not self.history:
            return
        if e.angleDelta().y() > 0:            # yukarı → eski
            if self.history_index == -1:
                self.history_index = len(self.history) - 1
            elif self.history_index > 0:
                self.history_index -= 1
        else:                                  # aşağı → yeni
            if self.history_index < len(self.history) - 1:
                self.history_index += 1
            else:
                self.history_index = -1

        if self.history_index == -1:
            text, _ = self.history[-1]
            self.state_chip.setText("Canlı")
            self.state_chip.set_tone("ok")
        else:
            text, _ = self.history[self.history_index]
            self.state_chip.setText(f"Geçmiş {self.history_index + 1}/{len(self.history)}")
            self.state_chip.set_tone("info")
        self.state_chip.adjustSize()
        self.view.set_text(text)
        self.update()
        self.toolbar.adjustSize()
