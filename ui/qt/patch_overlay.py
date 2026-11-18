"""
NEXUS AI v3 — Canlı Yama Katmanı (PatchOverlayWindow)

Oyunun tamamının üstünde duran, fare tıklamalarını %100 oyuna geçiren
(click-through) şeffaf tam ekran katman.

Özellikler:
  - WDA_EXCLUDEFROMCAPTURE ile ekran yakalamadan tamamen gizlenir (OCR kendi yamasını okumaz).
  - Bukalemun + Buzlu Cam maskesi: orijinal metni bulanıklaştırıp bölgenin yerel
    arka plan rengiyle örter → İngilizce ve Türkçe yazılar asla iç içe geçmez.
  - Orijinal kutu sınırına sadık kalır; Türkçe çeviri uzunsa fontu otomatik küçülterek
    kutuya sığdırır (menüler birbirine girmez).
  - Orijinal yazı rengini, hizasını ve konuşmacı vurgusunu ('Lucia: ...') korur.
"""
import ctypes
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from core.windows import exclude_widget_from_capture

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


class PatchOverlayWindow(QWidget):
    """Tüm ekran/oyun penceresi üzerinde metin yamaları çizen şeffaf katman."""

    def __init__(self, font_family: str = "Segoe UI"):
        super().__init__()
        self.setWindowTitle("NEXUS AI Patch Overlay")
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self._boxes = []
        self._origin = (0, 0)
        self._frame_size = (0, 0)
        self._capture_excluded = False

        self._font_family = font_family or "Segoe UI"
        self._chameleon_opacity = 78
        self._auto_text_color = True
        self._freeze_active = False

        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(400)
        self._topmost_timer.timeout.connect(self.ensure_topmost)
        self._topmost_timer.start()

        self._fit_screen()

    def _fit_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.virtualGeometry()
            self.setGeometry(g)
        else:
            self.setGeometry(0, 0, 1920, 1080)

    def apply_settings(self, settings: dict):
        self._font_family = settings.get("font_family", "Segoe UI") or "Segoe UI"
        self._chameleon_opacity = int(settings.get("chameleon_opacity", 78))
        self._auto_text_color = bool(settings.get("auto_text_color", True))
        self.update()

    def set_freeze_active(self, active: bool):
        self._freeze_active = bool(active)
        self.update()

    def set_boxes(self, boxes: list, origin: tuple = (0, 0), frame_size: tuple = (0, 0)):
        self._boxes = list(boxes or [])
        self._origin = tuple(origin or (0, 0))
        self._frame_size = tuple(frame_size or (0, 0))

        # Kaynak pencere boyutuna ve konumuna hizala (DPI ölçeğini dikkate al)
        if self._frame_size[0] > 0 and self._frame_size[1] > 0:
            dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
            lx = int(round(self._origin[0] / dpr))
            ly = int(round(self._origin[1] / dpr))
            lw = int(round(self._frame_size[0] / dpr))
            lh = int(round(self._frame_size[1] / dpr))
            cur = self.geometry()
            if (cur.x(), cur.y(), cur.width(), cur.height()) != (lx, ly, lw, lh):
                self.setGeometry(lx, ly, lw, lh)

        if self._boxes or self._freeze_active:
            if not self.isVisible():
                self.show()
            self.ensure_topmost()
        self.update()

    def clear_boxes(self):
        self._boxes = []
        self._freeze_active = False
        self.update()

    # ------------------------------------------------------------ Win32 şeffaf/topmost
    def showEvent(self, e):
        super().showEvent(e)
        if not self._capture_excluded:
            ok = exclude_widget_from_capture(self, True)
            self._capture_excluded = ok
        self.ensure_topmost(force_style=True)

    def ensure_topmost(self, force_style: bool = False):
        if sys.platform != "win32" or not self.isVisible():
            return
        try:
            import ctypes.wintypes as wt
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE)
            desired = (style | WS_EX_LAYERED | WS_EX_TOOLWINDOW |
                       WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
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
        except Exception:
            pass

    # ------------------------------------------------------------ tipografi & sığdırma
    @staticmethod
    def _wrap_text(text: str, metrics: QFontMetricsF, max_w: float) -> list[str]:
        words = text.replace("\r", " ").replace("\n", " ").split(" ")
        lines, cur = [], ""
        for w in words:
            if not w:
                continue
            trial = f"{cur} {w}".strip()
            if metrics.horizontalAdvance(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _fit_font_and_wrap(self, full_text: str, rect: QRectF, line_count: int):
        """
        Orijinal kutu sınırına sadık kalarak font boyutunu otomatik ölçekler.
        Döner: (QFont, lines: list[str], QFontMetricsF)
        """
        pad_x = 10.0
        pad_y = 4.0
        avail_w = max(24.0, rect.width() - pad_x)
        avail_h = max(14.0, rect.height() - pad_y)

        est_line_h = rect.height() / max(1, line_count)
        start_px = max(11, min(46, int(round(est_line_h * 0.78))))
        min_px = 10

        best_font = QFont(self._font_family)
        best_font.setWeight(QFont.DemiBold)
        best_lines = [full_text]
        best_metrics = QFontMetricsF(best_font)

        for px in range(start_px, min_px - 1, -1):
            font = QFont(self._font_family)
            font.setPixelSize(px)
            font.setWeight(QFont.DemiBold)
            metrics = QFontMetricsF(font)
            lines = self._wrap_text(full_text, metrics, avail_w)

            line_h = metrics.height() * 1.12
            total_h = line_h * len(lines)
            max_line_w = max((metrics.horizontalAdvance(ln) for ln in lines), default=0.0)

            best_font = font
            best_lines = lines
            best_metrics = metrics

            if total_h <= avail_h + 2.0 and max_line_w <= avail_w + 2.0:
                break

        return best_font, best_lines, best_metrics

    # ------------------------------------------------------------ çizim
    def paintEvent(self, event):
        if not self._boxes and not self._freeze_active:
            return

        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform,
            True,
        )

        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))

        for box in self._boxes:
            if getattr(box, "is_proper_noun", False):
                continue
            tr_text = (getattr(box, "translated_text", "") or "").strip()
            if not tr_text:
                continue

            bx, by, bw, bh = box.smoothed_bbox
            is_sub = bool(getattr(box, "is_subtitle", False))
            # Altyazıda geniş nefes payı, dünya/menü/buton etiketlerinde yan tuş ikonlarına taşmayan sıkı pay
            pad_x = 5.0 if is_sub else 1.5
            pad_y = 2.5 if is_sub else 1.5
            rx = max(0.0, (bx / dpr) - pad_x)
            ry = max(0.0, (by / dpr) - pad_y)
            rw = min(self.width() - rx, (bw / dpr) + pad_x * 2)
            rh = min(self.height() - ry, (bh / dpr) + pad_y * 2)
            if rw <= 4 or rh <= 4:
                continue

            rect = QRectF(rx, ry, rw, rh)
            style = getattr(box, "style", None) or {}
            bg_rgb = style.get("bg_color", (16, 20, 26))
            fg_rgb = style.get("fg_color", (255, 255, 255)) if self._auto_text_color else (255, 255, 255)
            blurred_rgb = style.get("blurred_rgb")
            align = style.get("align", "left")
            if getattr(box, "is_subtitle", False):
                align = "center"

            radius = min(8.0, rh * 0.22)
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            # 1) Buzlu Cam (Blurred Crop) + Bukalemun Yama Zemini
            painter.save()
            painter.setClipPath(path)
            if blurred_rgb is not None and getattr(blurred_rgb, "size", 0):
                bh_px, bw_px = blurred_rgb.shape[:2]
                qimg = QImage(
                    blurred_rgb.data, bw_px, bh_px, bw_px * 3, QImage.Format_RGB888
                )
                painter.drawImage(rect, qimg)

            alpha = int(max(0, min(255, round(self._chameleon_opacity * 255 / 100.0))))
            painter.fillPath(path, QColor(bg_rgb[0], bg_rgb[1], bg_rgb[2], alpha))
            painter.restore()

            # Zarif, çok hafif çerçeve
            bg_lum = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
            border_col = QColor(255, 255, 255, 24) if bg_lum < 140 else QColor(0, 0, 0, 28)
            painter.setPen(QPen(border_col, 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            # 2) Konuşmacı ön eki ve otomatik ölçekli metin
            speaker = (getattr(box, "speaker", "") or "").strip()
            display_full = f"{speaker}: {tr_text}" if speaker else tr_text
            font, lines, metrics = self._fit_font_and_wrap(
                display_full, rect, getattr(box, "line_count", 1)
            )
            painter.setFont(font)

            line_h = metrics.height() * 1.10
            total_h = line_h * len(lines)
            start_y = rect.y() + max(2.0, (rect.height() - total_h) / 2.0) + metrics.ascent()

            fg_color = QColor(fg_rgb[0], fg_rgb[1], fg_rgb[2])
            fg_lum = 0.299 * fg_rgb[0] + 0.587 * fg_rgb[1] + 0.114 * fg_rgb[2]
            outline_color = QColor(0, 0, 0, 210) if fg_lum > 110 else QColor(255, 255, 255, 180)

            # Konuşmacı rengi (orijinal metin sarı değilse sıcak altın, sarıysa camgöbeği)
            is_yellow = fg_rgb[0] > 190 and fg_rgb[1] > 160 and fg_rgb[2] < 110
            speaker_color = QColor("#00E5FF") if is_yellow else QColor("#FFD84D")
            speaker_prefix = f"{speaker}: " if speaker else ""

            for i, ln in enumerate(lines):
                lw = metrics.horizontalAdvance(ln)
                if align == "center":
                    tx = rect.x() + (rect.width() - lw) / 2.0
                else:
                    tx = rect.x() + 5.0
                ty = start_y + i * line_h

                # İlk satırda konuşmacı vurgusu varsa iki parça çiz
                if i == 0 and speaker_prefix and ln.startswith(speaker_prefix):
                    rest = ln[len(speaker_prefix):]
                    self._draw_crisp_text(painter, tx, ty, font, speaker_prefix,
                                          speaker_color, outline_color)
                    sp_w = metrics.horizontalAdvance(speaker_prefix)
                    if rest:
                        self._draw_crisp_text(painter, tx + sp_w, ty, font, rest,
                                              fg_color, outline_color)
                else:
                    self._draw_crisp_text(painter, tx, ty, font, ln,
                                          fg_color, outline_color)

        # 3) Dondur & Oku rozeti (F7 aktifken)
        if self._freeze_active:
            banner = "❄  DONDURULDU — F7 ile canlı moda dön"
            bf = QFont(self._font_family, 10, QFont.DemiBold)
            painter.setFont(bf)
            bm = QFontMetricsF(bf)
            bw_b = bm.horizontalAdvance(banner) + 28
            bh_b = 30.0
            bx_b = (self.width() - bw_b) / 2.0
            brect = QRectF(bx_b, 14.0, bw_b, bh_b)
            bpath = QPainterPath()
            bpath.addRoundedRect(brect, 15.0, 15.0)
            painter.fillPath(bpath, QColor(14, 17, 22, 225))
            painter.setPen(QPen(QColor("#4C8DFF"), 1.2))
            painter.drawPath(bpath)
            painter.setPen(QColor("#E6EDF3"))
            painter.drawText(brect, Qt.AlignCenter, banner)

        painter.end()

    @staticmethod
    def _draw_crisp_text(painter: QPainter, x: float, y: float, font: QFont,
                         text: str, fill_color: QColor, outline_color: QColor):
        path = QPainterPath()
        path.addText(QPointF(x, y), font, text)
        pen = QPen(outline_color)
        pen.setWidthF(2.2)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_color)
        painter.drawPath(path)
