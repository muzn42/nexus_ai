"""
NEXUS AI — Ayarlar Penceresi

Beş sekme, her biri tek konu:
  Görünüm   → altyazı stili + CANLI önizleme
  OCR       → model boyutu, işlem birimi
  Çeviri    → motor, dil, API anahtarları
  Kısayollar→ tuş atamaları
  Hakkında  → sürüm, bağlantılar

Tasarım ilkesi: her ayarın yanında ne işe yaradığını anlatan tek cümle.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QColorDialog, QComboBox, QGridLayout,
                               QHBoxLayout, QKeySequenceEdit, QLineEdit,
                               QPushButton, QScrollArea, QTabWidget,
                               QVBoxLayout, QWidget)

from core.theme import C, DEFAULT_PRESET, R, S, SUBTITLE_PRESETS
from ui.qt.components import (Card, Chip, Divider, FramelessWindow, SliderRow,
                              Toast, label, vbox)
from ui.qt.subtitle_view import SubtitleView

SAMPLE_TEXT = ("Dutch: We ride at dawn, Arthur. Tahiti is waiting for us."
               "  —  Bu bir canlı önizlemedir.")


def _parse_geo(value: str) -> tuple:
    """'1100x230+10+20' veya '1100x230' → (genişlik, yükseklik, x, y)."""
    try:
        s = str(value)
        coord = s
        if "+" in s:
            size_part, x, y = s.split("+")
            return (int(size_part.split("x")[0]), int(size_part.split("x")[1]),
                    int(x), int(y))
        w, h = coord.split("x")
        return int(w), int(h), 0, 0
    except Exception:
        return 1100, 230, 0, 0


class SettingsWindow(FramelessWindow):
    """Ayarlar penceresi."""

    def __init__(self, controller, parent=None):
        super().__init__("Ayarlar", "Her şey buradan özelleştirilir",
                         width=900, height=700)
        self.c = controller
        self.toast = Toast(self, "", ms=10)

        tabs = QTabWidget()
        tabs.addTab(self._build_view_tab(), "Görünüm")
        tabs.addTab(self._build_ocr_tab(), "OCR")
        tabs.addTab(self._build_translate_tab(), "Çeviri")
        tabs.addTab(self._build_hotkey_tab(), "Kısayollar")
        tabs.addTab(self._build_about_tab(), "Hakkında")
        self.content_lay.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_reset = QPushButton("Görünümü sıfırla")
        btn_reset.setProperty("variant", "ghost")
        btn_reset.clicked.connect(self._reset_style)
        bottom.addWidget(btn_reset)
        btn_close = QPushButton("Kaydet ve Kapat")
        btn_close.setProperty("variant", "primary")
        btn_close.clicked.connect(self.close)
        bottom.addWidget(btn_close)
        self.content_lay.addLayout(bottom)

        self._update_preview()

    # ------------------------------------------------------------ yardımcılar
    def _set(self, key, value):
        self.c.set_setting(key, value)
        self._apply_live()

    def _apply_live(self):
        self._update_preview()
        if self.c.hud:
            self.c.hud.apply_style(self.c.style())

    def _update_preview(self):
        if not hasattr(self, "preview"):
            return
        self.preview.apply_style(self.c.style())
        self.preview.set_text(SAMPLE_TEXT)
        self.preview.setStyleSheet(self._preview_qss())

    def _preview_qss(self) -> str:
        """
        Önizleme zemini: HUD'un arkasında tipik bir oyun görüntüsü varmış
        gibi davranır, sonra arka plan modunu üstüne uygular.
        """
        mode = self.c.settings.get("opacity_mode", "Transparent")
        bg = self.c.settings.get("bg_color", "#000000")
        pct = int(self.c.settings.get("bg_opacity", 55))

        def blend(hex_color, alpha):
            try:
                h = hex_color.lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            except Exception:
                r = g = b = 0
            return f"rgb({int(r * alpha + 27 * (1 - alpha))}," \
                   f"{int(g * alpha + 36 * (1 - alpha))}," \
                   f"{int(b * alpha + 48 * (1 - alpha))})"

        if mode == "Opaque":
            return f"background: {bg}; border-radius: {R.MD}px;"
        if mode == "Semi":
            a = max(0.0, min(1.0, pct / 100.0))
            return (f"background: {blend(bg, a)};"
                    f" border: 1px solid {C.BORDER}; border-radius: {R.MD}px;")
        # Transparent → tipik oyun zemini (saydamlık hissi)
        return (f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f"stop:0 #1b2430, stop:1 #2a1f14);"
                f" border-radius: {R.MD}px;")

    def _notify(self, msg, tone="ok"):
        self.toast.show_message(msg, tone)
        self.toast._reposition()

    def _combo_row(self, card, title, items, current, on_change, sub=""):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        texts = QWidget()
        tl = vbox(texts, spacing=2)
        tl.addWidget(label(title))
        if sub:
            tl.addWidget(label(sub, "faint", size=9, wrap=True))
        lay.addWidget(texts, 1)
        combo = QComboBox()
        combo.addItems(items)
        idx = combo.findText(str(current))
        combo.setCurrentIndex(max(0, idx))
        combo.setMinimumWidth(160)
        combo.currentTextChanged.connect(on_change)
        lay.addWidget(combo, 0, Qt.AlignTop)
        card.add(row)
        return combo

    def _slider_row(self, card, title, lo, hi, val, suffix, on_change):
        s = SliderRow(title, lo, hi, val, suffix)
        s.changed.connect(on_change)
        card.add(s)
        return s

    def _color_row(self, card, title, initial, on_change):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(label(title), 1)

        btn = QPushButton()
        btn.setFixedSize(74, 30)
        btn.setCursor(Qt.PointingHandCursor)
        holder = {"color": initial}

        def paint():
            btn.setStyleSheet(
                f"background:{holder['color']}; border:1px solid {C.BORDER_HI};"
                f" border-radius:{R.SM}px;")

        def pick():
            col = QColorDialog.getColor(QColor(holder["color"]), self, "Renk seç")
            if col.isValid():
                holder["color"] = col.name()
                paint()
                on_change(holder["color"])

        btn.clicked.connect(pick)
        paint()
        lay.addWidget(btn)
        card.add(row)
        return btn

    # ============================================================ GÖRÜNÜM
    def _build_view_tab(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setSpacing(S.LG)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        left = QWidget()
        ll = vbox(left, spacing=S.MD, margins=(0, 0, S.SM, 0))

        # --- HUD paneli boyutu (en üstte: en çok aranan ayar) ---
        size_card = Card("Altyazı paneli boyutu",
                         "Şeffaf katmanın genişliği/yüksekliği. HUD görünürken "
                         "sağ-alt köşesinden fareyle de boyutlandırabilirsin.")
        geo = _parse_geo(self.c.settings.get("hud_geometry", "1000x200"))
        self.slider_hud_w = self._slider_row(
            size_card, "Genişlik", 400, 2560, max(geo[0], 400), " px",
            lambda v: self._set_hud_size(w=v))
        self.slider_hud_h = self._slider_row(
            size_card, "Yükseklik", 80, 600, max(geo[1], 80), " px",
            lambda v: self._set_hud_size(h=v))
        btn_auto = QPushButton("Ekran genişliğine sığdır")
        btn_auto.setProperty("variant", "ghost")
        btn_auto.clicked.connect(self._fit_hud_to_screen)
        size_card.add(btn_auto)
        ll.addWidget(size_card)

        pre_card = Card("Hazır görünümler", "Tek tıkla dene, sonra ince ayar yap.")
        grid = QGridLayout()
        grid.setSpacing(S.SM)
        for i, name in enumerate(SUBTITLE_PRESETS.keys()):
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._apply_preset(n))
            grid.addWidget(b, i // 2, i % 2)
        pre_card.add_layout(grid)
        ll.addWidget(pre_card)

        type_card = Card("Tipografi")
        self.combo_font = self._combo_row(
            type_card, "Yazı tipi",
            ["Segoe UI", "Arial", "Verdana", "Tahoma", "Georgia", "Consolas"],
            self.c.settings.get("font_family", "Segoe UI"),
            lambda v: self._set("font_family", v))
        self.slider_size = self._slider_row(
            type_card, "Yazı boyutu", 14, 72,
            self.c.settings.get("font_size", 30), " px",
            lambda v: self._set("font_size", v))
        self.slider_stroke = self._slider_row(
            type_card, "Dış çizgi kalınlığı", 0, 8,
            self.c.settings.get("stroke_width", 3), " px",
            lambda v: self._set("stroke_width", v))
        ll.addWidget(type_card)

        color_card = Card("Renkler")
        self.btn_text_color = self._color_row(
            color_card, "Yazı rengi", self.c.settings.get("text_color", "#FFFFFF"),
            lambda v: self._set("text_color", v))
        self.btn_stroke_color = self._color_row(
            color_card, "Çizgi rengi", self.c.settings.get("stroke_color", "#000000"),
            lambda v: self._set("stroke_color", v))
        ll.addWidget(color_card)

        mode_card = Card("Arka plan")
        self.combo_mode = self._combo_row(
            mode_card, "Saydamlık", ["Transparent", "Semi", "Opaque"],
            self.c.settings.get("opacity_mode", "Transparent"),
            lambda v: self._set("opacity_mode", v),
            sub="Transparent = tamamen şeffaf (önerilen) · Semi = yarı saydam "
                "kutu · Opaque = katı kutu")
        self.slider_bg_opacity = self._slider_row(
            mode_card, "Arka plan dolgunluğu (Semi için)", 0, 100,
            self.c.settings.get("bg_opacity", 55), " %",
            lambda v: self._set("bg_opacity", v))
        self.btn_bg_color = self._color_row(
            mode_card, "Kutu rengi", self.c.settings.get("bg_color", "#000000"),
            lambda v: self._set("bg_color", v))
        ll.addWidget(mode_card)
        ll.addStretch(1)

        scroll.setWidget(left)
        lay.addWidget(scroll, 1)

        pv = Card("Canlı önizleme", "Değişiklikler anında uygulanır.")
        self.preview = SubtitleView()
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #1b2430, stop:1 #2a1f14); border-radius: {R.MD}px;")
        self.preview.set_text(SAMPLE_TEXT)
        pv.add(self.preview, 1)
        lay.addWidget(pv, 1)
        return page

    def _apply_preset(self, name):
        self.c.set_setting("subtitle_preset", name, autosave=False)
        from core.theme import preset
        style = preset(name)
        for k in ("font_family", "font_size", "text_color", "stroke_color",
                  "stroke_width", "bg_color", "opacity_mode"):
            self.c.settings[k] = style[k]
        self.c.save()
        # arayüz kontrollerini güncelle
        idx = self.combo_font.findText(style.get("font_family", "Segoe UI"))
        self.combo_font.blockSignals(True)
        self.combo_font.setCurrentIndex(max(0, idx))
        self.combo_font.blockSignals(False)
        self.slider_size.setValue(style.get("font_size", 30))
        self.slider_stroke.setValue(style.get("stroke_width", 3))
        idx = self.combo_mode.findText(style.get("opacity_mode", "Transparent"))
        self.combo_mode.blockSignals(True)
        self.combo_mode.setCurrentIndex(max(0, idx))
        self.combo_mode.blockSignals(False)
        self._apply_live()
        self._notify(f"'{name}' görünümü uygulandı.", "ok")

    def _reset_style(self):
        from core.theme import preset
        style = preset(DEFAULT_PRESET)
        self.c.settings["subtitle_preset"] = DEFAULT_PRESET
        for k, v in style.items():
            self.c.settings[k] = v
        self.c.save()
        self._apply_preset(DEFAULT_PRESET)

    def _fit_hud_to_screen(self):
        """HUD'u ekran genişliğinin %80'ine, yüksekliğini 230 px'e ayarla."""
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        sw = screen.geometry().width() if screen else 1920
        w = int(sw * 0.8)
        self.c.set_setting("hud_geometry", f"{w}x230")
        self.slider_hud_w.blockSignals(True)
        self.slider_hud_w.setValue(w)
        self.slider_hud_w.blockSignals(False)
        self.slider_hud_h.blockSignals(True)
        self.slider_hud_h.setValue(230)
        self.slider_hud_h.blockSignals(False)
        self._apply_hud_geometry()
        self._notify(f"Panel boyutu {w}×230 yapıldı.", "ok")

    def _set_hud_size(self, w=None, h=None):
        """Genişlik/yükseklik değişince HUD'u anında yeniden boyutlandır."""
        cur = _parse_geo(self.c.settings.get("hud_geometry", "1100x230"))
        nw = int(w) if w is not None else cur[0]
        nh = int(h) if h is not None else cur[1]
        self.c.set_setting("hud_geometry", f"{nw}x{nh}")
        self._apply_hud_geometry()

    def _apply_hud_geometry(self):
        if not self.c.hud:
            return
        w, h, x, y = _parse_geo(self.c.settings.get("hud_geometry", "1100x230"))
        g = self.c.hud.geometry()
        # Konumu koru (x,y = 0 ise mevcut konum)
        nx = g.x() if x == 0 else x
        ny = g.y() if y == 0 else y
        self.c.hud.setGeometry(nx, ny, w, h)
        self.c.hud.view.update()

    # ============================================================ OCR
    def _build_ocr_tab(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setSpacing(S.LG)
        col = vbox(spacing=S.MD)

        card = Card("Metin tanıma (OCR)",
                    "Ekrandaki yazıyı okuyan motor. Hız ve doğruluk dengesi.")
        self.combo_ocr_ver = self._combo_row(
            card, "OCR sürümü", ["PP-OCRv6", "PP-OCRv5", "PP-OCRv4"],
            self.c.settings.get("paddle_version", "PP-OCRv5"),
            self._on_ocr_version,
            sub="PP-OCRv6 = en yeni ve en hızlı")

        self.combo_ocr_size = self._combo_row(
            card, "Model boyutu", ["tiny", "small", "medium"],
            self.c.settings.get("ocr_model_size", "small"),
            lambda v: self._on_ocr_change("ocr_model_size", v),
            sub="tiny = en hızlı · small = dengeli (önerilen) · "
                "medium = en doğru ama yavaş")

        self.combo_ocr_device = self._combo_row(
            card, "İşlem birimi", ["cpu", "gpu"],
            self.c.settings.get("ocr_device", "cpu"),
            lambda v: self._on_ocr_change("ocr_device", v),
            sub="gpu = NVIDIA kartı kullan (paddlepaddle-gpu kurulu olmalı)")
        col.addWidget(card)

        speed = Card("Hız / doğruluk ipuçları",
                     "Aynı sonucu daha hızlı almak için:")
        tips = [
            "• 'small' model oyun altyazıları için fazlasıyla yeterli.",
            "• GPU varsa 'gpu' seçin: CPU'ya göre ~3 kat hızlı.",
            "• Altyazı alanını dar seçin — OCR süresi alanla büyür.",
            "• 'Akıllı Filtre' açıkken değişmeyen kareler hiç okunmaz.",
        ]
        for t in tips:
            speed.add(label(t, "muted", size=9, wrap=True))
        col.addWidget(speed)

        self.ocr_status = Card("Motor durumu")
        self.ocr_status.add(label("Henüz başlatılmadı.", "muted", size=9))
        btn_test = QPushButton("Motoru test et")
        btn_test.clicked.connect(self._test_ocr)
        self.ocr_status.add(btn_test)
        col.addWidget(self.ocr_status)
        col.addStretch(1)

        lay.addLayout(col, 1)

        warn = Card("Bilinen sorun: PaddlePaddle sürümü",
                    "OCR beklenenden yavaşsa sebebi bu olabilir.")
        warn.add(label(
            "paddlepaddle 3.3.0 / 3.3.1 sürümlerinde oneDNN (MKLDNN) hatası var; "
            "motor sessizce yavaş CPU moduna düşer.\n\n"
            "Kalıcı çözüm:\n    pip install paddlepaddle==3.2.2\n\n"
            "GPU için:\n    pip install paddlepaddle-gpu==3.2.2 "
            "--index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/\n"
            "    pip install nvidia-cudnn-cu12 nvidia-cublas-cu12",
            size=9, wrap=True))
        lay.addWidget(warn, 1)
        return page

    def _on_ocr_version(self, v):
        self._on_ocr_change("paddle_version", v)

    def _on_ocr_change(self, key, value):
        self.c.set_setting(key, value)
        self.c.rebuild_ocr()
        self._notify("OCR ayarı kaydedildi (sonraki okumada geçerli).", "ok")

    def _test_ocr(self):
        import threading
        import numpy as np
        self.ocr_status.body_lay.itemAt(0).widget().setText("Test ediliyor…")

        def run():
            try:
                img = np.zeros((120, 900, 3), dtype=np.uint8)
                img[:, :] = 30
                # basit metin çizmek için cv2 (zaten bağımlılık)
                import cv2
                cv2.putText(img, "Dutch is waiting at camp.", (20, 75),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                self.c.ocr_engine.read_text(img)   # ısınma
                import time
                t0 = time.time()
                text = self.c.ocr_engine.read_text(img)
                ms = (time.time() - t0) * 1000
                msg = (f"{self.c.ocr_engine.status()}\n"
                       f"Ölçüm: {ms:.0f} ms · okunan: '{text}'")
            except Exception as e:
                msg = f"Test hatası: {e}"
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._show_ocr_result(msg))

        threading.Thread(target=run, daemon=True).start()

    def _show_ocr_result(self, msg):
        w = self.ocr_status.body_lay.itemAt(0).widget()
        if hasattr(w, "setText"):
            w.setText(msg)

    # ============================================================ ÇEVİRİ
    def _build_translate_tab(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setSpacing(S.LG)
        col = vbox(spacing=S.MD)

        eng = Card("Motor ve dil",
                   "Sözlükte bulunmayan cümleler bu motorla çevrilir.")
        self.combo_engine2 = self._combo_row(
            eng, "Çeviri motoru",
            ["Akıllı Zincir (GPT-OSS → Gemini)", "Groq AI (Qwen 27B)",
             "Gemini AI", "Google Translate (Ücretsiz)",
             "Argos Translate (Çevrimdışı)"],
            self.c.settings.get("fallback_engine", "Akıllı Zincir (GPT-OSS → Gemini)"),
            self._on_engine2)
        self.combo_target = self._combo_row(
            eng, "Hedef dil",
            ["Türkçe", "İngilizce", "Almanca", "Fransızca", "İspanyolca",
             "Japonca", "Rusça"],
            self.c.settings.get("target_language", "Türkçe"),
            self._on_lang2)
        col.addWidget(eng)

        learn = Card("Öğrenme ve filtreleme")
        from ui.qt.components import ToggleRow
        self.toggle_learn = ToggleRow(
            "Otomatik öğrenme",
            "Yapay zekadan gelen çevirileri yerel havuza kaydeder; "
            "aynı cümle tekrar gelince anında ve bedava döner.",
            self.c.settings.get("auto_learn_enabled", True))
        self.toggle_learn.changed.connect(self._on_auto_learn)
        learn.add(self.toggle_learn)

        self.toggle_filter = ToggleRow(
            "Akıllı filtre",
            "Değişmeyen kareleri OCR'a hiç göndermez (varsayılan zaten açık).",
            self.c.settings.get("smart_filter_enabled", True))
        self.toggle_filter.changed.connect(
            lambda v: self.c.set_setting("smart_filter_enabled", v))
        learn.add(self.toggle_filter)
        col.addWidget(learn)
        col.addStretch(1)
        lay.addLayout(col, 1)

        keys = Card("API anahtarları",
                    "Yalnızca ilgili motoru kullanacaksanız gerekir. "
                    "Anahtarlar yalnızca bu bilgisayarda saklanır.")
        self.entry_groq = self._key_row(
            keys, "Groq", self.c.settings.get("groq_api_key", ""),
            "gsk_…", self._save_groq)
        self.entry_gemini = self._key_row(
            keys, "Gemini", self.c.settings.get("gemini_api_key", ""),
            "AIza…", self._save_gemini)
        self.entry_evren = self._key_row(
            keys, "EVREN", self.c.settings.get("evren_api_key", ""),
            "evren_llm_…", self._save_evren)

        keys.add(Divider())
        keys.add(label("Ücretsiz seçenek: Google Translate anahtar istemez.",
                       "faint", size=9, wrap=True))
        lay.addWidget(keys, 1)
        return page

    def _key_row(self, card, name, current, placeholder, on_save):
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.XS)
        lay.addWidget(label(f"{name} API anahtarı", size=9))
        h = QHBoxLayout()
        h.setSpacing(S.SM)
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.Password)
        entry.setPlaceholderText(placeholder)
        entry.setText(current or "")
        h.addWidget(entry, 1)
        btn = QPushButton("Kaydet")
        btn.clicked.connect(lambda: on_save(entry.text().strip()))
        h.addWidget(btn)
        lay.addLayout(h)
        card.add(row)
        return entry

    def _save_groq(self, key):
        self.c.settings["groq_api_key"] = key
        self.c.save()
        self.c.translator.set_keys(groq_api_key=key)
        self._notify("Groq anahtarı kaydedildi.", "ok")

    def _save_gemini(self, key):
        self.c.settings["gemini_api_key"] = key
        self.c.save()
        self.c.translator.set_keys(gemini_api_key=key)
        self._notify("Gemini anahtarı kaydedildi.", "ok")

    def _save_evren(self, key):
        self.c.settings["evren_api_key"] = key
        self.c.save()
        self.c.translator.set_keys(evren_api_key=key)
        self._notify("EVREN anahtarı kaydedildi.", "ok")

    def _on_engine2(self, text):
        self.c.set_setting("fallback_engine", text)
        self.c.translator.fallback_engine = text

    def _on_lang2(self, text):
        self.c.set_setting("target_language", text)
        self.c.translator.target_language = text

    def _on_auto_learn(self, value):
        self.c.set_setting("auto_learn_enabled", value)
        self.c.translator.auto_learn_enabled = value

    # ============================================================ KISAYOLLAR
    HOTKEYS = [
        ("hotkey_start", "Başlat / Durdur", "f9"),
        ("hotkey_reselect", "Alan seç", "f10"),
        ("hotkey_settings", "Ayarlar", "f11"),
        ("hotkey_lock", "HUD kilidi (tıklama geçirgenliği)", "f8"),
        ("hotkey_exit", "Çıkış", "f12"),
    ]

    def _build_hotkey_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(S.MD)

        card = Card("Klavye kısayolları",
                    "Oyun sırasında fare kullanmadan yönetmek için.")
        for key, title, default in self.HOTKEYS:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            texts = QWidget()
            tl = vbox(texts, spacing=0)
            tl.addWidget(label(title))
            h.addWidget(texts, 1)

            edit = QKeySequenceEdit()
            edit.setMaximumWidth(180)
            current = self.c.settings.get(key, default)
            edit.setKeySequence(QKeySequence(str(current).upper()))
            edit.keySequenceChanged.connect(
                lambda seq, k=key: self._on_hotkey(k, seq))
            h.addWidget(edit)
            card.add(row)
        lay.addWidget(card)
        lay.addStretch(1)

        note = Card("Notlar")
        note.add(label(
            "• Kısayollar oyun penceresi öndeyken de çalışır.\n"
            "• Bazı oyunlar F tuşlarını kendine alabilir; çakışma olursa "
            "başka tuş seçin.\n"
            "• Değişiklikler uygulamayı yeniden başlatınca etkin olur.",
            "muted", size=9, wrap=True))
        lay.addWidget(note)
        return page

    def _on_hotkey(self, key, seq):
        text = seq.toString().lower() or ""
        if not text:
            return
        self.c.set_setting(key, text)
        self._notify(f"Kısayol kaydedildi: {text.upper()}", "ok")

    # ============================================================ HAKKINDA
    def _build_about_tab(self):
        from core.config_manager import APP_NAME, APP_VERSION, BASE_DIR
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(S.MD)

        head = Card()
        head.add(label(APP_NAME, "display"))
        head.add(label(f"Sürüm {APP_VERSION} · Hızlı Oyun Çeviri Asistanı",
                       "muted", size=9))
        head.add(label(
            "Ekrandaki oyun altyazısını okur, sözlüğünden veya yapay zekadan "
            "çevirir ve oyunun üstünde şeffaf bir katman olarak gösterir.",
            size=10, wrap=True))
        lay.addWidget(head)

        flow = Card("Nasıl çalışır?",
                    "Dört adım, hepsi yerel olarak kontrolünüzde.")
        for i, t in enumerate([
            "1. Ekranın seçtiğin bölgesi yakalanır (sadece o bölge).",
            "2. PaddleOCR metni okur (GPU varsa ~30-70 ms).",
            "3. Sözlükte varsa anında döner; yoksa yapay zekaya sorulur.",
            "4. Çeviri, tıklamaları engellemeyen şeffaf katmanda gösterilir.",
        ]):
            flow.add(label(t, "muted", size=9, wrap=True))
        lay.addWidget(flow)

        links = Card("Bağlantılar")
        for text, url in [
            ("Chiaki-ng (PS5 uzaktan oynatma) — indir",
             "https://github.com/streetpea/chiaki-ng/releases"),
            ("PaddleOCR", "https://github.com/PaddlePaddle/PaddleOCR"),
        ]:
            lb = label(f'<a href="{url}" style="color:{C.ACCENT}">{text}</a>',
                       size=9)
            lb.setOpenExternalLinks(True)
            lb.setTextFormat(Qt.RichText)
            links.add(lb)
        links.add(Divider())
        links.add(label(f"Kurulum klasörü: {BASE_DIR}", "faint", size=8, wrap=True))
        lay.addWidget(links)
        lay.addStretch(1)
        return page
