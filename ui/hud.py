"""
NEXUS AI v2 — HUD (Head-Up Display)
Ana uygulama penceresi: Şeffaf overlay, çeviri döngüsü, altyazı geçmişi,
kaynak göstergesi, pencere konumu hatırlama.
"""
import cv2
import numpy as np
import time
import threading
import difflib
from collections import deque
import tkinter as tk
from tkinter import messagebox, simpledialog
import customtkinter as ctk
import keyboard
import os
from PIL import ImageGrab

from core.config_manager import (
    ConfigManager, SettingsManager, LOGO_PATH, APP_NAME, DATA_DIR
)
from core.db_manager import DBManager, AutoLearnDB
from core.ocr_engine import OCREngine
from core.translation_engine import TranslationEngine
from ui.widgets import StrokeLabel, ToolTip
from ui.launcher import StartupScreen, select_roi_fullscreen


class TranslationApp:
    """NEXUS AI v2 Ana Uygulama."""

    def __init__(self):
        # --- Ayarları Yükle ---
        self.settings = SettingsManager.load()
        s = self.settings

        # --- Windows DPI Fix ---
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # --- CustomTkinter Tema ---
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # --- Core Motorları Başlat ---
        self.db_manager = DBManager(s.get("db_path", ""))
        self.auto_learn_db = AutoLearnDB(DATA_DIR)
        self.ocr_engine = OCREngine(
            version=s.get("paddle_version", "PP-OCRv5"),
            use_mkldnn=s.get("use_mkldnn", True)
        )
        self.translation_engine = TranslationEngine(
            db_manager=self.db_manager,
            auto_learn_db=self.auto_learn_db,
            fallback_engine=s.get("fallback_engine", "Google Translate (Ücretsiz)"),
            target_language=s.get("target_language", "Türkçe"),
            gemini_api_key=s.get("gemini_api_key", ""),
            auto_learn_enabled=s.get("auto_learn_enabled", True),
        )

        # --- Ana Pencere (HUD) ---
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title(f"{APP_NAME} HUD")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        try:
            if os.path.exists(LOGO_PATH):
                self.root.iconbitmap(LOGO_PATH)
        except Exception:
            pass

        # Pencere boyutu ve konumu (kayıtlı veya varsayılan)
        geometry = s.get("window_geometry", "1000x200+100+100")
        self.root.geometry(geometry)

        self.root.bind('<Button-1>', self._save_click_pos)
        self.root.bind('<B1-Motion>', self._drag)

        # --- Durum Değişkenleri ---
        self.roi = None
        self.is_running = False
        self.should_exit = False
        self.latest_text = "Lütfen Alan Seçimi Yapın 📐"
        self.source_type = s.get("source_type", "screen")
        self.camera_index = s.get("camera_index", 0)
        self.cap = None

        self.is_recording_key = False
        self.in_move_mode = False
        self.hide_buttons_enabled = s.get("hide_buttons", False)

        # Altyazı Geçmişi
        self.subtitle_history = deque(maxlen=50)
        self.history_index = -1  # -1 = canlı mod

        # --- Arka Plan & Renkler ---
        bg = s.get("bg_color", "#121212")
        self.ghost_color = "#000001"
        self.root.configure(fg_color=bg)

        # --- Control Bar ---
        self.ctrl_frame = ctk.CTkFrame(self.root, height=40, corner_radius=0, fg_color="#222222")
        self.ctrl_frame.pack(fill='x', side='top')
        self.ctrl_frame.bind('<Button-1>', self._save_click_pos)
        self.ctrl_frame.bind('<B1-Motion>', self._drag)

        self.control_buttons = []

        self.btn_toggle = ctk.CTkButton(
            self.ctrl_frame, text="▶", command=self.toggle_translation,
            font=("Arial", 14), fg_color="transparent", text_color='#2ecc71',
            hover_color="#333333", width=40)
        self.btn_toggle.pack(side='left', padx=2)
        ToolTip(self.btn_toggle, "Başlat / Durdur")
        self.control_buttons.append(self.btn_toggle)

        self.btn_reselect = ctk.CTkButton(
            self.ctrl_frame, text="📐", command=self.reselect_area,
            font=("Segoe UI Emoji", 12), fg_color="transparent", text_color='#3498db',
            hover_color="#333333", width=40)
        self.btn_reselect.pack(side='left', padx=2)
        ToolTip(self.btn_reselect, "Alan Seç")
        self.control_buttons.append(self.btn_reselect)

        self.btn_settings = ctk.CTkButton(
            self.ctrl_frame, text="⚙", command=self.open_settings,
            font=("Segoe UI Emoji", 14), fg_color="transparent", text_color='white',
            hover_color="#333333", width=40)
        self.btn_settings.pack(side='left', padx=2)
        ToolTip(self.btn_settings, "Ayarlar")
        self.control_buttons.append(self.btn_settings)

        # Sağ taraf
        self.btn_exit = ctk.CTkButton(
            self.ctrl_frame, text="✕", command=self.close_app,
            font=("Arial", 12, "bold"), fg_color="transparent", text_color='#e74c3c',
            hover_color="#333333", width=40)
        self.btn_exit.pack(side='right', padx=2)
        ToolTip(self.btn_exit, "Çıkış")

        self.btn_minimize = ctk.CTkButton(
            self.ctrl_frame, text="_", command=self._minimize,
            font=("Arial", 12, "bold"), fg_color="transparent", text_color='white',
            hover_color="#333333", width=40)
        self.btn_minimize.pack(side='right', padx=2)
        ToolTip(self.btn_minimize, "Küçült")

        self.status_label = ctk.CTkLabel(
            self.ctrl_frame, text="Bekleniyor...",
            text_color="gray", font=("Segoe UI", 11))
        self.status_label.pack(side='left', fill='x', expand=True, padx=10)
        self.control_buttons.append(self.status_label)
        self.control_buttons.append(self.btn_minimize)
        self.control_buttons.append(self.btn_exit)

        # Kaynak etiketi (HUD sağ alt)
        self.source_label = ctk.CTkLabel(
            self.ctrl_frame, text="",
            text_color="#6c5ce7", font=("Segoe UI", 10, "bold"))
        self.source_label.pack(side='right', padx=8)

        self.btn_help = ctk.CTkButton(
            self.ctrl_frame, text="?", font=("Arial", 12, "bold"),
            fg_color="transparent", text_color='#f39c12', width=30)
        self.update_help_tooltip()

        # --- Metin Canvas ---
        self.text_canvas = StrokeLabel(
            self.root, text=self.latest_text,
            font_family=s.get("font_family", "Segoe UI"),
            font_size=s.get("font_size", 24),
            text_color=s.get("text_color", "#FFFFFF"),
            stroke_color=s.get("stroke_color", "#000000"),
            stroke_width=s.get("stroke_width", 2),
            bg=bg)
        self.text_canvas.pack(expand=True, fill='both', pady=5)
        self.text_canvas.bind('<Button-1>', self._save_click_pos)
        self.text_canvas.bind('<B1-Motion>', self._drag)
        self.text_canvas.bind('<Double-Button-1>', lambda e: self.toggle_minimal_mode())
        self.root.bind('<Double-Button-1>', lambda e: self.toggle_minimal_mode())

        # Fare scroll: Altyazı geçmişinde gezin
        self.text_canvas.bind('<MouseWheel>', self._on_scroll)
        self.root.bind('<MouseWheel>', self._on_scroll)

        # --- Arka Plan Thread'leri ---
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._hotkey_thread.start()

        self._translation_thread = threading.Thread(target=self._translation_loop, daemon=True)
        self._translation_thread.start()

    # ===== PENCERE YÖNETİMİ =====
    def _save_click_pos(self, event):
        self._lastX = event.x
        self._lastY = event.y

    def _drag(self, event):
        x = event.x - self._lastX + self.root.winfo_x()
        y = event.y - self._lastY + self.root.winfo_y()
        self.root.geometry(f"+{x}+{y}")

    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.bind("<Map>", self._on_restore)

    def _on_restore(self, event):
        if self.root.state() == 'normal':
            self.root.overrideredirect(True)
            self.root.unbind("<Map>")

    # ===== KAYNAK AYARI =====
    def set_source(self, source_type, cam_idx=0):
        self.source_type = source_type
        self.camera_index = cam_idx
        self.settings["source_type"] = source_type
        self.settings["camera_index"] = cam_idx
        self.save_settings()
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_capture_frame(self):
        if self.source_type == "screen":
            try:
                shot = ImageGrab.grab()
                return cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
            except Exception:
                return None
        elif self.source_type == "camera":
            if self.cap is None:
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            if not self.cap.isOpened():
                return None
            ret, frame = self.cap.read()
            return frame if ret else None
        return None

    # ===== HUD GÖSTER =====
    def show_hud(self, initial_roi=None):
        self.root.deiconify()
        self.root.lift()
        if initial_roi:
            self.roi = initial_roi
            self.set_text("Profil Yüklendi. Başlatın.")
        elif self.roi is None:
            self.set_text("Lütfen Alan Seçimi Yapın 📐")
        self.apply_visual_settings()

    def start_launcher(self):
        StartupScreen(self)

    # ===== KISAYOLLAR =====
    def _hotkey_loop(self):
        s = self.settings
        while not self.should_exit:
            try:
                if self.is_recording_key:
                    time.sleep(0.2)
                    continue
                if keyboard.is_pressed(s.get("hotkey_start", "f9")):
                    self.root.after(0, self.toggle_translation); time.sleep(0.4)
                elif keyboard.is_pressed(s.get("hotkey_reselect", "f10")):
                    self.root.after(0, self.reselect_area); time.sleep(0.4)
                elif keyboard.is_pressed(s.get("hotkey_minimal", "f11")):
                    self.root.after(0, self.toggle_minimal_mode); time.sleep(0.4)
                elif keyboard.is_pressed(s.get("hotkey_move", "f8")):
                    self.root.after(0, self.toggle_move_mode); time.sleep(0.4)
                elif keyboard.is_pressed(s.get("hotkey_exit", "f12")):
                    self.root.after(0, self.close_app); time.sleep(0.4)
                time.sleep(0.05)
            except Exception:
                time.sleep(1)

    def update_help_tooltip(self):
        s = self.settings
        text = (f"Başlat: {s.get('hotkey_start','f9').upper()}\n"
                f"Alan: {s.get('hotkey_reselect','f10').upper()}\n"
                f"Minimal: {s.get('hotkey_minimal','f11').upper()}\n"
                f"Taşıma: {s.get('hotkey_move','f8').upper()}\n"
                f"Çıkış: {s.get('hotkey_exit','f12').upper()}")
        ToolTip(self.btn_help, text)

    # ===== ALTYAZI GEÇMİŞİ =====
    def _on_scroll(self, event):
        if not self.subtitle_history:
            return
        if event.delta > 0:  # Yukarı scroll = eski altyazılar
            if self.history_index == -1:
                self.history_index = len(self.subtitle_history) - 1
            elif self.history_index > 0:
                self.history_index -= 1
        else:  # Aşağı scroll = yeni altyazılar
            if self.history_index < len(self.subtitle_history) - 1:
                self.history_index += 1
            else:
                self.history_index = -1

        if self.history_index == -1:
            text, source = self.subtitle_history[-1] if self.subtitle_history else ("", "")
            self.status_label.configure(text="Çeviri Aktif", text_color="#00FF00")
        else:
            text, source = self.subtitle_history[self.history_index]
            pos = self.history_index + 1
            total = len(self.subtitle_history)
            self.status_label.configure(text=f"Geçmiş [{pos}/{total}]", text_color="#f39c12")

        self.text_canvas.config_text(text=text)
        self.source_label.configure(text=f"[{source}]" if source else "")

    # ===== GÖRSEL AYARLAR =====
    def apply_visual_settings(self):
        self.toggle_minimal_mode(reapply=True)
        s = self.settings
        self.text_canvas.config_text(
            text_color=s.get("text_color", "#FFFFFF"),
            font_size=s.get("font_size", 24),
            stroke_color=s.get("stroke_color", "#000000"),
            stroke_width=s.get("stroke_width", 2),
        )

    def toggle_move_mode(self):
        self.in_move_mode = not self.in_move_mode
        if self.in_move_mode:
            self.root.attributes("-transparentcolor", "")
            self.root.attributes("-alpha", 0.8)
            self.root.configure(fg_color="#444444")
            self.text_canvas.configure(bg="#444444")
            self.status_label.configure(text="[TAŞIMA MODU] Sürükle — F8 ile çık", text_color="#e67e22")
        else:
            self.apply_visual_settings()
            self.status_label.configure(text="Aktif", text_color="#00FF00")

    def toggle_minimal_mode(self, reapply=False):
        if not reapply:
            self.hide_buttons_enabled = not self.hide_buttons_enabled
            self.settings["hide_buttons"] = self.hide_buttons_enabled
            self.save_settings()
        if self.in_move_mode:
            return

        s = self.settings
        bg = s.get("bg_color", "#121212")
        mode = s.get("opacity_mode", "Transparent")

        if mode == "Transparent":
            self.root.attributes("-transparentcolor", self.ghost_color)
            self.root.configure(fg_color=self.ghost_color)
            self.text_canvas.configure(bg=self.ghost_color)
            if self.hide_buttons_enabled:
                self.ctrl_frame.pack_forget()
                self.btn_help.pack_forget()
            else:
                self.ctrl_frame.configure(fg_color="#222222")
                self.status_label.configure(fg_color="transparent")
                self._restore_buttons()
        else:
            self.root.attributes("-transparentcolor", "")
            self.root.configure(fg_color=bg)
            self.text_canvas.configure(bg=bg)
            alpha = 0.7 if mode == "Semi" else 1.0
            self.root.attributes("-alpha", alpha)
            if self.hide_buttons_enabled:
                self.ctrl_frame.pack_forget()
                self.btn_help.pack_forget()
            else:
                self.ctrl_frame.configure(fg_color="#222222")
                self._restore_buttons()

    def _restore_buttons(self):
        self.ctrl_frame.pack(before=self.text_canvas, fill='x', side='top')
        self.btn_toggle.pack(side='left', padx=2)
        self.btn_reselect.pack(side='left', padx=2)
        self.btn_settings.pack(side='left', padx=2)
        self.status_label.pack(side='left', fill='x', expand=True, padx=10)
        self.source_label.pack(side='right', padx=8)
        self.btn_help.pack(side='right', padx=2)
        self.btn_minimize.pack(side='right', padx=2)
        self.btn_exit.pack(side='right', padx=2)

    # ===== ÇEVİRİ KONTROLÜ =====
    def toggle_translation(self):
        if self.roi is None:
            self.reselect_area()
            return
        if self.is_running:
            self.is_running = False
            self.btn_toggle.configure(text="▶", text_color='#2ecc71')
            self.status_label.configure(text="Duraklatıldı", text_color="yellow")
            self.set_text("Bekleniyor...")
        else:
            self.is_running = True
            self.history_index = -1
            self.btn_toggle.configure(text="■", text_color='#f39c12')
            stats = self.translation_engine.stats_summary()
            self.status_label.configure(text=f"Aktif  •  {stats}", text_color="#00FF00")

    def reselect_area(self):
        self.is_running = False
        self.btn_toggle.configure(text="▶", text_color='#2ecc71')
        self.status_label.configure(text="Alan seçiliyor...", text_color="#3498db")
        self.set_text("")
        self.root.withdraw()
        time.sleep(0.5)
        full_frame = self.get_capture_frame()
        if full_frame is None:
            messagebox.showerror("Hata", "Görüntü kaynağı alınamadı!")
            self.root.deiconify()
            return
        try:
            roi = select_roi_fullscreen(full_frame)
            nx, ny, nw, nh = [int(v) for v in roi]
            if nw > 0 and nh > 0:
                self.roi = (nx, ny, nw, nh)
                save_name = simpledialog.askstring("Profili Kaydet", "Profil Adı:")
                if save_name:
                    ConfigManager.save_profile(save_name, [nx, ny, nw, nh])
                    self.set_text(f"'{save_name}' kaydedildi. Başlatın.")
                else:
                    self.set_text("Alan Seçildi. Başlatın.")
        except Exception:
            pass
        self.root.deiconify()

    # ===== AYARLAR =====
    def open_settings(self):
        from ui.settings_dialog import SettingsDialog
        SettingsDialog(self)

    def save_settings(self):
        # Pencere konumunu kaydet
        try:
            self.settings["window_geometry"] = self.root.geometry()
        except Exception:
            pass
        SettingsManager.save(self.settings)

    # ===== METİN & DURUM =====
    def set_text(self, text, source=""):
        self.latest_text = text
        self.text_canvas.config_text(text=text)
        self.source_label.configure(text=f"[{source}]" if source else "")

    def _update_status(self, text, color="gray"):
        try:
            self.status_label.configure(text=text, text_color=color)
        except Exception:
            pass

    # ===== ANA ÇEVİRİ DÖNGÜSÜ =====
    def _translation_loop(self):
        prev_img = None
        last_check = 0
        last_ocr_text = ""

        def is_similar(t1, t2):
            if not t1 or not t2:
                return False
            return difflib.SequenceMatcher(None, t1.strip().lower(), t2.strip().lower()).ratio() > 0.80

        while not self.should_exit:
            if not self.is_running or self.roi is None:
                time.sleep(0.1)
                continue

            now = time.time()
            if now - last_check < 0.05:
                time.sleep(0.01)
                continue
            last_check = now

            full_frame = self.get_capture_frame()
            if full_frame is None:
                continue

            x, y, w, h = self.roi
            try:
                if y + h > full_frame.shape[0] or x + w > full_frame.shape[1]:
                    continue
                subtitle_area = full_frame[y:y+h, x:x+w]

                # Değişim algılama
                if self.settings.get("smart_filter_enabled", False):
                    gray = cv2.cvtColor(subtitle_area, cv2.COLOR_BGR2GRAY)
                    _, compare_img = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
                else:
                    compare_img = subtitle_area

                if not self._has_changed(prev_img, compare_img):
                    continue
                prev_img = compare_img

                # OCR
                full_text = self.ocr_engine.read_text(subtitle_area)

                if full_text:
                    if not is_similar(full_text, last_ocr_text):
                        last_ocr_text = full_text

                        # Çevir
                        translated, source = self.translation_engine.translate(full_text)

                        # Geçmişe ekle
                        self.subtitle_history.append((translated, source))
                        self.history_index = -1

                        # HUD'a yaz
                        self.root.after(0, lambda t=translated, s=source: self.set_text(t, s))

                        # Status bar güncelle
                        stats = self.translation_engine.stats_summary()
                        self.root.after(0, lambda st=stats: self._update_status(f"Aktif  •  {st}", "#00FF00"))
                else:
                    self.root.after(0, lambda: self.set_text(""))
                    last_ocr_text = ""

            except Exception as e:
                print(f"[Loop] Hata: {e}")

    def _has_changed(self, img1, img2, threshold=0.96):
        if img1 is None or img2 is None:
            return True
        if img1.shape != img2.shape:
            return True
        s1 = cv2.resize(img1, (80, 40))
        s2 = cv2.resize(img2, (80, 40))
        diff = cv2.absdiff(s1, s2)
        return (np.count_nonzero(diff) / s1.size) > (1 - threshold)

    # ===== BAŞLAT / KAPAT =====
    def start(self):
        self.start_launcher()
        self.root.mainloop()

    def close_app(self):
        self.save_settings()
        if hasattr(self, 'cap') and self.cap:
            self.cap.release()
        self.should_exit = True
        self.root.destroy()
        os._exit(0)
