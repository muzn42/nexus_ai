"""
NEXUS AI — PS5 / Chiaki-ng Penceresi

PS5'te oyunu kendi dilinde oynamak isteyen biri için "önce görüntüyü
bilgisayara getir" adımı en zor kısımdır. Bu pencere onu kolaylaştırır:

  1) Chiaki-ng kurulu mu? → tek tıkla başlat, değilse indirme bağlantısı
  2) Ağdaki PS5'i otomatik bul (Remote Play portu 9295 taraması)
  3) Adım adım rehber
"""
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from core import chiaki
from core.theme import C, S
from ui.qt.components import Card, Chip, Divider, FramelessWindow, Toast, label


class ChiakiWindow(FramelessWindow):
    """PS5 bağlantı yardımcısı."""

    _found = Signal(list)
    _progress = Signal(int, int)

    def __init__(self, controller, parent=None):
        super().__init__("PS5 · Chiaki-ng", "PS5 görüntüsünü bilgisayara getir",
                         width=880, height=640)
        self.c = controller
        self.toast = Toast(self, "", ms=10)
        self._scanning = False

        body = QHBoxLayout()
        body.setSpacing(S.LG)

        # --- sol kolon ---
        left = QVBoxLayout()
        left.setSpacing(S.MD)

        self.state_card = Card("Chiaki-ng", "PS5 Remote Play istemcisi")
        self.chip_state = Chip("Kontrol ediliyor…", "neutral", self.state_card)
        self.state_row = QHBoxLayout()
        self.state_row.addWidget(self.chip_state)
        self.state_row.addStretch(1)
        self.state_card.add_layout(self.state_row)

        self.state_info = label("", "muted", size=9, wrap=True)
        self.state_card.add(self.state_info)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.SM)
        self.btn_launch = QPushButton("Chiaki-ng'yi Başlat")
        self.btn_launch.setProperty("variant", "primary")
        self.btn_launch.setCursor(Qt.PointingHandCursor)
        self.btn_launch.clicked.connect(self._launch)
        btn_row.addWidget(self.btn_launch)

        btn_dl = QPushButton("İndir")
        btn_dl.clicked.connect(self._open_download)
        btn_row.addWidget(btn_dl)

        btn_browse = QPushButton("Gözat…")
        btn_browse.setToolTip("chiaki.exe dosyasını elle seç "
                              "(portable sürümler için)")
        btn_browse.clicked.connect(self._browse)
        btn_row.addWidget(btn_browse)
        btn_row.addStretch(1)
        self.state_card.add_layout(btn_row)
        left.addWidget(self.state_card)

        # --- ağ taraması ---
        scan_card = Card("PS5'imi Bul",
                         "Ağdaki PS5'i Remote Play portundan otomatik arar "
                         "(yalnızca yerel ağ, 5-10 saniye).")
        self.btn_scan = QPushButton("Aramayı Başlat")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self._scan)
        scan_card.add(self.btn_scan)

        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        scan_card.add(self.scan_progress)

        self.results = QListWidget()
        self.results.setMaximumHeight(110)
        scan_card.add(self.results)

        self.scan_hint = label("", "faint", size=9, wrap=True)
        scan_card.add(self.scan_hint)
        left.addWidget(scan_card)
        left.addStretch(1)

        left_w = QWidget()
        left_w.setLayout(left)
        body.addWidget(left_w, 1)

        # --- sağ: rehber ---
        guide = Card("Kurulum rehberi", "Sırayla ilerleyin.")
        for i, step in enumerate(chiaki.GUIDE_STEPS, start=1):
            num = label(str(i), size=10, bold=True)
            num.setStyleSheet(
                f"color:{C.ACCENT}; background:{C.ACCENT_SOFT};"
                f" border-radius:11px; padding:2px 9px;")
            head = QHBoxLayout()
            head.setSpacing(S.SM)
            head.addWidget(num, 0, Qt.AlignTop)
            head.addWidget(label(step["title"], size=10, bold=True), 1)
            guide.add_layout(head)
            guide.add(label(step["detail"], "muted", size=9, wrap=True))
            if i < len(chiaki.GUIDE_STEPS):
                guide.add(Divider())
        guide.add(Divider())
        guide.add(label(
            "İpucu: PS5 görüntüsü bilgisayara geldikten sonra Nexus AI'da "
            "kaynak olarak 'PC Ekranı'nı seçip altyazı alanını işaretlemen yeterli.",
            "faint", size=9, wrap=True))
        body.addWidget(guide, 1)
        self.content_lay.addLayout(body, 1)

        # --- doğrudan kablo (CAT5e) bölümü ---
        direct = Card("Doğrudan kablo (PS5 ↔ PC)",
                      "Router olmadan, en düşük gecikme. İnternet gerekmez.")
        self.chip_direct = Chip("Kontrol ediliyor…", "neutral", direct)
        self.direct_row = QHBoxLayout()
        self.direct_row.addWidget(self.chip_direct)
        self.direct_row.addStretch(1)
        direct.add_layout(self.direct_row)

        self.direct_info = label("", "muted", size=9, wrap=True)
        direct.add(self.direct_info)

        drow = QHBoxLayout()
        drow.setSpacing(S.SM)
        btn_script = QPushButton("Kurulum Script'ini Aç")
        btn_script.setProperty("variant", "primary")
        btn_script.setToolTip(
            "tools/setup_ps5_direct.bat — Yönetici olarak çalıştırın "
            "(PC IP + adaptör hız ayarları)")
        btn_script.clicked.connect(self._open_setup_script)
        drow.addWidget(btn_script)

        btn_recheck = QPushButton("Yeniden Kontrol Et")
        btn_recheck.clicked.connect(self._check_direct)
        drow.addWidget(btn_recheck)
        drow.addStretch(1)
        direct.add_layout(drow)

        direct.add(Divider())
        direct.add(label("PS5'te yapılacaklar", size=9, bold=True))
        for i, step in enumerate(chiaki.DIRECT_CABLE_STEPS, start=1):
            direct.add(label(f"{i}. {step['title']}", size=9, bold=True))
            direct.add(label(step["detail"], "muted", size=8, wrap=True))

        direct.add(Divider())
        direct.add(label("Chiaki-ng akış ayarları (önerilen)", size=9, bold=True))
        for name, value, why in chiaki.STREAM_SETTINGS:
            direct.add(label(f"•  {name}: {value}  —  {why}", "muted", size=8,
                             wrap=True))

        self.content_lay.addWidget(direct, 0)

        self._found.connect(self._on_found)
        self._progress.connect(self._on_progress)

        QTimer.singleShot(120, self._detect)
        QTimer.singleShot(600, self._check_direct)

    # ------------------------------------------------------------ tespit
    def _detect(self):
        path = chiaki.find_chiaki()
        if path:
            self.chip_state.setText("Kurulu")
            self.chip_state.set_tone("ok")
            self.state_info.setText(f"Bulundu: {path}")
            self.btn_launch.setEnabled(True)
        else:
            self.chip_state.setText("Bulunamadı")
            self.chip_state.set_tone("warn")
            self.state_info.setText(
                "Chiaki-ng otomatik bulunamadı. Portable sürüm kullanıyorsanız "
                "'Gözat…' ile chiaki.exe dosyasını seçin (bir kez yeterli). "
                "Kurulu değilse 'İndir' ile resmi sürümü indirin.")
            self.btn_launch.setEnabled(False)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "chiaki.exe dosyasını seç", "",
            "Chiaki (chiaki.exe chiaki-ng.exe);;Çalıştırılabilir (*.exe);;Tümü (*)")
        if not path:
            return
        chiaki.remember_path(path)
        self._detect()
        self._notify("Chiaki-ng yolu kaydedildi.", "ok")

    def _launch(self):
        ok, msg = chiaki.launch_chiaki()
        self._notify(msg, "ok" if ok else "danger")

    def _open_download(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(chiaki.CHIAKI_DOWNLOAD_URL))
        self._notify("Tarayıcıda indirme sayfası açıldı.", "info")

    # ------------------------------------------------------------ tarama
    def _scan(self):
        if self._scanning:
            return
        self._scanning = True
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Taranıyor…")
        self.scan_progress.setVisible(True)
        self.scan_progress.setValue(0)
        self.results.clear()
        self.scan_hint.setText(f"Yerel ağ: {chiaki.get_local_ip()}")

        def work():
            def progress(done, total):
                pct = int(done * 100 / total)
                self._progress.emit(pct, total)

            found = chiaki.discover_ps5(progress_cb=progress)
            self._found.emit(found)

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, pct, _total):
        self.scan_progress.setValue(pct)

    def _on_found(self, ips):
        self._scanning = False
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("Yeniden Ara")
        self.scan_progress.setVisible(False)
        if ips:
            for ip in ips:
                self.results.addItem(f"{ip}   —   muhtemel PS5 (port 9295 açık)")
            self.scan_hint.setText(
                "Bu IP'yi Chiaki-ng'de 'Add Host' alanına yazın. "
                "Bulunan cihaz PS5 değilse yok sayın.")
            self._notify(f"{len(ips)} cihaz bulundu.", "ok")
        else:
            self.scan_hint.setText(
                "Cihaz bulunamadı. PS5 açık ve aynı Wi-Fi ağında mı? "
                "Uzaktan Oynatma etkin mi? Ethernet kablosu daha güvenilir.")
            self._notify("Cihaz bulunamadı.", "warn")

    def _notify(self, msg, tone="neutral"):
        self.toast.show_message(msg, tone)
        self.toast._reposition()

    # ------------------------------------------------------------ doğrudan kablo
    def _check_direct(self):
        """Kablo bağlantısını denetler (arka planda, UI'yı bloklamaz)."""
        self.chip_direct.setText("Kontrol ediliyor…")
        self.chip_direct.set_tone("neutral")
        self.chip_direct.adjustSize()

        def work():
            info = chiaki.check_direct_link()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._show_direct(info))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _show_direct(self, info):
        lines = []
        if info.get("adapter"):
            lines.append(f"Adaptör: {info['adapter']}  ·  "
                         f"{info.get('speed', '?')}  ·  "
                         f"IP: {info.get('ip', '—')}")
        if info.get("ps5_reachable"):
            host = info.get("ps5_host", "192.168.100.2")
            lines.append(f"PS5 Remote Play portu (9295) YANIT VERİYOR ✓")
            lines.append(f"Chiaki-ng'ye IP olarak {host} girin.")
        self.direct_info.setText("\n".join(lines) if lines else "")

        if info.get("ok"):
            self.chip_direct.setText("Bağlı ✓")
            self.chip_direct.set_tone("ok")
        elif info.get("apipa"):
            self.chip_direct.setText("IP verilmemiş")
            self.chip_direct.set_tone("warn")
        elif not info.get("link_up"):
            self.chip_direct.setText("Kablo takılı değil")
            self.chip_direct.set_tone("danger")
        else:
            self.chip_direct.setText("PS5 yanıt vermiyor")
            self.chip_direct.set_tone("warn")
        self.chip_direct.adjustSize()

        notes = info.get("notes") or []
        if notes:
            self.direct_info.setText(
                (self.direct_info.text() + "\n" if self.direct_info.text()
                 else "") + "\n".join(f"• {n}" for n in notes))

    def _open_setup_script(self):
        """setup_ps5_direct.bat dosyasını aç (yönetici olarak çalıştırması için)."""
        import os
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from core.config_manager import BASE_DIR

        path = os.path.join(BASE_DIR, "tools", "setup_ps5_direct.bat")
        if not os.path.isfile(path):
            self._notify("Kurulum script'i bulunamadı.", "danger")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self._notify(
            "Açılan dosyaya SAĞ TIK → 'Yönetici olarak çalıştır'. "
            "Sonra 'Yeniden Kontrol Et'e bas.", "info")
