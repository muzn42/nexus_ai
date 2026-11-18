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
        ctk.CTkLabel(parent, text="Öncelikli: Yerel Veritabanı (Varsa 0 ms, ücretsiz)", text_color="#2ecc71", font=("Segoe UI", 11)).pack(anchor="w", pady=2)

        ctk.CTkLabel(parent, text="Yapay Zeka / Çevirmen:", font=("Segoe UI", 12)).pack(anchor="w", pady=(8, 2))
        engines = ["Akıllı Zincir (GPT-OSS → Gemini)", "Groq AI (Qwen 27B)", "Gemini AI", "Google Translate (Ücretsiz)", "Argos Translate (Çevrimdışı)"]
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

        # Groq API
        ctk.CTkLabel(parent, text="Groq API Anahtarı (Önerilen Hızlı Model):", font=("Segoe UI", 11)).pack(anchor="w", pady=(8, 2))
        entry_groq = ctk.CTkEntry(parent, placeholder_text="gsk_... API Anahtarınızı Yapıştırın...", show="*")
        entry_groq.insert(0, s.get("groq_api_key", ""))
        entry_groq.pack(fill="x", pady=4)

        def save_groq_key():
            k = entry_groq.get().strip()
            self._set_and_save("groq_api_key", k)
            self.app.translation_engine.groq_api_key = k
            self.app.translation_engine._groq_client = None
            messagebox.showinfo("Kaydedildi", "Groq API Anahtarı güncellendi.")
        ctk.CTkButton(parent, text="Groq Anahtarını Kaydet", command=save_groq_key, fg_color="#27ae60", hover_color="#2ecc71", width=140).pack(anchor="e", pady=2)

        # Gemini API
        ctk.CTkLabel(parent, text="Gemini API Anahtarı:", font=("Segoe UI", 11)).pack(anchor="w", pady=(8, 2))
        entry_key = ctk.CTkEntry(parent, placeholder_text="AIzaSy... API Anahtarınızı Yapıştırın...", show="*")
        entry_key.insert(0, s.get("gemini_api_key", ""))
        entry_key.pack(fill="x", pady=4)

        def save_key():
            k = entry_key.get().strip()
            self._set_and_save("gemini_api_key", k)
            self.app.translation_engine.gemini_api_key = k
            self.app.translation_engine._gemini_model = None
            self.app.translation_engine.set_keys(gemini_api_key=k)
            messagebox.showinfo("Kaydedildi", "Gemini API Anahtarı güncellendi.")
        ctk.CTkButton(parent, text="Gemini Anahtarını Kaydet", command=save_key, fg_color="#444444", width=140).pack(anchor="e", pady=2)

        # EVREN AI API
        ctk.CTkLabel(parent, text="EVREN AI API Anahtarı (SSYZ - Milli Yapay Zeka):", font=("Segoe UI", 11)).pack(anchor="w", pady=(8, 2))
        entry_evren = ctk.CTkEntry(parent, placeholder_text="evren_llm_... API Anahtarınızı Yapıştırın...", show="*")
        entry_evren.insert(0, s.get("evren_api_key", ""))
        entry_evren.pack(fill="x", pady=4)

        def save_evren_key():
            k = entry_evren.get().strip()
            self._set_and_save("evren_api_key", k)
            self.app.translation_engine.evren_api_key = k
            self.app.translation_engine.set_keys(evren_api_key=k)
            messagebox.showinfo("Kaydedildi", "EVREN AI API Anahtarı güncellendi.")
        ctk.CTkButton(parent, text="EVREN Anahtarını Kaydet", command=save_evren_key, fg_color="#1e3799", hover_color="#4a69bd", width=160).pack(anchor="e", pady=2)

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=12)

        # 2. OCR
        ctk.CTkLabel(parent, text="2. OCR Ayarları", font=("Segoe UI", 13, "bold"), text_color="#00d2d3").pack(anchor="w", pady=(0, 5))

        ver_labels = {
            "PP-OCRv6": "PP-OCRv6 (Hızlı - Önerilen)",
            "PP-OCRv5": "PP-OCRv5 (Daha Doğru)",
            "PP-OCRv4": "PP-OCRv4 (Daha Hızlı)",
        }
        combo_ver = ctk.CTkComboBox(parent, values=list(ver_labels.values()))
        combo_ver.set(ver_labels.get(s.get("paddle_version"), ver_labels["PP-OCRv5"]))
        combo_ver.pack(fill="x", pady=5)

        def on_ver(choice):
            ver = "PP-OCRv6" if "v6" in choice else ("PP-OCRv5" if "v5" in choice else "PP-OCRv4")
            self._set_and_save("paddle_version", ver)
            self.app.ocr_engine.reset(version=ver)
        combo_ver.configure(command=on_ver)

        # PP-OCRv6 model boyutu (tiny / small / medium)
        size_labels = {
            "tiny": "PP-OCRv6 Tiny (En Hızlı - Temiz Altyazı)",
            "small": "PP-OCRv6 Small (Dengeli - Önerilen)",
            "medium": "PP-OCRv6 Medium (En Doğru - Yavaş)",
        }
        ctk.CTkLabel(parent, text="Model Boyutu (PP-OCRv6):", font=("Segoe UI", 11)).pack(anchor="w", pady=(6, 2))
        combo_size = ctk.CTkComboBox(parent, values=list(size_labels.values()))
        combo_size.set(size_labels.get(s.get("ocr_model_size", "small"), size_labels["small"]))
        combo_size.pack(fill="x", pady=5)

        def on_size(choice):
            size = "tiny" if "Tiny" in choice else ("small" if "Small" in choice else "medium")
            self._set_and_save("ocr_model_size", size)
            self.app.ocr_engine.reset(model_size=size)
        combo_size.configure(command=on_size)

        # İşlem birimi: CPU / GPU
        dev_labels = {
            "cpu": "CPU (MKLDNN hızlandırmalı)",
            "gpu": "GPU (NVIDIA CUDA - paddlepaddle-gpu gerekir)",
        }
        ctk.CTkLabel(parent, text="İşlem Birimi:", font=("Segoe UI", 11)).pack(anchor="w", pady=(6, 2))
        combo_dev = ctk.CTkComboBox(parent, values=list(dev_labels.values()))
        combo_dev.set(dev_labels.get(s.get("ocr_device", "cpu"), dev_labels["cpu"]))
        combo_dev.pack(fill="x", pady=5)

        def on_dev(choice):
            dev = "gpu" if "GPU" in choice else "cpu"
            self._set_and_save("ocr_device", dev)
            self.app.ocr_engine.reset(device=dev)
        combo_dev.configure(command=on_dev)

        var_mk = tk.BooleanVar(value=s.get("use_mkldnn", True))
        ctk.CTkCheckBox(parent, text="CPU Hızlandırma (MKLDNN)", variable=var_mk,
            command=lambda: [self._set_and_save("use_mkldnn", var_mk.get()),
                             self.app.ocr_engine.reset(use_mkldnn=var_mk.get())]
        ).pack(anchor="w", pady=5)

        ctk.CTkLabel(
            parent,
            text=("Not: Paddle 3.3.x'te MKLDNN/PIR hatası var. Kalıcı çözüm:\n"
                  "pip install paddlepaddle==3.2.2"),
            font=("Segoe UI", 10), text_color="#e67e22", justify="left"
        ).pack(anchor="w", pady=(0, 2))

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=12)

        # 3. Oyun & Veritabanı seçimi
        ctk.CTkLabel(parent, text="3. Oyun & Veritabanı Seçimi", font=("Segoe UI", 13, "bold"), text_color="#00d2d3").pack(anchor="w", pady=(0, 5))

        game_map = {
            "Red Dead Redemption 2 (Yerel DB)": os.path.join(DATA_DIR, "rdr2_ceviri.db"),
            "Diğer Oyunlar (DB Yok - Doğrudan Yapay Zeka)": "",
        }
        if os.path.exists(DATA_DIR):
            for f in os.listdir(DATA_DIR):
                if f.endswith(".db") and f not in ("translation_cache.db", "nexus_golden.db", "rdr2_ceviri.db"):
                    game_map[f"Özel DB: {f}"] = os.path.join(DATA_DIR, f)

        current_db = s.get("db_path", "")
        selected_label = "Diğer Oyunlar (DB Yok - Doğrudan Yapay Zeka)"
        if current_db:
            for label, path in game_map.items():
                if path and os.path.basename(path) == os.path.basename(current_db):
                    selected_label = label
                    break

        combo_db = ctk.CTkComboBox(parent, values=list(game_map.keys()))
        combo_db.set(selected_label)
        combo_db.pack(fill="x", pady=5)

        def on_db(choice):
            new_path = game_map.get(choice, "")
            self._set_and_save("db_path", new_path)
            self.app.db_manager.reload(new_path)
            if new_path:
                messagebox.showinfo("Oyun Seçimi", f"'{choice}' yüklendi.")
            else:
                messagebox.showinfo("Oyun Seçimi", "Diğer Oyun modu: Yerel RDR2 veritabanı kapatıldı, doğrudan hızlı yapay zeka kullanılacak.")
        combo_db.configure(command=on_db)

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
