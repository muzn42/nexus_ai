"""
NEXUS AI — Sözlük Kütüphanesi

Tek ekranda: kütüphane listesi, sözlük detayları, indirme, dosyadan yükleme
ve sözlük içinde iki dilli arama.

Akış (ilk kez kullanan için):
  1) Soldan bir sözlük seç (ya da "Dosyadan Yükle")
  2) Sağda satır sayısını gör, istersen içinde ara
  3) "Aktif Yap" → ana ekran bu sözlüğü kullanmaya başlar
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core.db_catalog import DictionaryLibrary, format_size
from core.theme import S
from ui.qt.components import Card, Chip, FramelessWindow, Toast, label, vbox


class DictionaryWindow(FramelessWindow):
    """Sözlük kütüphanesi penceresi."""

    _download_done = Signal(bool, str)
    _import_done = Signal(bool, str)

    def __init__(self, controller, parent=None):
        super().__init__("Sözlük Kütüphanesi",
                         "Oyun çeviri veritabanları", width=900, height=680)
        self.c = controller
        self.lib: DictionaryLibrary = controller.library
        self._selected = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._run_search)

        self.toast = Toast(self, "", ms=10)

        # --- üst araç çubuğu ---
        top = QHBoxLayout()
        top.setSpacing(S.SM)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Sözlük listesinde ara…  (ör. Red Dead)")
        self.search_field.textChanged.connect(self._filter_list)
        top.addWidget(self.search_field, 1)

        btn_import = QPushButton("Dosyadan Yükle")
        btn_import.clicked.connect(self._import_file)
        top.addWidget(btn_import)

        btn_refresh = QPushButton("↻")
        btn_refresh.setProperty("icon", True)
        btn_refresh.setToolTip("Yerel dosyaları yeniden tara")
        btn_refresh.setFixedSize(38, 38)
        btn_refresh.clicked.connect(self._rescan)
        top.addWidget(btn_refresh)
        self.content_lay.addLayout(top)

        # --- gövde: sol liste | sağ detay ---
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        left_card = Card("Kütüphane")
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        left_card.add(self.list, 1)
        self.library_hint = label("", "faint", size=9, wrap=True)
        left_card.add(self.library_hint)
        split.addWidget(left_card)

        right = QWidget()
        rl = vbox(right, spacing=S.MD)
        self.detail = Card("Sözlük seçilmedi",
                           "Soldan bir sözlük seçin veya dosyadan yükleyin.")
        self.detail_row = QHBoxLayout()
        self.detail_row.setSpacing(S.SM)
        self.chip_state = Chip("—", "neutral", self.detail)
        self.detail_row.addWidget(self.chip_state)
        self.chip_lang = Chip("EN → TR", "info", self.detail)
        self.detail_row.addWidget(self.chip_lang)
        self.detail_row.addStretch(1)
        self.detail.add_layout(self.detail_row)

        self.detail_info = label("", "muted", size=9, wrap=True)
        self.detail.add(self.detail_info)

        actions = QHBoxLayout()
        actions.setSpacing(S.SM)
        self.btn_activate = QPushButton("Aktif Yap")
        self.btn_activate.setProperty("variant", "primary")
        self.btn_activate.setCursor(Qt.PointingHandCursor)
        self.btn_activate.clicked.connect(self._activate)
        actions.addWidget(self.btn_activate)

        self.btn_download = QPushButton("İndir")
        self.btn_download.clicked.connect(self._download)
        actions.addWidget(self.btn_download)

        self.btn_delete = QPushButton("Sil")
        self.btn_delete.setProperty("variant", "danger")
        self.btn_delete.clicked.connect(self._delete)
        actions.addWidget(self.btn_delete)
        actions.addStretch(1)
        self.detail.add_layout(actions)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.detail.add(self.progress)
        rl.addWidget(self.detail)

        # sözlük içi arama
        self.preview_card = Card("Sözlük içinde ara",
                                 "Kelime veya cümle yazın — anında sonuç.")
        self.preview_field = QLineEdit()
        self.preview_field.setPlaceholderText("ör. stranger")
        self.preview_field.textChanged.connect(lambda: self._search_timer.start(250))
        self.preview_field.setEnabled(False)
        self.preview_card.add(self.preview_field)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["İngilizce", "Türkçe"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_card.add(self.table, 1)
        rl.addWidget(self.preview_card, 1)

        split.addWidget(right)
        split.setSizes([300, 570])
        self.content_lay.addWidget(split, 1)

        self._download_done.connect(self._on_download_done)
        self._import_done.connect(self._on_import_done)

        self._reload_list()

    # ------------------------------------------------------------ liste
    def _reload_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        items = self.lib.all()
        items.sort(key=lambda d: (not d.is_installed(), d.game.lower()))
        for d in items:
            installed = d.is_installed()
            count = ""
            if installed:
                info = self.lib.stats(d.path)
                count = f"{info['count']:,} satır" if info["ok"] else "okunamadı"
            mark = "●" if installed else "○"
            text = f"{mark}  {d.game}"
            text += (f"\n      {count} · {format_size(d.size_bytes())}"
                     if count else "\n      yüklü değil")
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, d.id)
            it.setForeground(Qt.white if installed else Qt.gray)
            self.list.addItem(it)
        self.list.blockSignals(False)

        installed = len(self.lib.installed())
        self.library_hint.setText(
            f"{installed} yüklü / {len(items)} kayıt.   ● yüklü   ○ yüklü değil")
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _filter_list(self, text):
        text = (text or "").lower().strip()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    def _on_select(self, current, _previous=None):
        if current is None:
            return
        self._selected = self.lib.get(current.data(Qt.UserRole))
        self._refresh_detail()

    def _refresh_detail(self):
        d = self._selected
        if d is None:
            self.detail.title_label.setText("Sözlük seçilmedi")
            return
        installed = d.is_installed()
        self.detail.title_label.setText(d.game)
        self.chip_state.setText("Yüklü" if installed else "Yüklü değil")
        self.chip_state.set_tone("ok" if installed else "warn")
        self.chip_lang.setText(d.lang_label())

        if installed:
            info = self.lib.stats(d.path)
            parts = [
                f"{info['count']:,} satır" if info["ok"] else "şema okunamadı",
                format_size(d.size_bytes()),
                d.note or "",
                f"v{d.version}" if d.version else "",
            ]
            self.detail_info.setText("   ·   ".join(p for p in parts if p))
        else:
            self.detail_info.setText(
                d.note or "Bu sözlük henüz indirilmemiş. "
                          "'İndir' veya 'Dosyadan Yükle' kullanın.")

        active_path = str(self.c.settings.get("db_path") or "").lower()
        is_active = bool(active_path) and d.path.lower() == active_path
        self.btn_activate.setEnabled(installed and not is_active)
        self.btn_activate.setText("Aktif" if is_active else "Aktif Yap")
        self.btn_download.setVisible(not installed and bool(d.source_url))
        self.btn_download.setEnabled(bool(d.source_url))
        self.btn_delete.setEnabled(True)

        self.preview_field.setEnabled(installed)
        self.preview_field.setPlaceholderText(
            "ör. stranger" if installed else "Sözlük yüklü değil")
        self.table.setRowCount(0)
        if installed:
            self._run_search()

    # ------------------------------------------------------------ arama
    def _run_search(self):
        d = self._selected
        if d is None or not d.is_installed():
            return
        q = self.preview_field.text().strip()
        rows = self.lib.search(d.path, q, limit=300) if q else []
        self.table.setRowCount(len(rows))
        for i, (src, tgt) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(src))
            self.table.setItem(i, 1, QTableWidgetItem(tgt))

    # ------------------------------------------------------------ eylemler
    def _activate(self):
        d = self._selected
        if d is None or not d.is_installed():
            return
        self.c.set_dictionary(d.path)
        self._refresh_detail()
        self._reload_list()
        self._notify(f"{d.game} aktif sözlük yapıldı.", "ok")

    def _notify(self, msg, tone="neutral"):
        self.toast.show_message(msg, tone)
        self.toast._reposition()

    def _download(self):
        d = self._selected
        if d is None or not d.source_url:
            self._notify("Bu kaydın indirme adresi yok. "
                         "'Dosyadan Yükle' kullanın.", "warn")
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_download.setEnabled(False)

        def work():
            def progress(done, total):
                if total:
                    pct = int(done * 100 / total)
                    QTimer.singleShot(0, lambda: self.progress.setValue(pct))

            ok, msg = self.lib.download(d, progress_cb=progress)
            self._download_done.emit(ok, msg)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _on_download_done(self, ok, msg):
        self.progress.setVisible(False)
        self.btn_download.setEnabled(True)
        self._reload_list()
        self._refresh_detail()
        self._notify(msg, "ok" if ok else "danger")

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Sözlük dosyası seç", "",
            "SQLite veritabanı (*.db *.sqlite);;Tüm dosyalar (*)")
        if not path:
            return
        ok, msg, entry = self.lib.import_file(path)
        self._on_import_done(ok, msg)
        if ok and entry:
            self._reload_list()
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole) == entry.id:
                    self.list.setCurrentRow(i)
                    break

    def _on_import_done(self, ok, msg):
        self._notify(msg, "ok" if ok else "danger")

    def _delete(self):
        d = self._selected
        if d is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Sözlüğü sil")
        box.setText(f"'{d.game}' kütüphaneden çıkarılsın mı?")
        box.setInformativeText(
            "Dosya da silinsin mi? 'Hayır' derseniz yalnızca kayıt kaldırılır.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.No)
        ret = box.exec()
        if ret == QMessageBox.Cancel:
            return
        was_active = str(self.c.settings.get("db_path") or "").lower() == d.path.lower()
        ok, msg = self.lib.remove(d.id, delete_file=(ret == QMessageBox.Yes))
        if ok and was_active:
            self.c.set_dictionary("", announce=False)
        self._selected = None
        self._reload_list()
        self._refresh_detail()
        self._notify(msg, "info")

    def _rescan(self):
        added = self.lib.scan_local()
        self._reload_list()
        if added:
            self._notify(f"{len(added)} yeni sözlük bulundu.", "ok")
        else:
            self._notify("Yeni sözlük bulunamadı.", "info")
