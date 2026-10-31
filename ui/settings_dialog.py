"""
NEXUS AI v2 — Ayarlar Penceresi
TranslationApp'tan ayrılmış, bağımsız ayarlar diyaloğu.
"""
import os
import threading
import tkinter as tk
from tkinter import messagebox, colorchooser, filedialog
import customtkinter as ctk
import keyboard

from core.config_manager import ConfigManager, APP_NAME, DATA_DIR
from ui.launcher import list_available_cameras


class SettingsDialog:
    """Ayarlar Penceresi — Tüm ayarları sidebar ile kategorize eder."""

    def __init__(self, app):
        self.app = app
        self.sw = ctk.CTkToplevel(app.root)
        self.sw.title("Ayarlar")
        self.sw.geometry("750x560")
        self.sw.attributes("-topmost", True)

        self.sw.grid_columnconfigure(1, weight=1)
        self.sw.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self.sw, width=180, corner_radius=0, fg_color="#1a1a2e")
        sidebar.grid(row=0, column=0, sticky="nsew")

        content_area = ctk.CTkFrame(self.sw, corner_radius=0, fg_color="transparent")
        content_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

        self.content_area = content_area

        pages = ["Genel", "Görüntü", "Kısayollar", "Algılama", "Motor", "Hakkında"]
        for p in pages:
            ctk.CTkButton(
                sidebar, text=p, command=lambda b=p: self._show_page(b),
                fg_color="transparent", text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"), anchor="w",
                font=("Segoe UI", 12)
            ).pack(fill="x", pady=2, padx=5)

        ctk.CTkLabel(
            sidebar, text=APP_NAME,
            font=("Segoe UI", 13, "bold"), text_color="#6c5ce7"
        ).pack(side="bottom", pady=20)

        self._show_page("Genel")

    def _show_page(self, page_name):
        for w in self.content_area.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.content_area, text=page_name,
            font=("Segoe UI", 20, "bold")
        ).pack(anchor="w", pady=(0, 15))

        pages = {
            "Genel": self._page_general,
            "Görüntü": self._page_visual,
            "Kısayollar": self._page_keys,
            "Algılama": self._page_detect,
            "Motor": self._page_engine,
            "Hakkında": self._page_about,
        }
        pages.get(page_name, lambda p: None)(self.content_area)

    # === GENEL ===
    def _page_general(self, parent):
        s = self.app.settings

        ctk.CTkLabel(parent, text="Çeviri Dili:", font=("Segoe UI", 12)).pack(anchor="w")
        langs = {"Türkçe": "tr", "İngilizce": "en", "Almanca": "de", "Fransızca": "fr",
                 "İspanyolca": "es", "Japonca": "ja", "Rusça": "ru"}
        combo_lang = ctk.CTkComboBox(parent, values=list(langs.keys()))
        current = [k for k, v in langs.items() if v == s.get("target_language", "Türkçe")]
        combo_lang.set(current[0] if current else "Türkçe")
        combo_lang.pack(fill="x", pady=5)

        def save_lang(event):
            s["target_language"] = langs.get(combo_lang.get(), "Türkçe")
            self.app.translation_engine.target_language = s["target_language"]
            self.app.save_settings()
        combo_lang.configure(command=save_lang)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=15)

        ctk.CTkLabel(parent, text="Görüntü Kaynağı:", font=("Segoe UI", 12)).pack(anchor="w")
        combo_source = ctk.CTkComboBox(parent, values=["Yükleniyor..."])
        display = "PC Ekranı" if s.get("source_type") == "screen" else f"Kamera / Capture Card (Port {s.get('camera_index', 0)})"
        combo_source.set(display)
        combo_source.pack(fill="x", pady=5)
        threading.Thread(target=lambda: self._load_sources(combo_source), daemon=True).start()

        def apply_src():
            sel = combo_source.get()
            if sel == "Yükleniyor...": return
            st, idx = "screen", 0
            if "PC Ekranı" not in sel:
                st = "camera"
                try: idx = int(sel.split("Port ")[1].replace(")", ""))
                except Exception: pass
            self.app.set_source(st, idx)
            messagebox.showinfo("Bilgi", "Kaynak değiştirildi.")
        ctk.CTkButton(parent, text="Kaynağı Uygula", command=apply_src, fg_color="#6c5ce7").pack(fill="x", pady=8)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=15)

        # Profil
        ctk.CTkLabel(parent, text="Aktif Çeviri Alanı:", font=("Segoe UI", 12)).pack(anchor="w")
        profiles = ConfigManager.load_profiles()
        names = list(profiles.keys()) or ["Kayıtlı Profil Yok"]
        combo_prof = ctk.CTkComboBox(parent, values=names)
        combo_prof.set("Seçiniz")
        combo_prof.pack(fill="x", pady=5)

        def apply_prof(choice):
            if choice in profiles:
                self.app.roi = tuple(profiles[choice])
                self.app.set_text(f"Profil '{choice}' yüklendi.")
        combo_prof.configure(command=apply_prof)

    def _load_sources(self, combo):
        ports = list_available_cameras()
        try: combo.configure(values=ports)
        except Exception: pass

    # === GÖRÜNTÜ ===
    def _page_visual(self, parent):
        s = self.app.settings

        ctk.CTkLabel(parent, text="Pencere Modu:", font=("Segoe UI", 12)).pack(anchor="w")
        var_op = tk.StringVar(value=s.get("opacity_mode", "Transparent"))
        for t, m in [("Şeffaf", "Transparent"), ("Yarı Şeffaf", "Semi"), ("Opak", "Opaque")]:
            ctk.CTkRadioButton(parent, text=t, variable=var_op, value=m,
                command=lambda: self._set_and_save("opacity_mode", var_op.get(), apply_visual=True)
            ).pack(anchor="w", pady=2)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=10)

        ctk.CTkButton(parent, text="Arka Plan Rengi", command=lambda: self._pick_color("bg_color"), fg_color="#555555").pack(fill="x", pady=2)
        ctk.CTkButton(parent, text="Yazı Rengi", command=lambda: self._pick_color("text_color"), fg_color="#555555").pack(fill="x", pady=2)
        ctk.CTkButton(parent, text="Dış Çizgi Rengi", command=lambda: self._pick_color("stroke_color"), fg_color="#555555").pack(fill="x", pady=2)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=10)

        ctk.CTkLabel(parent, text="Yazı Boyutu:", font=("Segoe UI", 12)).pack(anchor="w")
        slider = ctk.CTkSlider(parent, from_=10, to=100,
            command=lambda v: self._set_and_save("font_size", int(v), apply_visual=True))
        slider.set(s.get("font_size", 24))
        slider.pack(fill="x", pady=5)

        ctk.CTkLabel(parent, text="Dış Çizgi Kalınlığı:", font=("Segoe UI", 12)).pack(anchor="w")
        slider_sw = ctk.CTkSlider(parent, from_=0, to=5,
            command=lambda v: self._set_and_save("stroke_width", int(v), apply_visual=True))
        slider_sw.set(s.get("stroke_width", 2))
        slider_sw.pack(fill="x", pady=5)

    def _pick_color(self, key):
        color = colorchooser.askcolor()[1]
        if color:
            self._set_and_save(key, color, apply_visual=True)

    def _set_and_save(self, key, value, apply_visual=False):
        self.app.settings[key] = value
        self.app.save_settings()
        if apply_visual:
            self.app.apply_visual_settings()

    # === KISAYOLLAR ===
    def _page_keys(self, parent):
        ctk.CTkLabel(parent, text="Tıklayıp yeni tuşa basın.", text_color="gray").pack(anchor="w", pady=(0, 10))
        for label, var in [("Başlat/Durdur", "hotkey_start"), ("Alan Seç", "hotkey_reselect"),
                           ("Minimal Mod", "hotkey_minimal"), ("Taşıma Modu", "hotkey_move"),
                           ("Çıkış", "hotkey_exit")]:
            self._create_key_binder(parent, label, var)

    def _create_key_binder(self, parent, label_text, var_name):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text=label_text, width=120, anchor="w").pack(side="left")
        btn = ctk.CTkButton(f, text=self.app.settings.get(var_name, "?").upper(), width=100)
        btn.pack(side="right")

        def record():
            if self.app.is_recording_key: return
            self.app.is_recording_key = True
            btn.configure(text="...", fg_color="#e67e22")
            threading.Thread(target=lambda: capture(btn, var_name), daemon=True).start()

        def capture(b, v):
            try:
                k = keyboard.read_hotkey(suppress=False)
                self.app.root.after(0, lambda: done(b, v, k))
            except Exception:
                self.app.root.after(0, lambda: done(b, v, None))

        def done(b, v, k):
            if k and k != 'esc':
                self.app.settings[v] = k
                self.app.save_settings()
            b.configure(text=self.app.settings.get(v, "?").upper(), fg_color="#3B8ED0")
            self.app.is_recording_key = False
            self.app.update_help_tooltip()

        btn.configure(command=record)

    # === ALGILAMA ===
    def _page_detect(self, parent):
        var_sf = tk.BooleanVar(value=self.app.settings.get("smart_filter_enabled", False))
        ctk.CTkCheckBox(parent, text="Akıllı Filtreleme (Siyah-Beyaz)", variable=var_sf,
            command=lambda: self._set_and_save("smart_filter_enabled", var_sf.get())
        ).pack(anchor="w", pady=10)
        ctk.CTkLabel(parent, text="Açık: Arka plan değişimlerini yoksayar.\nKapalı: Tüm değişimleri izler (daha hassas).",
                     text_color="gray", justify="left").pack(anchor="w", padx=20)

    # === MOTOR ===
    def _page_engine(self, parent):
        s = self.app.settings

        # 1. Çeviri motoru
        ctk.CTkLabel(parent, text="1. Çeviri Sistemi", font=("Segoe UI", 13, "bold"), text_color="#00d2d3").pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(parent, text="Öncelikli: Yerel Veritabanı (0 ms, ücretsiz)", text_color="#2ecc71", font=("Segoe UI", 11)).pack(anchor="w", pady=2)

        ctk.CTkLabel(parent, text="Yedek Çevirmen:", font=("Segoe UI", 12)).pack(anchor="w", pady=(8, 2))
        engines = ["Google Translate (Ücretsiz)", "Argos Translate (Çevrimdışı)", "Gemini AI"]
        combo_eng = ctk.CTkComboBox(parent, values=engines)
        combo_eng.set(s.get("fallback_engine", engines[0]))
        combo_eng.pack(fill="x", pady=5)

        def on_eng(choice):
            self._set_and_save("fallback_engine", choice)
            self.app.translation_engine.fallback_engine = choice
        combo_eng.configure(command=on_eng)

        # Otomatik öğrenme
        var_al = tk.BooleanVar(value=s.get("auto_learn_enabled", True))
        ctk.CTkCheckBox(parent, text="Otomatik Öğrenme (çevirileri yerel DB'ye kaydet)", variable=var_al,
            command=lambda: [self._set_and_save("auto_learn_enabled", var_al.get()),
                             setattr(self.app.translation_engine, 'auto_learn_enabled', var_al.get())]
        ).pack(anchor="w", pady=5)

        # Gemini API
        ctk.CTkLabel(parent, text="Gemini API Anahtarı (opsiyonel):", font=("Segoe UI", 11)).pack(anchor="w", pady=(10, 2))
        entry_key = ctk.CTkEntry(parent, placeholder_text="API Anahtarınızı Yapıştırın...", show="*")
        entry_key.insert(0, s.get("gemini_api_key", ""))
        entry_key.pack(fill="x", pady=5)

        def save_key():
            self._set_and_save("gemini_api_key", entry_key.get().strip())
            self.app.translation_engine.gemini_api_key = entry_key.get().strip()
            self.app.translation_engine._gemini_model = None
            messagebox.showinfo("Kaydedildi", "API Anahtarı güncellendi.")
        ctk.CTkButton(parent, text="Kaydet", command=save_key, fg_color="#444444", width=100).pack(anchor="e", pady=3)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=12)

        # 2. OCR
        ctk.CTkLabel(parent, text="2. OCR Ayarları", font=("Segoe UI", 13, "bold"), text_color="#00d2d3").pack(anchor="w", pady=(0, 5))

        combo_ver = ctk.CTkComboBox(parent, values=["PP-OCRv5 (Daha Doğru)", "PP-OCRv4 (Daha Hızlı)"])
        combo_ver.set("PP-OCRv5 (Daha Doğru)" if s.get("paddle_version") == "PP-OCRv5" else "PP-OCRv4 (Daha Hızlı)")
        combo_ver.pack(fill="x", pady=5)

        def on_ver(choice):
            ver = "PP-OCRv5" if "v5" in choice else "PP-OCRv4"
            self._set_and_save("paddle_version", ver)
            self.app.ocr_engine.reset(version=ver)
        combo_ver.configure(command=on_ver)

        var_mk = tk.BooleanVar(value=s.get("use_mkldnn", True))
        ctk.CTkCheckBox(parent, text="CPU Hızlandırma (MKLDNN)", variable=var_mk,
            command=lambda: [self._set_and_save("use_mkldnn", var_mk.get()),
                             self.app.ocr_engine.reset(use_mkldnn=var_mk.get())]
        ).pack(anchor="w", pady=5)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=12)

        # 3. Veritabanı seçimi
        ctk.CTkLabel(parent, text="3. Oyun Veritabanı", font=("Segoe UI", 13, "bold"), text_color="#00d2d3").pack(anchor="w", pady=(0, 5))

        db_files = [f for f in os.listdir(DATA_DIR) if f.endswith(".db") and f != "translation_cache.db"] if os.path.exists(DATA_DIR) else []
        if db_files:
            combo_db = ctk.CTkComboBox(parent, values=db_files)
            current_db = os.path.basename(s.get("db_path", ""))
            combo_db.set(current_db if current_db in db_files else db_files[0])
            combo_db.pack(fill="x", pady=5)

            def on_db(choice):
                new_path = os.path.join(DATA_DIR, choice)
                self._set_and_save("db_path", new_path)
                self.app.db_manager.reload(new_path)
                messagebox.showinfo("Veritabanı", f"'{choice}' yükleniyor...")
            combo_db.configure(command=on_db)
        else:
            ctk.CTkLabel(parent, text="data/ klasöründe DB dosyası bulunamadı.", text_color="gray").pack(anchor="w")

    # === HAKKINDA ===
    def _page_about(self, parent):
        ctk.CTkLabel(parent, text=APP_NAME, font=("Segoe UI", 24, "bold"), text_color="#00d2d3").pack(pady=(10, 5))
        ctk.CTkLabel(parent, text=f"Sürüm {self.app.__class__.__name__} v2.0", text_color="gray").pack()
        ctk.CTkLabel(parent, text="Gerçek zamanlı oyun altyazı çeviri asistanı.\nPaddleOCR + SQLite DB + Google/Argos/Gemini",
                     text_color="#aaaaaa", justify="center").pack(pady=15)

        stats = self.app.translation_engine.stats_summary()
        learn_count = self.app.auto_learn_db.count
        ctk.CTkLabel(parent, text=f"Oturum İstatistikleri: {stats}", text_color="#6c5ce7").pack(pady=5)
        ctk.CTkLabel(parent, text=f"Otomatik Öğrenilen Çeviriler: {learn_count}", text_color="#2ecc71").pack(pady=2)
