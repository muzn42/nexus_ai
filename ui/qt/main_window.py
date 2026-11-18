"""
NEXUS AI — Ana Ekran

İlk kez açan birinin hiçbir şey bilmeden ilerleyebileceği numaralı akış:
  1) Görüntü kaynağı  2) Çeviri alanı  3) Sözlük  4) Çeviri motoru
En üstte tek bir "Başlat" düğmesi ve canlı durum bilgisi.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core import chiaki
from core.capture import list_cameras
from core.theme import C, DEFAULT_PRESET, R, S
from ui.qt.components import (Card, Chip, Divider, FramelessWindow, Toast,
                              label, vbox)
from ui.qt.roi_selector import RoiSelector

ENGINES = [
    "Akıllı Zincir (GPT-OSS → Gemini)",
    "Groq AI (Qwen 27B)",
    "Gemini AI",
    "Google Translate (Ücretsiz)",
    "Argos Translate (Çevrimdışı)",
]

LANGUAGES = ["Türkçe", "İngilizce", "Almanca", "Fransızca",
             "İspanyolca", "Japonca", "Rusça"]


class MainWindow(FramelessWindow):
    """Uygulamanın ana penceresi."""

    def __init__(self, controller):
        super().__init__("NEXUS AI", "Hızlı Oyun Çeviri Asistanı",
                         width=760, height=900)
        self.c = controller
        self._cameras = []
        self._roi_selector = None

        self.toast = Toast(self, "", ms=10)

        # --- kaydırılabilir içerik ---
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.col = vbox(inner, spacing=S.MD, margins=(0, 0, S.SM, 0))
        scroll.setWidget(inner)
        self.content_lay.addWidget(scroll, 1)

        self._build_hero()
        self._build_source_card()
        self._build_area_card()
        self._build_dict_card()
        self._build_engine_card()
        self._build_footer()

        # --- sinyaller ---
        self.c.state_changed.connect(self._on_state)
        self.c.text_ready.connect(self._on_text)
        self.c.partial_ready.connect(self._on_partial)
        self.c.stats_changed.connect(self._on_stats)
        self.c.roi_changed.connect(self._on_roi)
        self.c.toast.connect(self._show_toast)
        self.c.dict_changed.connect(lambda *_: self._refresh_dict_card())

        self._refresh_all()
        # Kamera portlarını arka planda tara (açılışı bloklamaz)
        QTimer.singleShot(400, self._scan_cameras)

    # ------------------------------------------------------------ hero
    def _build_hero(self):
        card = Card()
        hero = QHBoxLayout()
        hero.setSpacing(S.LG)

        left = QWidget()
        ll = vbox(left, spacing=4)
        self.status_chip = Chip("Hazır", "neutral")
        ll.addWidget(self.status_chip, 0, Qt.AlignLeft)
        self.hero_title = label("Başlamaya hazır", size=15, bold=True)
        ll.addWidget(self.hero_title)
        self.hero_sub = label("Adımları tamamlayıp Başlat'a basın.", "muted",
                              size=9, wrap=True)
        ll.addWidget(self.hero_sub)
        hero.addWidget(left, 1)

        btns = QVBoxLayout()
        btns.setSpacing(S.SM)
        self.btn_start = QPushButton("▶   Başlat")
        self.btn_start.setProperty("variant", "primary")
        self.btn_start.setMinimumHeight(46)
        self.btn_start.setMinimumWidth(180)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._toggle)
        btns.addWidget(self.btn_start)

        self.btn_area = QPushButton("▣   Alan Seç")
        self.btn_area.setMinimumHeight(38)
        self.btn_area.setCursor(Qt.PointingHandCursor)
        self.btn_area.clicked.connect(self._select_area)
        btns.addWidget(self.btn_area)

        # HUD'u önizle: kullanıcı katmanın nerede olduğunu görsün, taşıyabilsin
        self.btn_hud = QPushButton("👁   HUD'u Göster")
        self.btn_hud.setMinimumHeight(34)
        self.btn_hud.setProperty("variant", "ghost")
        self.btn_hud.setCursor(Qt.PointingHandCursor)
        self.btn_hud.setToolTip(
            "Altyazı katmanını göster/gizle. Göründüğünde fareyle taşıyabilirsin.")
        self.btn_hud.clicked.connect(self._toggle_hud_visible)
        btns.addWidget(self.btn_hud)
        hero.addLayout(btns)

        card.add_layout(hero)

        # ince istatistik satırı
        stats = QHBoxLayout()
        stats.setSpacing(S.LG)
        self.stat_ocr = self._stat("OCR", "—")
        self.stat_tr = self._stat("Çeviri", "—")
        self.stat_dict = self._stat("Sözlük", "—")
        for w in (self.stat_ocr, self.stat_tr, self.stat_dict):
            stats.addWidget(w)
        stats.addStretch(1)
        card.add_layout(stats)

        # son altyazı (teşhis: OCR ne okuyor / ne çevirdi)
        card.add(Divider())
        last_row = QHBoxLayout()
        last_row.setSpacing(S.SM)
        last_row.addWidget(label("Son altyazı", "faint", size=8))
        self.last_text_label = label("—", "muted", size=9, wrap=True)
        last_row.addWidget(self.last_text_label, 1)
        card.add_layout(last_row)

        self.col.addWidget(card)

    def _stat(self, title, value):
        w = QWidget()
        lay = vbox(w, spacing=0)
        v = label(value, size=12, bold=True)
        lay.addWidget(v)
        lay.addWidget(label(title, "faint", size=8))
        w._value = v
        return w

    # ------------------------------------------------------------ 1) kaynak
    def _build_source_card(self):
        card = Card("1 · Görüntü kaynağı",
                    "Oyunu nereden okuyacağız? PC ekranı ya da capture card.")
        row = QHBoxLayout()
        row.setSpacing(S.SM)
        from PySide6.QtWidgets import QComboBox
        self.combo_source = QComboBox()
        self.combo_source.addItem("PC Ekranı")
        self.combo_source.setMinimumWidth(260)
        self.combo_source.currentIndexChanged.connect(self._on_source_change)
        row.addWidget(self.combo_source, 1)

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setProperty("icon", True)
        self.btn_refresh.setToolTip("Kaynakları yeniden tara")
        self.btn_refresh.setFixedSize(38, 38)
        self.btn_refresh.clicked.connect(self._scan_cameras)
        row.addWidget(self.btn_refresh)

        # Açık pencerelerden birini seç (oyun / video oynatıcı / Chiaki)
        self.btn_pick_window = QPushButton("Pencere Seç…")
        self.btn_pick_window.setCursor(Qt.PointingHandCursor)
        self.btn_pick_window.setToolTip(
            "Açık pencerelerden birini seç. Seçilen pencere taşınsa bile "
            "takip edilir; arayüzünüz üstüne gelse bile okunmaz.")
        self.btn_pick_window.clicked.connect(self._pick_window)
        row.addWidget(self.btn_pick_window)
        card.add_layout(row)

        # Seçili pencere bilgisi
        self.window_label = label("", "faint", size=9, wrap=True)
        card.add(self.window_label)
        self.col.addWidget(card)

    # ------------------------------------------------------------ 2) alan
    def _build_area_card(self):
        card = Card("2 · Çeviri alanı",
                    "Altyazının ekranda göründüğü dikdörtgen bölge.")
        row = QHBoxLayout()
        row.setSpacing(S.SM)

        self.roi_label = label("Henüz alan seçilmedi", "muted", size=10)
        row.addWidget(self.roi_label, 1)

        self.btn_select_roi = QPushButton("Alan Seç")
        self.btn_select_roi.setCursor(Qt.PointingHandCursor)
        self.btn_select_roi.clicked.connect(self._select_area)
        row.addWidget(self.btn_select_roi)
        card.add_layout(row)

        # kayıtlı profiller
        prow = QHBoxLayout()
        prow.setSpacing(S.SM)
        from PySide6.QtWidgets import QComboBox
        self.combo_profile = QComboBox()
        self.combo_profile.setMinimumWidth(240)
        self.combo_profile.currentIndexChanged.connect(self._on_profile_change)
        prow.addWidget(self.combo_profile, 1)
        self.btn_del_profile = QPushButton("Sil")
        self.btn_del_profile.setProperty("variant", "ghost")
        self.btn_del_profile.clicked.connect(self._delete_profile)
        prow.addWidget(self.btn_del_profile)
        card.add_layout(prow)
        self.col.addWidget(card)

    # ------------------------------------------------------------ 3) sözlük
    def _build_dict_card(self):
        card = Card("3 · Sözlük (opsiyonel)",
                    "Oyunun hazır çeviri veritabanı varsa buradan seçin — "
                    "çeviriler anında ve bedava gelir.")
        row = QHBoxLayout()
        row.setSpacing(S.SM)
        self.dict_label = label("Sözlük kullanılmıyor", "muted", size=10)
        row.addWidget(self.dict_label, 1)

        btn = QPushButton("Sözlük Kütüphanesi")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._open_dictionary)
        row.addWidget(btn)
        card.add_layout(row)
        self.col.addWidget(card)

    # ------------------------------------------------------------ 4) motor
    def _build_engine_card(self):
        card = Card("4 · Çeviri motoru",
                    "Sözlükte olmayan cümleler için kullanılacak yapay zeka.")
        from PySide6.QtWidgets import QComboBox
        row = QHBoxLayout()
        row.setSpacing(S.SM)
        self.combo_engine = QComboBox()
        self.combo_engine.addItems(ENGINES)
        self.combo_engine.setMinimumWidth(260)
        self.combo_engine.currentTextChanged.connect(self._on_engine_change)
        row.addWidget(self.combo_engine, 1)

        self.combo_lang = QComboBox()
        self.combo_lang.addItems(LANGUAGES)
        self.combo_lang.setMinimumWidth(130)
        self.combo_lang.currentTextChanged.connect(self._on_lang_change)
        row.addWidget(self.combo_lang)
        card.add_layout(row)

        self.engine_hint = label("", "faint", size=9, wrap=True)
        card.add(self.engine_hint)
        self.col.addWidget(card)

    # ------------------------------------------------------------ alt
    def _build_footer(self):
        row = QHBoxLayout()
        row.setSpacing(S.SM)

        btn_settings = QPushButton("⚙  Ayarlar")
        btn_settings.clicked.connect(self._open_settings)
        row.addWidget(btn_settings)

        btn_chiaki = QPushButton("🎮  PS5 / Chiaki-ng")
        btn_chiaki.clicked.connect(self._open_chiaki)
        row.addWidget(btn_chiaki)

        btn_help = QPushButton("?  Yardım")
        btn_help.setProperty("variant", "ghost")
        btn_help.clicked.connect(self._open_help)
        row.addWidget(btn_help)

        row.addStretch(1)
        self.footer_note = label("F9 başlat/durdur · F10 alan · F11 ayarlar · F12 çıkış",
                                "faint", size=8)
        row.addWidget(self.footer_note)
        self.content_lay.addLayout(row)

    # ------------------------------------------------------------ yenileme
    def _refresh_all(self):
        s = self.c.settings
        # kaynak
        idx = self.combo_source.findText(self._source_text_from_settings())
        if idx >= 0:
            self.combo_source.blockSignals(True)
            self.combo_source.setCurrentIndex(idx)
            self.combo_source.blockSignals(False)
        # motor + dil
        self.combo_engine.blockSignals(True)
        e = s.get("fallback_engine", ENGINES[0])
        i = self.combo_engine.findText(e)
        self.combo_engine.setCurrentIndex(max(0, i))
        self.combo_engine.blockSignals(False)
        self.combo_lang.blockSignals(True)
        l = self.combo_lang.findText(s.get("target_language", "Türkçe"))
        self.combo_lang.setCurrentIndex(max(0, l))
        self.combo_lang.blockSignals(False)

        self._update_engine_hint()
        self.refresh_profiles()
        self._refresh_dict_card()
        self._on_roi(self.c.roi)
        if s.get("source_type") == "window" and s.get("window_title"):
            self.window_label.setText(
                f"Kaynak pencere: {s.get('window_title')}\n"
                "Alan seçimi bu pencerenin İÇİNE göre yapılır; pencere "
                "taşınsa bile takip edilir.")

    def _refresh_dict_card(self):
        entry = self.c.active_dictionary()
        if entry:
            info = self.c.library.stats(entry.path)
            count = f"{info['count']:,} satır" if info["ok"] else "okunamadı"
            self.dict_label.setText(f"{entry.game} · {count}")
            self.dict_label.setProperty("muted", False)
            self.stat_dict._value.setText(f"{info['count']:,}")
        else:
            has_db = bool(self.c.settings.get("db_path"))
            self.dict_label.setText(
                "Sözlük seçilmedi — yalnızca yapay zeka kullanılacak"
                if not has_db else "Sözlük dosyası bulunamadı")
            self.stat_dict._value.setText("—")

    def _source_text_from_settings(self):
        s = self.c.settings
        if s.get("source_type") == "camera":
            return f"Kamera / Capture Card (Port {s.get('camera_index', 0)})"
        return "PC Ekranı"

    def _update_engine_hint(self):
        e = self.combo_engine.currentText()
        hints = {
            "Akıllı Zincir (GPT-OSS → Gemini)":
                "En hızlı seçenek. Groq → Gemini sırayla denenir; biri kota "
                "verirse otomatik diğerine geçer. Anahtar gerekir.",
            "Groq AI (Qwen 27B)": "Tek model, çok hızlı. Groq anahtarı gerekir.",
            "Gemini AI": "Google Gemini. Kaliteli ama biraz yavaş.",
            "Google Translate (Ücretsiz)":
                "Anahtar gerekmez, ücretsiz. Uzun cümlelerde bölünme olabilir.",
            "Argos Translate (Çevrimdışı)":
                "İnternetsiz çalışır. Modeli bir kez indirmeniz gerekir.",
        }
        self.engine_hint.setText(hints.get(e, ""))
        need_key = e in ("Akıllı Zincir (GPT-OSS → Gemini)", "Groq AI (Qwen 27B)")
        has_key = bool(self.c.settings.get("groq_api_key"))
        if need_key and not has_key:
            self.engine_hint.setText(
                self.engine_hint.text() + "  ⚠ Groq anahtarı girilmemiş — "
                "Ayarlar'dan ekleyin.")

    def refresh_profiles(self):
        from core.config_manager import ConfigManager
        self.profiles = ConfigManager.load_profiles()
        names = ["Alan seçilmedi / yeni"] + list(self.profiles.keys())
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        self.combo_profile.addItems(names)
        self.combo_profile.setCurrentIndex(0)
        self.combo_profile.blockSignals(False)

    # ------------------------------------------------------------ olaylar
    def _toggle(self):
        if self.c.pipeline and self.c.pipeline.is_running:
            self.c.pause()
            return
        # Alan seçilmemişse kullanıcıyı doğrudan seçime götür
        if not self.c.roi:
            self._show_toast("Önce altyazı alanını seçelim.", "warn")
            self._select_area()
            return
        if self.c.start():
            self._show_hud()
            self._show_toast("Çeviri başladı. Altyazı katmanı oyunun üstünde.",
                             "ok")

    def _show_hud(self):
        from ui.qt.hud import HUDWindow
        first_create = self.c.hud is None
        if first_create:
            geo = (self.c.settings.get("hud_geometry")
                   or self.c.settings.get("window_geometry")
                   or "1000x200+120+620")
            self.c.hud = HUDWindow(geo)
            self.c.hud.toggle_requested.connect(self.c.toggle)
            self.c.hud.reselect_requested.connect(self._select_area)
            self.c.hud.settings_requested.connect(self._open_settings)
            self.c.hud.close_requested.connect(self._quit)
            self.c.hud.geometry_changed.connect(self._save_hud_geometry)
            self.c.hud.apply_style(self.c.style())
        self.c.hud.show()
        self.c.hud.raise_()
        # Kilitli başla: oyunun üstünde tıklamaları engellemesin (show() sonrası Win32 stili uygula)
        locked = True if first_create else bool(getattr(self.c.hud, "locked", True))
        self.c.hud.set_locked(locked, silent=True)
        # HUD'u ekran yakalamadan gizle: OCR kendi altyazısını okumasın
        if not getattr(self.c.hud, "_capture_excluded", False):
            self.c.hud.exclude_from_capture(True)
        self.c.hud.ensure_topmost(force_style=True)
        self._sync_hud_button()

    def _save_hud_geometry(self):
        """Fareyle boyutlandırma/taşıma sonrası konumu kalıcılaştır."""
        if self.c.hud:
            self.c.set_setting("hud_geometry", self.c.hud.geometry_string())

    def _toggle_hud_visible(self):
        """HUD'u göster / gizle (önizleme)."""
        if self.c.hud is not None and self.c.hud.isVisible():
            self.c.hud.hide()
            self._sync_hud_button()
            return
        if self.c.hud is None:
            self._show_hud()
        else:
            self.c.hud.show()
            self.c.hud.raise_()
        # Önizleme sırasında kilit açık olsun ki kullanıcı taşıyabilsin
        if self.c.hud.locked:
            self.c.hud.set_locked(False, silent=True)
        self.c.hud.ensure_topmost(force_style=True)
        if not self.c.hud.view.text():
            self.c.hud.set_text("Altyazı burada görünecek", "ÖNİZLEME",
                                add_history=False)
        self._sync_hud_button()

    def _sync_hud_button(self):
        visible = self.c.hud is not None and self.c.hud.isVisible()
        self.btn_hud.setText("🙈   HUD'u Gizle" if visible else "👁   HUD'u Göster")

    # ------------------------------------------------------------ altyazı akışı
    def _on_text(self, text, source):
        """Çeviri hazır → HUD'a yaz (HUD yoksa oluştur)."""
        if self.c.hud is None:
            if not text:
                return
            self._show_hud()
        self.c.hud.set_text(text or "", source or "")
        if text:
            self.last_text_label.setText(text)
        else:
            self.last_text_label.setText("—")

    def _on_partial(self, text):
        """SSE ile gelen kısmi çeviri → HUD'da anlık göster."""
        if self.c.hud is None:
            self._show_hud()
        self.c.hud.set_text(text or "", "…", add_history=False)
        if text:
            self.last_text_label.setText(f"{text} …")

    def _on_state(self, state):
        labels = {"running": ("Çalışıyor", "ok", "■   Durdur"),
                  "paused": ("Duraklatıldı", "warn", "▶   Devam et"),
                  "idle": ("Hazır", "neutral", "▶   Başlat"),
                  "error": ("Hata", "danger", "▶   Başlat")}
        text, tone, btn = labels.get(state, ("Hazır", "neutral", "▶   Başlat"))
        self.status_chip.setText(text)
        self.status_chip.set_tone(tone)
        self.btn_start.setText(btn)
        titles = {
            "running": "Çeviri çalışıyor",
            "paused": "Duraklatıldı",
            "idle": "Başlamaya hazır",
            "error": "Bir sorun oluştu",
        }
        self.hero_title.setText(titles.get(state, "Başlamaya hazır"))
        if self.c.hud:
            self.c.hud.set_state(state)

    def _on_stats(self, stats):
        self.stat_ocr._value.setText(f"{stats.get('ocr_ms', 0):.0f} ms")
        self.stat_tr._value.setText(f"{stats.get('tr_ms', 0):.0f} ms")
        if self.c.hud:
            self.c.hud.set_state("running", f"{stats.get('ocr_ms', 0):.0f}ms")
        self.hero_sub.setText(
            f"OCR {stats.get('ocr_ms', 0):.0f} ms · çeviri "
            f"{stats.get('tr_ms', 0):.0f} ms · kaynak: {stats.get('source', '—')}")

    def _on_roi(self, roi):
        if not roi:
            self.roi_label.setText("Henüz alan seçilmedi")
            return
        x, y, w, h = roi
        self.roi_label.setText(f"{w} × {h} piksel  ·  konum ({x}, {y})")

    def _show_toast(self, message, tone="neutral"):
        self.toast.show_message(message, tone)
        self.toast._reposition()

    # ------------------------------------------------------------ alan seçimi
    def _select_area(self):
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(250, self._run_roi_selector)

    def _run_roi_selector(self):
        sel = RoiSelector()
        self._roi_selector = sel

        def on_selected(roi):
            roi = self._to_source_relative(roi)
            self.c.set_roi(roi)
            self.show()
            self.raise_()
            self._ask_profile_name(roi)

        sel.selected.connect(on_selected)
        sel.showFullScreen()
        sel.raise_()
        sel.activateWindow()
        sel.setFocus()

    def _to_source_relative(self, roi):
        """
        Tam ekran seçici EKRAN koordinatı verir.
        Kaynak bir pencere ise ROI o pencerenin istemci alanına GÖRELİ olmalı.
        """
        if not roi:
            return roi
        if self.c.settings.get("source_type") != "window":
            return roi
        hwnd = getattr(self.c, "window_handle", 0)
        if not hwnd:
            return roi
        from core.windows import window_client_rect
        rect = window_client_rect(hwnd)
        if not rect:
            return roi
        wx, wy, ww, wh = rect
        x, y, w, h = roi
        rel_x = max(0, x - wx)
        rel_y = max(0, y - wy)
        rel_w = min(w, ww - rel_x)
        rel_h = min(h, wh - rel_y)
        if rel_w <= 0 or rel_h <= 0:
            self._show_toast(
                "Seçilen alan pencere dışında. Pencere içinden seçin.", "warn")
            return None
        return (rel_x, rel_y, rel_w, rel_h)

    def _ask_profile_name(self, roi):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Profili kaydet",
            "Bu alan için bir ad verin (boş bırakırsanız kaydedilmez):")
        if ok and name.strip():
            self.c.set_roi(roi, profile_name=name.strip())
            self.refresh_profiles()
            self._show_toast(f"'{name.strip()}' profili kaydedildi.", "ok")
        else:
            self.c.set_roi(roi)
            self._show_toast("Alan seçildi.", "ok")

    # ------------------------------------------------------------ kaynak
    def _scan_cameras(self):
        from PySide6.QtCore import QThread, Signal as QSignal

        class Scanner(QThread):
            done = QSignal(list)

            def run(self):
                try:
                    self.done.emit(list(list_cameras()))
                except Exception:
                    self.done.emit([])

        self._scanner = Scanner(self)
        self._scanner.done.connect(self._on_cameras)
        self._scanner.start()

    def _on_cameras(self, ports):
        self._cameras = ports
        current = self.combo_source.currentText()
        self.combo_source.blockSignals(True)
        self.combo_source.clear()
        self.combo_source.addItem("PC Ekranı")
        for p in ports:
            self.combo_source.addItem(f"Kamera / Capture Card (Port {p})")

        # Kayıtlı ayar geçersizse (kamera seçili ama kamera yok) ekrana dön
        want_camera = self.c.settings.get("source_type") == "camera"
        want_idx = self.c.settings.get("camera_index", 0)
        if want_camera and want_idx not in ports:
            self.c.settings["source_type"] = "screen"
            self.c.settings["camera_index"] = 0
            self.c.save()
            if self.c.pipeline:
                self.c.pipeline.set_source("screen", 0)
            self._show_toast("Kamera bulunamadı — PC Ekranı kullanılacak.", "warn")
            current = "PC Ekranı"

        idx = self.combo_source.findText(current)
        self.combo_source.setCurrentIndex(max(0, idx))
        self.combo_source.blockSignals(False)
        if not ports:
            self.combo_source.setToolTip(
                "Kamera/capture card bulunamadı — PC Ekranı kullanılacak.")

    def _on_source_change(self, _index):
        text = self.combo_source.currentText()
        if text.startswith("Kamera"):
            try:
                port = int(text.split("Port ")[1].rstrip(")"))
            except Exception:
                port = 0
            self.c.apply_source("camera", port)
            self.window_label.setText("")
        else:
            self.c.window_handle = 0
            self.c.settings.pop("window_handle", None)
            self.c.settings.pop("window_title", None)
            self.c.apply_source("screen", 0)
            self.window_label.setText("")

    # ------------------------------------------------------------ pencere seçimi
    def _pick_window(self):
        dlg = WindowPicker(self, self.c)
        if dlg.exec() and dlg.selected:
            hwnd, title = dlg.selected
            self.c.select_window(hwnd, title)
            self.window_label.setText(
                f"Kaynak pencere: {title}\n"
                "Alan seçimi bu pencerenin İÇİNE göre yapılır; pencere "
                "taşınsa bile takip edilir.")
            self.combo_source.blockSignals(True)
            self.combo_source.setCurrentIndex(0)
            self.combo_source.blockSignals(False)
            self._show_toast(f"Pencere seçildi: {title}", "ok")

    # ------------------------------------------------------------ profil
    def _on_profile_change(self, index):
        if index <= 0:
            return
        name = self.combo_profile.currentText()
        roi = getattr(self, "profiles", {}).get(name)
        if roi:
            self.c.set_roi(tuple(roi))
            self._show_toast(f"'{name}' profili yüklendi.", "ok")

    def _delete_profile(self):
        from PySide6.QtWidgets import QMessageBox
        if self.combo_profile.currentIndex() <= 0:
            return
        name = self.combo_profile.currentText()
        if QMessageBox.question(self, "Profili sil",
                                f"'{name}' profili silinsin mi?") == QMessageBox.Yes:
            from core.config_manager import ConfigManager
            ConfigManager.delete_profile(name)
            self.refresh_profiles()
            self._show_toast("Profil silindi.", "info")

    # ------------------------------------------------------------ motor
    def _on_engine_change(self, text):
        self.c.set_setting("fallback_engine", text)
        self.c.translator.fallback_engine = text
        self._update_engine_hint()

    def _on_lang_change(self, text):
        self.c.set_setting("target_language", text)
        self.c.translator.target_language = text

    # ------------------------------------------------------------ pencereler
    def _open_settings(self):
        from ui.qt.settings_window import SettingsWindow
        self._settings_win = SettingsWindow(self.c, self)
        self._settings_win.show()
        self._settings_win.raise_()

    def _open_dictionary(self):
        from ui.qt.dictionary_window import DictionaryWindow
        self._dict_win = DictionaryWindow(self.c, self)
        self._dict_win.show()
        self._dict_win.raise_()

    def _open_chiaki(self):
        from ui.qt.chiaki_window import ChiakiWindow
        self._chiaki_win = ChiakiWindow(self.c, self)
        self._chiaki_win.show()
        self._chiaki_win.raise_()

    def _open_help(self):
        from ui.qt.onboarding import OnboardingWindow
        self._help_win = OnboardingWindow(self.c, self, help_mode=True)
        self._help_win.show()
        self._help_win.raise_()

    def _quit(self):
        self.c.shutdown()
        QApplication.quit()

    def closeEvent(self, e):
        self.c.shutdown()
        e.accept()



class WindowPicker(QDialog):
    """
    Açık pencerelerden birini seçtiren diyalog.
    Oyun / video oynatıcı / Chiaki-ng penceresini seçmek için.
    """

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.setWindowTitle("Pencere Seç")
        self.setMinimumSize(620, 440)
        self.selected = None
        self.c = controller

        from PySide6.QtWidgets import QDialogButtonBox
        lay = QVBoxLayout(self)
        lay.setSpacing(S.MD)

        lay.addWidget(label("Hangi pencereden okusun?", size=12, bold=True))
        lay.addWidget(label(
            "Oyunu veya videoyu oynatan pencereyi seçin. Küçültülmüş "
            "pencereler listede görünmez.", "muted", size=9, wrap=True))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pencere adında ara…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._accept())
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        btn_refresh = QPushButton("↻  Yenile")
        btn_refresh.clicked.connect(self._reload)
        row.addWidget(btn_refresh)
        row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)

        self._reload()

    def _reload(self):
        from core.windows import list_windows
        self.list.clear()
        wins = list_windows(include_own=False)
        # Başlığa göre grupla, uzun başlıkları kısalt
        for w in sorted(wins, key=lambda x: x["title"].lower()):
            x, y, ww, hh = w["rect"]
            title = w["title"]
            if len(title) > 70:
                title = title[:67] + "…"
            item = QListWidgetItem(f"{title}\n      {ww} × {hh} px  ·  ({x}, {y})")
            item.setData(Qt.UserRole, (w["hwnd"], w["title"]))
            self.list.addItem(item)
        if self.list.count() == 0:
            it = QListWidgetItem("Açık pencere bulunamadı.")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def _filter(self, text):
        text = (text or "").lower().strip()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    def _accept(self):
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        self.selected = data
        self.accept()

