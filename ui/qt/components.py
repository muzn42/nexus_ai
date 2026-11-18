"""
NEXUS AI — Yeniden kullanılabilir Qt bileşenleri

Tasarım kuralı: her bileşen tek iş yapar, tema değerlerini core.theme'den alır.
Hiçbir bileşen kendi rengini/sayısını uydurmaz.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core.theme import C, F, R, S


# ------------------------------------------------------------------ yardımcı
def shadow(widget, blur=28, y=6, alpha=90):
    """
    NOT: QGraphicsDropShadowEffect, stylesheet ile yuvarlatılmış arka planı
    olan widget'larda zemini kaybettiriyor (bilinen Qt davranışı).
    Bu yüzden varsayılan olarak KAPALI — ayrım için ince çerçeve kullanıyoruz.
    """
    if not _SHADOWS_ENABLED:
        return None
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, y)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)
    return eff


_SHADOWS_ENABLED = False


def vbox(parent=None, spacing=S.MD, margins=(0, 0, 0, 0)):
    lay = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    return lay


def hbox(parent=None, spacing=S.MD, margins=(0, 0, 0, 0)):
    lay = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    return lay


def label(text="", variant=None, size=None, bold=False, wrap=False):
    """Hızlı etiket üretici. variant: None | 'muted' | 'faint' | 'heading' | 'display'."""
    lb = QLabel(text)
    if variant:
        lb.setProperty(variant, True)
    if size or bold:
        f = lb.font()
        if size:
            f.setPointSize(size)
        if bold:
            f.setWeight(QFont.DemiBold)
        lb.setFont(f)
    lb.setWordWrap(wrap)
    return lb


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("divider", True)
        self.setFixedHeight(1)


# ------------------------------------------------------------------ kart
class Card(QFrame):
    """
    Temel yüzey. Başlık + alt başlık + içerik alanı.
    Kullanım:
        card = Card("Başlık", "Açıklama")
        card.body.addWidget(...)
    """

    def __init__(self, title="", subtitle="", parent=None, pad=S.LG, elevated=True):
        super().__init__(parent)
        self.setProperty("card", "true")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = vbox(self, spacing=S.SM, margins=(pad, pad, pad, pad))

        self.header = QWidget(self)
        self.header_lay = vbox(self.header, spacing=2, margins=(0, 0, 0, 0))
        self.title_label = label(title, "heading")
        self.subtitle_label = label(subtitle, "muted", size=9)
        self.subtitle_label.setWordWrap(True)
        if title:
            self.header_lay.addWidget(self.title_label)
        if subtitle:
            self.header_lay.addWidget(self.subtitle_label)
        if title or subtitle:
            outer.addWidget(self.header)

        self.body = QWidget(self)
        self.body_lay = vbox(self.body, spacing=S.SM, margins=(0, 0, 0, 0))
        outer.addWidget(self.body, 1)

        if elevated:
            shadow(self, blur=30, y=8, alpha=70)

    def add(self, widget, stretch=0):
        self.body_lay.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.body_lay.addLayout(layout)
        return layout

    def set_subtitle(self, text):
        self.subtitle_label.setText(text)


class Chip(QLabel):
    """Küçük durum etiketi (rozet)."""

    TONES = {
        "ok": (C.OK, "#0E2A17"),
        "warn": (C.WARN, "#2B2008"),
        "danger": (C.DANGER, "#2E1114"),
        "info": (C.INFO, "#0D1E33"),
        "neutral": (C.TEXT_DIM, C.SURFACE_ALT),
    }

    def __init__(self, text="", tone="neutral", parent=None):
        super().__init__(text, parent)
        self.set_tone(tone)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(22)
        f = self.font()
        f.setPointSize(8)
        f.setWeight(QFont.DemiBold)
        self.setFont(f)

    def set_tone(self, tone):
        fg, bg = self.TONES.get(tone, self.TONES["neutral"])
        self.setStyleSheet(
            f"color:{fg}; background-color:{bg}; border-radius:11px; padding:0 10px;")


# ------------------------------------------------------------------ başlık çubuğu
class TitleBar(QWidget):
    """
    Çerçevesiz pencere için sürüklenebilir, minimal başlık çubuğu.
    Sadece gerekli üç düğme: küçült, büyüt, kapat.
    """

    def __init__(self, window, title="NEXUS AI", subtitle="", show_max=True):
        super().__init__(window)
        self._win = window
        self._drag = None
        self.setFixedHeight(48)
        self.setStyleSheet("background: transparent;")

        lay = hbox(self, spacing=S.SM, margins=(S.LG, S.SM, S.SM, S.SM))

        self.logo = QLabel("◆")
        self.logo.setStyleSheet(f"color:{C.ACCENT}; font-size:13pt;")
        lay.addWidget(self.logo)

        titles = QWidget(self)
        tl = vbox(titles, spacing=0)
        self.title_lbl = label(title, size=10, bold=True)
        tl.addWidget(self.title_lbl)
        if subtitle:
            self.sub_lbl = label(subtitle, "faint", size=8)
            tl.addWidget(self.sub_lbl)
        lay.addWidget(titles)
        lay.addStretch(1)

        self.btn_min = self._btn("–", "Küçült")
        self.btn_min.clicked.connect(self._win.showMinimized)
        lay.addWidget(self.btn_min)

        if show_max:
            self.btn_max = self._btn("□", "Büyüt / Geri al")
            self.btn_max.clicked.connect(self._toggle_max)
            lay.addWidget(self.btn_max)

        self.btn_close = self._btn("×", "Kapat", danger=True)
        self.btn_close.clicked.connect(self._win.close)
        lay.addWidget(self.btn_close)

    def _btn(self, text, tip, danger=False):
        b = QPushButton(text)
        b.setObjectName("titleBtn")
        b.setToolTip(tip)
        b.setFixedSize(30, 30)
        b.setCursor(Qt.PointingHandCursor)
        color = C.DANGER if danger else C.TEXT_DIM
        hover_bg = "rgba(248,81,73,40)" if danger else "rgba(255,255,255,26)"
        # Satır içi stil: QSS özgüllük çakışmalarını ve simge kaybını önler
        b.setStyleSheet(
            f"QPushButton#titleBtn {{"
            f" background: transparent; border: none; border-radius: 7px;"
            f" color: {color}; font-family: 'Segoe UI';"
            f" font-size: 13px; font-weight: 600; padding: 0; margin: 0; }}"
            f"QPushButton#titleBtn:hover {{ background: {hover_bg};"
            f" color: {'#FF7B72' if danger else C.TEXT}; }}")
        return b

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    # --- sürükleme ---
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.LeftButton:
            if self._win.isMaximized():
                return
            self._win.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None


class FramelessWindow(QWidget):
    """Çerçevesiz, kendi başlık çubuğu olan pencere tabanı."""

    def __init__(self, title="NEXUS AI", subtitle="", width=1000, height=700,
                 resizable=True, show_max=True):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # objectName + WA_StyledBackground: QSS arka planı gerçekten çizilsin
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(width, height)
        if resizable:
            self.setMinimumSize(min(width, 720), min(height, 520))

        root = vbox(self, spacing=0, margins=(0, 0, 0, 0))
        self._outer = root
        self.titlebar = TitleBar(self, title, subtitle, show_max=show_max)
        root.addWidget(self.titlebar)

        self.content = QWidget(self)
        self.content.setObjectName("content")
        self.content_lay = vbox(self.content, spacing=S.LG,
                                margins=(S.XL, 0, S.XL, S.XL))
        root.addWidget(self.content, 1)

    def set_subtitle(self, text):
        if hasattr(self.titlebar, "sub_lbl"):
            self.titlebar.sub_lbl.setText(text)


# ------------------------------------------------------------------ bildirim
class Toast(QLabel):
    """
    Pencere altında beliren kısa bildirim.
    messagebox yerine kullanılır: akışı bölmez, kendiliğinden kaybolur.
    """

    def __init__(self, parent, text="", tone="neutral", ms=2600):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.show_message(text, tone, ms)

    def show_message(self, text, tone="neutral", ms=2600):
        fg = {"ok": C.OK, "warn": C.WARN, "danger": C.DANGER,
              "info": C.INFO}.get(tone, C.TEXT)
        border = {"ok": C.OK, "warn": C.WARN, "danger": C.DANGER,
                  "info": C.ACCENT}.get(tone, C.BORDER_HI)
        self.setStyleSheet(
            f"color:{fg}; background-color:{C.SURFACE_ALT};"
            f"border:1px solid {border}; border-radius:{R.MD}px;"
            f"padding:10px 16px; font-weight:600;")
        self.setText(text)
        self.adjustSize()
        self.setFixedWidth(min(max(self.sizeHint().width(), 260), self.parent().width() - 80))
        self._reposition()
        self.raise_()
        self.show()
        self._timer.start(ms)

    def _reposition(self):
        p = self.parent()
        if not p:
            return
        w = self.width()
        h = self.height()
        self.move(int((p.width() - w) / 2), int(p.height() - h - 28))


# ------------------------------------------------------------------ ayar satırları
class ToggleRow(QWidget):
    """Etiket + açıklama + anahtar (checkbox)."""

    changed = Signal(bool)

    def __init__(self, title, subtitle="", value=False, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox
        lay = hbox(self, spacing=S.MD)
        texts = QWidget(self)
        tl = vbox(texts, spacing=2)
        tl.addWidget(label(title))
        if subtitle:
            tl.addWidget(label(subtitle, "faint", size=9, wrap=True))
        lay.addWidget(texts, 1)

        self.box = QCheckBox()
        self.box.setChecked(bool(value))
        self.box.toggled.connect(self.changed.emit)
        lay.addWidget(self.box, 0, Qt.AlignTop)


class SliderRow(QWidget):
    """Etiket + değer + kaydırıcı."""

    changed = Signal(int)

    def __init__(self, title, minimum, maximum, value, suffix="", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QSlider
        lay = vbox(self, spacing=S.XS)
        top = hbox(spacing=S.SM)
        top.addWidget(label(title))
        top.addStretch(1)
        self.value_lbl = label(f"{value}{suffix}", size=10, bold=True)
        self.value_lbl.setProperty("accent", True)
        top.addWidget(self.value_lbl)
        lay.addLayout(top)

        self.slider = QSlider(Qt.Horizontal)
        # ÖNEMLİ: setRange/setValue sinyalleri, bağlantı kurulmadan önce
        # yapılmalı — aksi halde init sırasında minimum değer kaydedilir.
        self.slider.blockSignals(True)
        self.slider.setRange(int(minimum), int(maximum))
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self.slider.setCursor(Qt.PointingHandCursor)
        self._suffix = suffix
        self.slider.valueChanged.connect(self._on_change)
        lay.addWidget(self.slider)

    def _on_change(self, v):
        self.value_lbl.setText(f"{v}{self._suffix}")
        self.changed.emit(int(v))

    def value(self):
        return self.slider.value()

    def setValue(self, v):
        self.slider.setValue(int(v))


class ComboRow(QWidget):
    """Etiket + açılır liste."""

    changed = Signal(str)

    def __init__(self, title, items, current="", subtitle="", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox
        lay = hbox(self, spacing=S.MD)
        texts = QWidget(self)
        tl = vbox(texts, spacing=2)
        tl.addWidget(label(title))
        if subtitle:
            tl.addWidget(label(subtitle, "faint", size=9, wrap=True))
        lay.addWidget(texts, 1)

        self.combo = QComboBox()
        self.combo.addItems([str(i) for i in items])
        if current:
            idx = self.combo.findText(str(current))
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.combo.setMinimumWidth(220)
        self.combo.currentTextChanged.connect(self.changed.emit)
        lay.addWidget(self.combo, 0, Qt.AlignTop)

    def current(self):
        return self.combo.currentText()

    def set_current(self, text):
        idx = self.combo.findText(str(text))
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

