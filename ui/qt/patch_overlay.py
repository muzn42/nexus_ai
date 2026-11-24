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
import re
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

try:
    from core.button_icons import GLYPH_TOKEN, button_token
except Exception:  # pragma: no cover - modül yoksa yalnızca hap (pill) çizilir
    GLYPH_TOKEN = "BTN"
    button_token = None

# Çeviri içindeki tuş etiketleri: "[R2]", "[BTN]", "[BTN2]"
_TAG_RE = re.compile(r"\[([A-Za-z0-9_\-]{1,10})\]")


def _is_button_tag(tok: str, icon_map: dict) -> bool:
    """Etiket gerçekten bir tuş mu? (ikonu var / bilinen tuş adı / sentetik BTN)"""
    up = tok.upper()
    if up in icon_map or up.startswith(GLYPH_TOKEN):
        return True
    if button_token is not None:
        try:
            return button_token(up) is not None
        except Exception:
            return False
    return False


def _split_atoms(text: str, icon_map: dict) -> list:
    """Metni [("text", str) | ("icon", TOKEN)] parçalarına ayırır."""
    parts, pos = [], 0
    for m in _TAG_RE.finditer(text):
        if not _is_button_tag(m.group(1), icon_map):
            continue
        if m.start() > pos:
            parts.append(("text", text[pos:m.start()]))
        parts.append(("icon", m.group(1).upper()))
        pos = m.end()
    if pos < len(text):
        parts.append(("text", text[pos:]))
    return parts


def _build_icon_map(box) -> dict:
    """TOKEN → [ikon, ...] (okuma sırasıyla); büyük/küçük harf duyarsız."""
    out = {}
    for ic in (getattr(box, "icons", None) or []):
        try:
            rgb = ic.get("rgb")
            if rgb is None or getattr(rgb, "ndim", 0) != 3 or rgb.shape[2] != 3 or rgb.size == 0:
                continue
            out.setdefault(str(ic.get("token", "")).upper(), []).append(ic)
        except Exception:
            continue
    return out

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
    # ------------------------------------------------------------ satır içi tuş ikonları
    @staticmethod
    def _icon_size(metrics: QFontMetricsF, icon_list) -> tuple:
        """İkon atomunun boyutu: yükseklik ≈ satır yüksekliği, en-boy oranı korunur."""
        h = metrics.height() * 1.0
        if icon_list:
            rgb = icon_list[0]["rgb"]
            ih, iw = rgb.shape[:2]
            return (max(4.0, iw * h / max(1, ih)), h)
        return (0.0, h)

    @staticmethod
    def _pill_font(font: QFont) -> QFont:
        pf = QFont(font)
        px = font.pixelSize() if font.pixelSize() > 0 else int(round(QFontMetricsF(font).height() * 0.8))
        pf.setPixelSize(max(7, int(round(px * 0.72))))
        pf.setWeight(QFont.Bold)
        return pf

    @classmethod
    def _atom_width(cls, token: str, metrics: QFontMetricsF, icon_map: dict, font: QFont = None) -> float:
        icon_list = icon_map.get(token)
        if icon_list:
            return cls._icon_size(metrics, icon_list)[0] + 2.0
        # İkon yoksa hap (pill): "R2" yazılı küçük yuvarlak çerçeve
        label = "" if token.startswith(GLYPH_TOKEN) else token
        pm = QFontMetricsF(cls._pill_font(font)) if font is not None else metrics
        inner = pm.horizontalAdvance(label) if label else metrics.height() * 0.55
        return inner + metrics.height() * 0.45 + 2.0

    @classmethod
    def _measure(cls, text: str, metrics: QFontMetricsF, icon_map: dict = None,
                 font: QFont = None) -> float:
        """Etiketleri ikon/hap atomu olarak sayan satır genişliği ölçümü."""
        if not icon_map and "[" not in text:
            return metrics.horizontalAdvance(text)
        total = 0.0
        for kind, val in _split_atoms(text, icon_map or {}):
            if kind == "text":
                total += metrics.horizontalAdvance(val)
            else:
                total += cls._atom_width(val, metrics, icon_map or {}, font)
        return total

    @classmethod
    def _wrap_text(cls, text: str, metrics: QFontMetricsF, max_w: float,
                   icon_map: dict = None, font: QFont = None) -> list[str]:
        words = text.replace("\r", " ").replace("\n", " ").split(" ")
        lines, cur = [], ""
        for w in words:
            if not w:
                continue
            trial = f"{cur} {w}".strip()
            if cls._measure(trial, metrics, icon_map, font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _draw_atoms(self, painter: QPainter, x: float, y: float, font: QFont,
                    metrics: QFontMetricsF, text: str, icon_map: dict, icon_cursor: dict,
                    fill_color: QColor, outline_color: QColor, keep_alive: list) -> float:
        """
        Metin parçalarını _draw_crisp_text ile, [TOKEN] etiketlerini orijinal ikon
        pikselleriyle (yoksa hap) satır içi çizer. Döner: çizilen genişlik.
        """
        cx = x
        for kind, val in _split_atoms(text, icon_map):
            if kind == "text":
                if val:
                    self._draw_crisp_text(painter, cx, y, font, val, fill_color, outline_color)
                    cx += metrics.horizontalAdvance(val)
                continue
            aw = self._atom_width(val, metrics, icon_map, font)
            top = y - metrics.ascent()
            icon_list = icon_map.get(val)
            if icon_list:
                # Aynı etiket birden çok geçerse ikonları sırayla kullan (son ikon tekrar eder)
                k = icon_cursor.get(val, 0)
                ic = icon_list[min(k, len(icon_list) - 1)]
                icon_cursor[val] = k + 1
                rgb = ic["rgb"]
                ih, iw = rgb.shape[:2]
                iw_draw, ih_draw = self._icon_size(metrics, [ic])
                qimg = QImage(rgb.data, iw, ih, iw * 3, QImage.Format_RGB888)
                keep_alive.append((rgb, qimg))  # numpy belleği çizim bitene kadar yaşasın
                painter.drawImage(QRectF(cx + 1.0, top + (metrics.height() - ih_draw) / 2.0,
                                         iw_draw, ih_draw), qimg)
            else:
                self._draw_button_pill(painter, cx + 1.0, top, aw - 2.0, metrics.height(),
                                       "" if val.startswith(GLYPH_TOKEN) else val,
                                       font, fill_color, outline_color)
            cx += aw
        return cx - x

    def _draw_button_pill(self, painter: QPainter, x: float, top: float, w: float, h: float,
                          label: str, font: QFont, fill_color: QColor, outline_color: QColor):
        """İkonu bulunamayan tuş etiketi: açık çerçeveli küçük yuvarlak hap."""
        ph = h * 0.82
        r = QRectF(x, top + (h - ph) / 2.0, max(ph * 0.6, w), ph)
        path = QPainterPath()
        path.addRoundedRect(r, ph * 0.45, ph * 0.45)
        painter.save()
        painter.fillPath(path, QColor(outline_color.red(), outline_color.green(),
                                      outline_color.blue(), 110))
        painter.setPen(QPen(QColor(fill_color.red(), fill_color.green(), fill_color.blue(), 200), 1.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        if label:
            pf = self._pill_font(font)
            painter.setFont(pf)
            painter.setPen(fill_color)
            painter.drawText(r, Qt.AlignCenter, label)
            painter.setFont(font)
        painter.restore()

    def _fit_font_and_wrap(self, full_text: str, rect: QRectF, line_count: int,
                           icon_map: dict = None):
        """
        Orijinal kutu sınırına sadık kalarak font boyutunu otomatik ölçekler.
        icon_map: [TOKEN] etiketleri satır içi ikon atomu olarak ölçülür.
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
            lines = self._wrap_text(full_text, metrics, avail_w, icon_map, font)

            line_h = metrics.height() * 1.12
            total_h = line_h * len(lines)
            max_line_w = max((self._measure(ln, metrics, icon_map, font) for ln in lines), default=0.0)

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
        keep_alive = []  # satır içi ikon QImage'larının numpy tamponları (painter.end'e kadar)

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
            icon_map = _build_icon_map(box)
            icon_cursor: dict = {}
            font, lines, metrics = self._fit_font_and_wrap(
                display_full, rect, getattr(box, "line_count", 1), icon_map
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
                lw = self._measure(ln, metrics, icon_map, font)
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
                        self._draw_atoms(painter, tx + sp_w, ty, font, metrics, rest,
                                         icon_map, icon_cursor, fg_color, outline_color,
                                         keep_alive)
                else:
                    self._draw_atoms(painter, tx, ty, font, metrics, ln, icon_map,
                                     icon_cursor, fg_color, outline_color, keep_alive)

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
