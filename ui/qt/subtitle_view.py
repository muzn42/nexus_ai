"""
NEXUS AI — Altyazı Görünümü (SubtitleView)

QPainter ile çizilen, dış çizgili (outline) ve yumuşak gölgeli altyazı.
Tkinter sürümünde her harf için ~80 ayrı text nesnesi çiziliyordu; burada
tek bir QPainterPath stroke+fill ile çiziliyor → çok daha hızlı ve keskin.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import QWidget

from core.theme import C


class SubtitleView(QWidget):
    """Altyazı metnini çizen widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._text = ""
        self._font_family = "Segoe UI"
        self._font_size = 30
        self._text_color = C.SUB_TEXT
        self._stroke_color = C.SUB_STROKE
        self._stroke_width = 3
        self._max_lines = 3
        self._line_spacing = 1.25
        self._align = Qt.AlignHCenter

    # ---------------------------------------------------------- ayarlar
    def set_text(self, text: str):
        text = text or ""
        if text != self._text:
            self._text = text
            self.update()

    def text(self) -> str:
        return self._text

    def apply_style(self, style: dict):
        self._font_family = style.get("font_family", self._font_family)
        self._font_size = int(style.get("font_size", self._font_size))
        self._text_color = style.get("text_color", self._text_color)
        self._stroke_color = style.get("stroke_color", self._stroke_color)
        self._stroke_width = int(style.get("stroke_width", self._stroke_width))
        self._max_lines = int(style.get("max_lines", self._max_lines))
        self._line_spacing = float(style.get("line_spacing", self._line_spacing))
        self.update()

    # ---------------------------------------------------------- çizim
    def _wrap(self, text: str, metrics: QFontMetricsF, width: float) -> list:
        """Metni kelime bazında satırlara böler (en fazla max_lines)."""
        words = text.replace("\r", " ").replace("\n", " ").split(" ")
        lines, cur = [], ""
        for w in words:
            if not w:
                continue
            trial = f"{cur} {w}".strip()
            if metrics.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
                if len(lines) >= self._max_lines:
                    break
        if cur and len(lines) < self._max_lines:
            lines.append(cur)
        # Taşan satırları kırp
        if len(lines) > self._max_lines:
            lines = lines[: self._max_lines]
            last = lines[-1]
            while last and metrics.horizontalAdvance(last + "…") > width:
                last = last[:-1]
            lines[-1] = last + "…"
        return lines

    def paintEvent(self, event):
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.Antialiasing | QPainter.TextAntialiasing |
            QPainter.SmoothPixmapTransform, True)

        font = QFont(self._font_family, self._font_size)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        metrics = QFontMetricsF(font)

        pad = max(8, self._stroke_width * 2 + 4)
        avail = max(40.0, self.width() - pad * 2)
        lines = self._wrap(self._text, metrics, avail)

        line_h = metrics.height() * self._line_spacing
        total_h = line_h * len(lines)
        start_y = (self.height() - total_h) / 2.0 + metrics.ascent()

        # Gölge (hafif, okunabilirliği artırır)
        shadow_off = 2.0

        for i, line in enumerate(lines):
            w = metrics.horizontalAdvance(line)
            x = (self.width() - w) / 2.0
            y = start_y + i * line_h
            path = QPainterPath()
            path.addText(QPointF(x, y), font, line)

            # 1) gölge
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 130))
            painter.translate(shadow_off, shadow_off)
            painter.drawPath(path)
            painter.translate(-shadow_off, -shadow_off)

            # 2) dış çizgi
            if self._stroke_width > 0:
                pen = QPen(QColor(self._stroke_color))
                pen.setWidth(self._stroke_width * 2)
                pen.setJoinStyle(Qt.RoundJoin)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            # 3) dolgu
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._text_color))
            painter.drawPath(path)

        painter.end()
