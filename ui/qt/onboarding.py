"""
NEXUS AI — İlk Kullanım Sihirbazı (Onboarding)

Amaç: hiçbir şey bilmeyen birinin 60 saniyede çalışır hale gelmesi.
Üç adım, her adımda tek karar:

  1) Hoş geldin
  2) Dil + çeviri motoru
  3) Altyazı alanı
  4) Başlat

`help_mode=True` ile aynı pencere bir kullanım kılavuzu olarak açılır.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from core.theme import C, S
from ui.qt.components import Card, Chip, Divider, FramelessWindow, Toast, label

LANGUAGES = ["Türkçe", "İngilizce", "Almanca", "Fransızca", "İspanyolca",
             "Japonca", "Rusça"]

ENGINES = [
    ("Google Translate (Ücretsiz)",
     "Anahtar gerekmez, hemen çalışır. Başlamak için en kolayı."),
    ("Akıllı Zincir (GPT-OSS → Gemini)",
     "En hızlı ve en doğal çeviri. Groq anahtarı gerekir."),
    ("Gemini AI", "Google Gemini. Kaliteli, anahtar gerekir."),
    ("Argos Translate (Çevrimdışı)",
     "İnternetsiz çalışır, modeli bir kez indirmek gerekir."),
]


class OnboardingWindow(FramelessWindow):
    """Adım adım ilk kurulum / yardım penceresi."""

    def __init__(self, controller, parent=None, help_mode=False):
        super().__init__(
            "Kullanım Kılavuzu" if help_mode else "NEXUS AI'a Hoş Geldiniz",
            "Her şeyi buradan öğrenebilirsiniz" if help_mode else "Adım adım hazır",
            width=760, height=660, show_max=False)
        self.c = controller
        self.help_mode = help_mode
        self.step = 0
        self.toast = Toast(self, "", ms=10)

        self.pages = [self._page_welcome(), self._page_engine(),
                      self._page_area(), self._page_ready()]

        self.stack = QWidget()
        self.stack_lay = QVBoxLayout(self.stack)
        self.stack_lay.setContentsMargins(0, 0, 0, 0)
        self.content_lay.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        nav.setSpacing(S.SM)
        self.dots = QHBoxLayout()
        self.dots.setSpacing(6)
        nav.addLayout(self.dots)
        nav.addStretch(1)

        self.btn_back = QPushButton("Geri")
        self.btn_back.setProperty("variant", "ghost")
        self.btn_back.clicked.connect(self._prev)
        nav.addWidget(self.btn_back)

        self.btn_next = QPushButton("İleri")
        self.btn_next.setProperty("variant", "primary")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_next)
        self.content_lay.addLayout(nav)

        self._show_step(0)

    # ------------------------------------------------------------ akış
    def _show_step(self, index):
        self.step = max(0, min(index, len(self.pages) - 1))
        while self.stack_lay.count():
            item = self.stack_lay.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.stack_lay.addWidget(self.pages[self.step])

        # noktalar
        while self.dots.count():
            item = self.dots.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i in range(len(self.pages)):
            dot = label("●" if i == self.step else "○", size=10)
            dot.setStyleSheet(f"color:{C.ACCENT if i == self.step else C.TEXT_FAINT};")
            self.dots.addWidget(dot)

        self.btn_back.setEnabled(self.step > 0)
        last = self.step == len(self.pages) - 1
        self.btn_next.setText("Bitir" if last else "İleri")
        if self.help_mode:
            self.btn_back.setVisible(False)
            self.btn_next.setText("Kapat" if last else "İleri")

    def _next(self):
        if self.step >= len(self.pages) - 1:
            self.c.set_setting("onboarding_done", True)
            self.close()
            return
        self._show_step(self.step + 1)

    def _prev(self):
        self._show_step(self.step - 1)

    # ------------------------------------------------------------ sayfalar
    def _page_welcome(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(S.MD)

        card = Card()
        card.add(label("Oyunu kendi dilinde oyna", "display"))
        card.add(label(
            "Nexus AI, ekrandaki altyazıyı okur ve Türkçeye çevirip oyunun "
            "üstünde gösterir. Hiçbir oyun dosyasına dokunmaz.",
            "muted", size=10, wrap=True))
        lay.addWidget(card)

        how = Card("Nasıl çalışır?", "Kısaca:")
        for num, title, detail in [
            ("1", "Altyazı alanını seçersin",
             "Ekranda yazının çıktığı dikdörtgeni bir kez işaretlersin."),
            ("2", "Program yazıyı okur",
             "Sadece o bölgeyi okur; oyunun geri kalanına dokunmaz."),
            ("3", "Sözlük ya da yapay zeka çevirir",
             "Oyunun hazır sözlüğü varsa anında, yoksa yapay zeka devreye girer."),
            ("4", "Çeviri oyunun üstünde görünür",
             "Şeffaf katman tıklamaları engellemez; oyun bozulmaz."),
        ]:
            row = QHBoxLayout()
            row.setSpacing(S.SM)
            badge = label(num, size=10, bold=True)
            badge.setStyleSheet(
                f"color:{C.ACCENT}; background:{C.ACCENT_SOFT};"
                f" border-radius:12px; padding:3px 10px;")
            row.addWidget(badge, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(title, size=10, bold=True))
            col.addWidget(label(detail, "muted", size=9, wrap=True))
            row.addLayout(col, 1)
            how.add_layout(row)
        lay.addWidget(how)
        lay.addStretch(1)
        return w

    def _page_engine(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(S.MD)

        card = Card("Hangi dile çevirelim?")
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(LANGUAGES)
        idx = self.combo_lang.findText(self.c.settings.get("target_language", "Türkçe"))
        self.combo_lang.setCurrentIndex(max(0, idx))
        self.combo_lang.currentTextChanged.connect(
            lambda v: self.c.set_setting("target_language", v))
        card.add(self.combo_lang)
        lay.addWidget(card)

        eng = Card("Çeviri motoru",
                   "Emin değilsen ilk seçenekle başla — sonra değiştirebilirsin.")
        for name, desc in ENGINES:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(name, size=10, bold=True))
            col.addWidget(label(desc, "muted", size=9, wrap=True))
            h.addLayout(col, 1)
            b = QPushButton("Seç")
            b.setFixedWidth(70)
            b.clicked.connect(lambda _=False, n=name: self._pick_engine(n))
            h.addWidget(b, 0, Qt.AlignTop)
            eng.add(row)
        lay.addWidget(eng)

        self.engine_chip = Chip(
            f"Aktif: {self.c.settings.get('fallback_engine', ENGINES[0][0])}", "info")
        lay.addWidget(self.engine_chip, 0, Qt.AlignLeft)
        lay.addStretch(1)
        return w

    def _pick_engine(self, name):
        self.c.set_setting("fallback_engine", name)
        self.c.translator.fallback_engine = name
        self.engine_chip.setText(f"Aktif: {name}")
        self.engine_chip.adjustSize()
        self.toast.show_message(f"{name} seçildi.", "ok")
        self.toast._reposition()

    def _page_area(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(S.MD)

        card = Card("Altyazı alanını seç",
                    "Ekranda yazının göründüğü yeri bir kez işaretle. "
                    "Oyun değişirse yeniden seçebilirsin.")
        self.area_status = label("Henüz alan seçilmedi", "muted", size=10)
        card.add(self.area_status)

        self.btn_pick_area = QPushButton("Ekranda Alan Seç")
        self.btn_pick_area.setProperty("variant", "primary")
        self.btn_pick_area.setCursor(Qt.PointingHandCursor)
        self.btn_pick_area.clicked.connect(self._pick_area)
        card.add(self.btn_pick_area)

        card.add(Divider())
        card.add(label(
            "İpucu: Alanı gereğinden büyük seçme. Ne kadar küçük olursa "
            "OCR o kadar hızlı olur. Altyazının iki satırı sığsın yeter.",
            "faint", size=9, wrap=True))
        lay.addWidget(card)
        lay.addStretch(1)
        return w

    def _pick_area(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from ui.qt.roi_selector import RoiSelector

        self.hide()
        QApplication.processEvents()

        def run():
            sel = RoiSelector()

            def on_selected(roi):
                self.c.set_roi(roi)
                self.area_status.setText(f"Seçildi: {roi[2]} × {roi[3]} piksel")
                self.show()
                self.raise_()

            sel.selected.connect(on_selected)
            sel.showFullScreen()
            sel.raise_()
            sel.setFocus()

        QTimer.singleShot(250, run)

    def _page_ready(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(S.MD)

        card = Card()
        card.add(label("Hazırsın", "display"))
        card.add(label(
            "Ana ekranda 'Başlat'a bas.\n\n"
            "Oyun sırasında:  F9 başlat/durdur  ·  F10 alan seç  ·  "
            "F11 ayarlar  ·  F8 kilit  ·  F12 çıkış",
            size=10, wrap=True))
        lay.addWidget(card)

        tips = Card("İlk seferde işine yarayacaklar")
        for t in [
            "• Sözlük Kütüphanesi'nden oyununun hazır çevirisini seçebilirsin "
            "(varsa çeviri anında ve bedava gelir).",
            "• PS5'te oynuyorsan 'PS5 / Chiaki-ng' ekranından bağlantıyı "
            "adım adım kurabilirsin.",
            "• Ayarlar → Görünüm'de yazı boyutu, renk ve görünüm ön ayarlarını "
            "canlı önizlemeyle deneyebilirsin.",
            "• Kilit (F8) açıkken fare tıklamaları oyuna geçer; altyazı "
            "katmanı hiçbir şeyi engellemez.",
        ]:
            tips.add(label(t, "muted", size=9, wrap=True))
        lay.addWidget(tips)
        lay.addStretch(1)
        return w
