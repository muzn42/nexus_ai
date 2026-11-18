"""
NEXUS AI v2 — Tasarım Sistemi (Design Tokens)

Uygulamanın TÜM görsel kararları burada. Tek kaynak: rengi, boşluğu veya
yazı boyutunu değiştirmek istersen sadece bu dosyaya dokun.

Tasarım ilkesi: "Sakin ve minimal."
  - Tek vurgu rengi (accent), geri kalan nötr.
  - Az sayıda yazı boyutu, net hiyerarşi.
  - Gereksiz çerçeve/gölge yok; ayrım için boşluk ve ince çizgi.
"""


class C:
    """Renk paleti (koyu tema)."""

    # Zemin katmanları (koyudan açığa)
    BG = "#0E1116"            # uygulama zemini
    SURFACE = "#151A21"       # kart
    SURFACE_ALT = "#1B222B"   # kart içi ikincil alan / input
    SURFACE_HI = "#222B36"    # hover

    # Çizgiler
    BORDER = "#262F3B"
    BORDER_HI = "#33404F"

    # Metin
    TEXT = "#E6EDF3"
    TEXT_DIM = "#9AA7B4"
    TEXT_FAINT = "#6B7885"

    # Vurgu (tek vurgu rengi)
    ACCENT = "#4C8DFF"
    ACCENT_HOVER = "#3B7AEA"
    ACCENT_SOFT = "#1B2C4D"   # seçili kart zemini

    # Durum renkleri
    OK = "#3FB950"
    WARN = "#D29922"
    DANGER = "#F85149"
    INFO = "#58A6FF"

    # Altyazı varsayılanları (HUD)
    SUB_TEXT = "#FFFFFF"
    SUB_STROKE = "#000000"
    SUB_BG = "#000000"


class F:
    """Yazı tipleri: (aile, boyut, kalınlık)."""
    FAMILY = "Segoe UI"
    MONO = "Consolas"

    DISPLAY = (FAMILY, 26, "bold")
    TITLE = (FAMILY, 18, "bold")
    HEADING = (FAMILY, 14, "bold")
    BODY = (FAMILY, 12)
    BODY_BOLD = (FAMILY, 12, "bold")
    SMALL = (FAMILY, 11)
    TINY = (FAMILY, 10)


class S:
    """Boşluk ölçeği (px)."""
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32


class R:
    """Köşe yarıçapları (px)."""
    SM = 6
    MD = 10
    LG = 14
    PILL = 999


# --- Bileşen ölçüleri ---
WINDOW_W = 620
WINDOW_H = 880
SETTINGS_W = 860
SETTINGS_H = 640


# --- Altyazı görünüm ön ayarları (HUD) ---
# Kullanıcı "Ayarlar > Görünüm" bölümünden tek tıkla uygular.
SUBTITLE_PRESETS = {
    "Sinematik": {
        "font_family": "Segoe UI", "font_size": 30,
        "text_color": "#FFFFFF", "stroke_color": "#000000", "stroke_width": 3,
        "bg_color": "#000000", "opacity_mode": "Transparent", "bg_opacity": 0,
        "line_spacing": 1.25, "max_lines": 3, "shadow": False,
    },
    "Minimal": {
        "font_family": "Segoe UI", "font_size": 26,
        "text_color": "#F2F5F8", "stroke_color": "#000000", "stroke_width": 1,
        "bg_color": "#000000", "opacity_mode": "Transparent", "bg_opacity": 0,
        "line_spacing": 1.2, "max_lines": 2, "shadow": False,
    },
    "Yüksek Kontrast": {
        "font_family": "Segoe UI", "font_size": 34,
        "text_color": "#FFFFFF", "stroke_color": "#000000", "stroke_width": 4,
        "bg_color": "#000000", "opacity_mode": "Semi", "bg_opacity": 60,
        "line_spacing": 1.3, "max_lines": 3, "shadow": False,
    },
    "Sarışın (Sarı)": {
        "font_family": "Segoe UI", "font_size": 28,
        "text_color": "#FFD84D", "stroke_color": "#1A1200", "stroke_width": 3,
        "bg_color": "#000000", "opacity_mode": "Transparent", "bg_opacity": 0,
        "line_spacing": 1.25, "max_lines": 3, "shadow": False,
    },
    "Net Kutu": {
        "font_family": "Segoe UI", "font_size": 26,
        "text_color": "#FFFFFF", "stroke_color": "#000000", "stroke_width": 0,
        "bg_color": "#000000", "opacity_mode": "Opaque", "bg_opacity": 100,
        "line_spacing": 1.25, "max_lines": 3, "shadow": False,
    },
}

DEFAULT_PRESET = "Sinematik"


def preset(name: str) -> dict:
    """Ada göre ön ayar; yoksa varsayılanı döndürür."""
    return dict(SUBTITLE_PRESETS.get(name, SUBTITLE_PRESETS[DEFAULT_PRESET]))


def apply_ctk():
    """(Eski Tkinter uyumluluğu — artık kullanılmıyor.)"""
    return None


# ============================================================ Qt / QSS
def _qss_core() -> str:
    return f"""
* {{ font-family: "{F.FAMILY}"; font-size: 10pt; outline: none; }}
QWidget {{ background-color: transparent; color: {C.TEXT}; }}
QWidget#root, QWidget#content {{ background-color: {C.BG}; }}
QToolTip {{
    background-color: {C.SURFACE_ALT}; color: {C.TEXT};
    border: 1px solid {C.BORDER}; padding: 6px 8px; border-radius: {R.SM}px;
}}

/* kartlar */
QFrame[card="true"] {{
    background-color: {C.SURFACE}; border: 1px solid {C.BORDER};
    border-radius: {R.LG}px;
}}
QFrame[card="flat"] {{
    background-color: {C.SURFACE_ALT}; border: 1px solid transparent;
    border-radius: {R.MD}px;
}}
QFrame[divider="true"] {{
    background-color: {C.BORDER}; border: none;
    max-height: 1px; min-height: 1px;
}}

/* yazı */
QLabel[muted="true"] {{ color: {C.TEXT_DIM}; }}
QLabel[faint="true"] {{ color: {C.TEXT_FAINT}; }}
QLabel[heading="true"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[display="true"] {{ font-size: 19pt; font-weight: 700; }}
QLabel[accent="true"] {{ color: {C.ACCENT}; }}
QLabel[ok="true"] {{ color: {C.OK}; }}
QLabel[warn="true"] {{ color: {C.WARN}; }}
QLabel[danger="true"] {{ color: {C.DANGER}; }}
"""


def _qss_buttons() -> str:
    return f"""
QPushButton {{
    background-color: {C.SURFACE_ALT}; color: {C.TEXT};
    border: 1px solid {C.BORDER}; border-radius: {R.MD}px;
    padding: 9px 16px; font-weight: 600;
}}
QPushButton:hover {{ background-color: {C.SURFACE_HI}; border-color: {C.BORDER_HI}; }}
QPushButton:pressed {{ background-color: {C.BORDER}; }}
QPushButton:disabled {{ color: {C.TEXT_FAINT}; background-color: {C.SURFACE}; }}

QPushButton[variant="primary"] {{
    background-color: {C.ACCENT}; border: 1px solid {C.ACCENT}; color: #FFFFFF;
}}
QPushButton[variant="primary"]:hover {{ background-color: {C.ACCENT_HOVER}; border-color: {C.ACCENT_HOVER}; }}
QPushButton[variant="primary"]:disabled {{ background-color: {C.SURFACE_ALT}; border-color: {C.BORDER}; color: {C.TEXT_FAINT}; }}

QPushButton[variant="ghost"] {{
    background-color: transparent; border: 1px solid transparent;
    color: {C.TEXT_DIM}; padding: 7px 12px;
}}
QPushButton[variant="ghost"]:hover {{ background-color: {C.SURFACE_ALT}; color: {C.TEXT}; }}

QPushButton[variant="danger"] {{
    background-color: transparent; border: 1px solid {C.DANGER}; color: {C.DANGER};
}}
QPushButton[variant="danger"]:hover {{ background-color: {C.DANGER}; color: #FFFFFF; }}

QPushButton[icon="true"] {{
    padding: 6px; border-radius: {R.SM}px; font-size: 12pt;
}}
"""


def _qss_inputs() -> str:
    return f"""
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {C.SURFACE_ALT}; border: 1px solid {C.BORDER};
    border-radius: {R.MD}px; padding: 9px 12px;
    selection-background-color: {C.ACCENT}; selection-color: #FFFFFF;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {C.ACCENT}; }}
QLineEdit:disabled {{ color: {C.TEXT_FAINT}; }}

QComboBox {{
    background-color: {C.SURFACE_ALT}; border: 1px solid {C.BORDER};
    border-radius: {R.MD}px; padding: 8px 12px;
}}
QComboBox:hover {{ border-color: {C.BORDER_HI}; }}
QComboBox:focus {{ border-color: {C.ACCENT}; }}
QComboBox::drop-down {{
    border: none; width: 26px;
    subcontrol-origin: padding; subcontrol-position: center right;
}}
QComboBox QAbstractItemView {{
    background-color: {C.SURFACE_ALT}; border: 1px solid {C.BORDER_HI};
    border-radius: {R.SM}px; padding: 4px;
    selection-background-color: {C.ACCENT}; selection-color: #FFFFFF;
}}

QCheckBox {{ spacing: {S.SM}px; color: {C.TEXT}; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {C.BORDER_HI}; background-color: {C.SURFACE_ALT};
}}
QCheckBox::indicator:checked {{ background-color: {C.ACCENT}; border-color: {C.ACCENT}; }}
QCheckBox::indicator:hover {{ border-color: {C.ACCENT}; }}

QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background-color: {C.BORDER}; }}
QSlider::sub-page:horizontal {{ background-color: {C.ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; background-color: {C.TEXT}; border: 2px solid {C.BG};
}}
QSlider::handle:horizontal:hover {{ background-color: {C.ACCENT}; }}

QProgressBar {{
    background-color: {C.SURFACE_ALT}; border: none; border-radius: 4px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background-color: {C.ACCENT}; border-radius: 4px; }}
"""


def _qss_lists() -> str:
    return f"""
QSplitter::handle {{ background-color: {C.BORDER}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C.BORDER_HI}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {C.TEXT_FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {C.BORDER_HI}; border-radius: 5px; min-width: 28px; }}

QListWidget, QTableView {{
    background-color: {C.SURFACE}; border: 1px solid {C.BORDER};
    border-radius: {R.MD}px; padding: 4px; gridline-color: {C.BORDER};
    selection-background-color: {C.ACCENT_SOFT}; selection-color: {C.TEXT};
    alternate-background-color: {C.SURFACE_ALT};
}}
QListWidget::item {{ padding: 9px 10px; border-radius: {R.SM}px; margin: 1px 0; }}
QListWidget::item:hover {{ background-color: {C.SURFACE_ALT}; }}
QListWidget::item:selected {{ background-color: {C.ACCENT_SOFT}; color: {C.TEXT}; }}

QHeaderView::section {{
    background-color: {C.SURFACE_ALT}; color: {C.TEXT_DIM};
    border: none; border-bottom: 1px solid {C.BORDER};
    padding: 8px 10px; font-weight: 600;
}}
QTableView::item {{ padding: 6px; }}

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {C.TEXT_DIM};
    padding: 9px 16px; margin-right: 4px;
    border-radius: {R.SM}px; font-weight: 600;
}}
QTabBar::tab:hover {{ background: {C.SURFACE_ALT}; color: {C.TEXT}; }}
QTabBar::tab:selected {{ background: {C.ACCENT_SOFT}; color: {C.ACCENT}; }}

QMenu {{
    background-color: {C.SURFACE_ALT}; border: 1px solid {C.BORDER_HI};
    border-radius: {R.MD}px; padding: 6px;
}}
QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: {R.SM}px; }}
QMenu::item:selected {{ background-color: {C.ACCENT_SOFT}; color: {C.TEXT}; }}
QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: 4px 8px; }}
"""


def qss() -> str:
    """Uygulamanın tamamı için tek stil sayfası."""
    return _qss_core() + _qss_buttons() + _qss_inputs() + _qss_lists()
