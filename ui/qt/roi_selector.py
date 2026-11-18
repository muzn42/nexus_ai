"""
NEXUS AI — Altyazı Alanı Seçici

Eski sürümde alan seçimi OpenCV'nin `selectROI` penceresiyle yapılıyordu:
karanlık, çirkin ve Enter/C tuşlarını bilmek gerekiyordu.

Burada tam ekran, yarı saydam bir katman var:
  - Fareyle sürükle → alanı seç
  - Enter veya çift tık → onayla
  - Esc → iptal
  - Canlı olarak boyut (W×H) gösterilir
"""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from core.theme import C, R


class RoiSelector(QWidget):
    """Tam ekran alan seçici katman."""

    selected = Signal(tuple)   # (x, y, w, h)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)

        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._has_selection = False

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

    # ---------------------------------------------------------- çizim
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))

        rect = self._rect()
        if rect.width() > 1 and rect.height() > 1:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(rect, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

            pen = QPen(QColor(C.ACCENT))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(rect)

            p.setBrush(QColor(C.ACCENT))
            p.setPen(Qt.NoPen)
            for cx, cy in ((rect.left(), rect.top()), (rect.right(), rect.top()),
                           (rect.left(), rect.bottom()), (rect.right(), rect.bottom())):
                p.drawEllipse(QPoint(cx, cy), 4, 4)

            text = f"{rect.width()} × {rect.height()}"
            font = QFont("Segoe UI", 10)
            font.setBold(True)
            p.setFont(font)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(text) + 20
            th = fm.height() + 10
            ty = rect.top() - th - 6
            if ty < 0:
                ty = rect.top() + 6
            box = QRect(rect.left(), ty, tw, th)
            p.setBrush(QColor(21, 26, 33, 240))
            p.setPen(QPen(QColor(C.BORDER), 1))
            p.drawRoundedRect(box, R.SM, R.SM)
            p.setPen(QColor(C.TEXT))
            p.drawText(box, Qt.AlignCenter, text)
        else:
            font = QFont("Segoe UI", 15)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(C.TEXT))
            p.drawText(self.rect().adjusted(0, -40, 0, -40), Qt.AlignCenter,
                       "Altyazı alanını fareyle sürükleyerek seç")
            f2 = QFont("Segoe UI", 10)
            p.setFont(f2)
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(self.rect().adjusted(0, 10, 0, 10), Qt.AlignCenter,
                       "Enter = onayla   ·   Esc = iptal")
        p.end()

    def _rect(self) -> QRect:
        if not self._has_selection:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    # ---------------------------------------------------------- fare
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self._has_selection = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = False
            rect = self._rect()
            if rect.width() < 10 or rect.height() < 10:
                self._has_selection = False
            self.update()

    def mouseDoubleClickEvent(self, e):
        self._confirm()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._confirm()
        elif e.key() == Qt.Key_Escape:
            self.close()

    def _confirm(self):
        rect = self._rect()
        if rect.width() < 10 or rect.height() < 10:
            return
        self.close()
        self.selected.emit((rect.x(), rect.y(), rect.width(), rect.height()))
