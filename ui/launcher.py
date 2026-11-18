"""
NEXUS AI v2 — Başlatıcı Ekranı (Launcher)
Modernize edilmiş launcher: DB yükleme durumu progress bar, motor durumu göstergesi.
"""
import os
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from core.config_manager import (
    ConfigManager, SettingsManager, LOGO_PATH, APP_NAME, APP_VERSION, DATA_DIR
)
import cv2


def select_roi_fullscreen(image_np):
    """Tam ekran görüntü üzerinden ROI seçimi."""
    window_name = "ALAN SECIMI (Onaylamak icin ENTER, Iptal icin C)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    roi = cv2.selectROI(window_name, image_np, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    return roi


def list_available_cameras(max_check=3):
    """
    Kamera / capture card portlarını listeler.

    Not: CAP_DSHOW ile port yoklamak Windows'ta her başarısız denemede
    8-20 sn bekleyebiliyor (eski kod açılışı ~42 sn geciktiriyordu).
    Bu yüzden: varsayılan backend kullanılır, ilk boş portta arama kesilir
    ve her port için kısa bir açma denemesi yapılır.
    """
    available_ports = ["PC Ekranı"]
    for i in range(max_check):
        cap = cv2.VideoCapture(i)
        try:
            if not cap.isOpened():
                break  # İlk boş indekste dur — gereksiz 30+ sn beklemeyi önler
            ret, _ = cap.read()
            if ret:
                available_ports.append(f"Kamera / Capture Card (Port {i})")
        except Exception:
            break
        finally:
            cap.release()
    return available_ports


class StartupScreen:
    """Modernize edilmiş NEXUS AI Başlatıcı Penceresi."""

    def __init__(self, app_instance):
        self.app = app_instance
        self.root = ctk.CTkToplevel()
        self.root.deiconify()
        self.root.title(f"{APP_NAME} v{APP_VERSION} Launcher")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        try:
            if os.path.exists(LOGO_PATH):
                self.root.iconbitmap(LOGO_PATH)
        except Exception:
            pass

        w, h = 540, 780
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        self.root.geometry('%dx%d+%d+%d' % (w, h, (ws / 2) - (w / 2), (hs / 2) - (h / 2)))
        self.root.resizable(False, False)
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))

        # ===== HEADER =====
        header_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        header_frame.pack(pady=(20, 5))

        ctk.CTkLabel(
            header_frame, text=APP_NAME,
            font=("Segoe UI", 40, "bold"), text_color="#00d2d3"
        ).pack()
        ctk.CTkLabel(
            header_frame, text=f"HIZLI OYUN ÇEVİRİ ASİSTANI  •  v{APP_VERSION}",
            font=("Segoe UI", 11, "bold"), text_color="#888888"
        ).pack()

        # ===== MOTOR DURUMU =====
        status_frame = ctk.CTkFrame(self.root, fg_color="#1a1a2e", corner_radius=10)
        status_frame.pack(pady=(8, 4), padx=30, fill="x")

        ctk.CTkLabel(
            status_frame, text="Motor Durumu",
            font=("Segoe UI", 11, "bold"), text_color="#6c5ce7"
        ).pack(anchor="w", padx=15, pady=(8, 2))

        # Motor durumlarını kontrol et
        motors_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        motors_frame.pack(fill="x", padx=15, pady=(0, 8))

        self._add_motor_status(motors_frame, "Groq AI (Qwen 27B)", bool(self.app.settings.get("groq_api_key", "")))
        self._add_motor_status(motors_frame, "Gemini AI", bool(self.app.settings.get("gemini_api_key", "")))
        self._add_motor_status(motors_frame, "Google Translate", self._check_deep_translator())
        self._add_motor_status(motors_frame, "Argos Translate", self._check_argos())

        # ===== DB PROGRESS =====
        db_frame = ctk.CTkFrame(self.root, fg_color="#1a1a2e", corner_radius=10)
        db_frame.pack(pady=4, padx=30, fill="x")

        self.db_status_label = ctk.CTkLabel(
            db_frame, text="📂 Veritabanı durumu kontrol ediliyor...",
            font=("Segoe UI", 11), text_color="#aaaaaa"
        )
        self.db_status_label.pack(anchor="w", padx=15, pady=(8, 2))

        self.db_progress = ctk.CTkProgressBar(db_frame, width=400, height=8)
        self.db_progress.set(0)
        self.db_progress.pack(padx=15, pady=(0, 8))

        # DB progress güncelleme
        self._poll_db_progress()

        # ===== ANA İÇERİK =====
        main_frame = ctk.CTkFrame(self.root, corner_radius=12)
        main_frame.pack(pady=8, padx=30, fill="both", expand=True)

        # 1. Kaynak seçimi
        ctk.CTkLabel(
            main_frame, text="1. Görüntü Kaynağı",
            font=("Segoe UI", 13, "bold")
        ).pack(pady=(10, 4), padx=20, anchor="w")

        self.combo_source = ctk.CTkComboBox(main_frame, values=["Yükleniyor..."], width=320)
        self.combo_source.set("PC Ekranı")
        self.combo_source.pack(pady=3, padx=20)
        threading.Thread(target=self._load_sources, daemon=True).start()

        # 2. Oyun seçimi
        ctk.CTkLabel(
            main_frame, text="2. Oyun & Veritabanı",
            font=("Segoe UI", 13, "bold")
        ).pack(pady=(10, 4), padx=20, anchor="w")

        self.game_map = {
            "Red Dead Redemption 2 (Yerel DB)": os.path.join(DATA_DIR, "rdr2_ceviri.db"),
            "Diğer Oyunlar (DB Yok - Doğrudan Yapay Zeka)": "",
        }
        if os.path.exists(DATA_DIR):
            for f in os.listdir(DATA_DIR):
                if f.endswith(".db") and f not in ("translation_cache.db", "nexus_golden.db", "rdr2_ceviri.db"):
                    self.game_map[f"Özel DB: {f}"] = os.path.join(DATA_DIR, f)

        current_db = self.app.settings.get("db_path", "")
        selected_game = "Diğer Oyunlar (DB Yok - Doğrudan Yapay Zeka)"
        if current_db:
            for label, path in self.game_map.items():
                if path and os.path.basename(path) == os.path.basename(current_db):
                    selected_game = label
                    break

        self.combo_game = ctk.CTkComboBox(main_frame, values=list(self.game_map.keys()), width=320)
        self.combo_game.set(selected_game)
        self.combo_game.pack(pady=3, padx=20)

        def on_game_change(choice):
            new_path = self.game_map.get(choice, "")
            self.app.settings["db_path"] = new_path
            SettingsManager.save(self.app.settings)
            self.app.db_manager.reload(new_path)
            self._poll_db_progress()
        self.combo_game.configure(command=on_game_change)

        # 3. Profil seçimi
        ctk.CTkLabel(
            main_frame, text="3. Çeviri Alanı (Profil)",
            font=("Segoe UI", 13, "bold")
        ).pack(pady=(10, 4), padx=20, anchor="w")

        profile_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        profile_frame.pack(fill="x", padx=20)

        self.profiles = ConfigManager.load_profiles()
        self.profile_names = ["Yeni Alan Seç (+Kaydet)"] + list(self.profiles.keys())

        self.combo_profile = ctk.CTkComboBox(profile_frame, values=self.profile_names, width=270)
        self.combo_profile.set(self.profile_names[0])
        self.combo_profile.pack(side="left", fill="x", expand=True)

        self.btn_del = ctk.CTkButton(
            profile_frame, text="🗑️", width=40,
            fg_color="#e74c3c", hover_color="#c0392b",
            command=self._delete_profile
        )
        self.btn_del.pack(side="right", padx=(8, 0))

        # ===== BUTONLAR =====
        btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        btn_frame.pack(pady=(10, 15))

        self.btn_start = ctk.CTkButton(
            btn_frame, text="▶  BAŞLAT", command=self.on_start,
            font=("Segoe UI", 16, "bold"), fg_color='#6c5ce7', hover_color='#5f27cd',
            width=220, height=48, corner_radius=24
        )
        self.btn_start.pack(pady=6)

        self.btn_settings = ctk.CTkButton(
            btn_frame, text="⚙  AYARLAR", command=self.on_settings,
            font=("Segoe UI", 12, "bold"), fg_color='#333333', hover_color='#2d3436',
            width=160, height=35, corner_radius=15
        )
        self.btn_settings.pack(pady=2)

    def _add_motor_status(self, parent, name, available):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=1)
        icon = "✅" if available else "❌"
        color = "#2ecc71" if available else "#e74c3c"
        ctk.CTkLabel(f, text=f"{icon}  {name}", font=("Segoe UI", 11), text_color=color).pack(anchor="w")

    def _check_deep_translator(self):
        try:
            from deep_translator import GoogleTranslator
            return True
        except ImportError:
            return False

    def _check_argos(self):
        try:
            import argostranslate.translate
            return True
        except ImportError:
            return False

    def _poll_db_progress(self):
        """DB yükleme ilerlemesini düzenli kontrol et."""
        db = self.app.db_manager
        if not db.db_path:
            self.db_progress.set(1.0)
            self.db_status_label.configure(
                text="⚡ Doğrudan Yapay Zeka Modu (Yerel DB Yok)",
                text_color="#00d2d3"
            )
            return

        if db.is_loaded:
            self.db_progress.set(1.0)
            self.db_status_label.configure(
                text=f"✅ Veritabanı hazır: {db.entry_count:,} çeviri satırı",
                text_color="#2ecc71"
            )
        else:
            try:
                self.root.after(200, self._poll_db_progress)
            except Exception:
                pass

    def _load_sources(self):
        ports = list_available_cameras()
        try:
            self.combo_source.configure(values=ports)
            self.combo_source.set(ports[0])
        except Exception:
            pass

    def _delete_profile(self):
        selection = self.combo_profile.get()
        if selection == "Yeni Alan Seç (+Kaydet)":
            return
        if messagebox.askyesno("Onay", f"'{selection}' profilini silmek istiyor musunuz?"):
            ConfigManager.delete_profile(selection)
            self.profiles = ConfigManager.load_profiles()
            self.profile_names = ["Yeni Alan Seç (+Kaydet)"] + list(self.profiles.keys())
            self.combo_profile.configure(values=self.profile_names)
            self.combo_profile.set(self.profile_names[0])

    def on_start(self):
        selection_src = self.combo_source.get()
        source_type = "screen"
        cam_idx = 0
        if "PC Ekranı" not in selection_src:
            source_type = "camera"
            try:
                cam_idx = int(selection_src.split("Port ")[1].replace(")", ""))
            except Exception:
                cam_idx = 0
        self.app.set_source(source_type, cam_idx)

        # Oyun ve Veritabanı seçimi kaydet
        game_choice = self.combo_game.get()
        selected_db = self.game_map.get(game_choice, "")
        self.app.settings["db_path"] = selected_db
        SettingsManager.save(self.app.settings)
        if self.app.db_manager.db_path != selected_db:
            self.app.db_manager.reload(selected_db)

        selection_prof = self.combo_profile.get()
        saved_roi = None
        if selection_prof != "Yeni Alan Seç (+Kaydet)":
            saved_roi = tuple(self.profiles[selection_prof])

        self.root.destroy()
        self.app.show_hud(initial_roi=saved_roi)

    def on_settings(self):
        self.app.open_settings()

    def on_close(self):
        self.root.destroy()
        self.app.close_app()
