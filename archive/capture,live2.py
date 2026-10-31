import cv2
import numpy as np
import time
import threading
import tkinter as tk
from tkinter import font, messagebox, simpledialog, colorchooser
import customtkinter as ctk
import google.generativeai as genai
from PIL import Image, ImageGrab, ImageTk
import ctypes
import os
import keyboard
import json
import io
import difflib
from paddleocr import PaddleOCR

# --- CONFIGURATION ---
API_KEY = ""
APP_NAME = "NEXUS AI (OCR TEST)"
LOGO_FILENAME = "logo.ico"
CONFIG_FILE = "profiles.json"

# --- WINDOWS DPI FIX ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- THEME SETUP ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# --- CONFIG MANAGER ---
class ConfigManager:
    @staticmethod
    def load_profiles():
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    @staticmethod
    def save_profile(name, coords):
        data = ConfigManager.load_profiles()
        data[name] = coords
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    @staticmethod
    def delete_profile(name):
        data = ConfigManager.load_profiles()
        if name in data:
            del data[name]
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

# --- HELPER CLASSES ---
class ToolTip(object):
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        self.showtip()

    def leave(self, event=None):
        self.hidetip()

    def showtip(self):
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry("+%d+%d" % (x, y))
        tw.attributes("-topmost", True)
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                       background="#333333", foreground="#ffffff",
                       relief=tk.SOLID, borderwidth=1,
                       font=("Segoe UI", 10))
        label.pack(ipadx=5, ipady=2)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

# --- CUSTOM WIDGETS ---
class StrokeLabel(tk.Canvas):
    def __init__(self, master, text="", font_family="Segoe UI", font_size=22, 
                 text_color="#00FF00", stroke_color="#000000", stroke_width=2, **kwargs):
        if "bg" not in kwargs and "background" not in kwargs:
            try:
                kwargs["bg"] = master.cget("bg")
            except:
                kwargs["bg"] = "black"
                
        super().__init__(master, highlightthickness=0, **kwargs)
        self.text = text
        self.font_family = font_family
        self.font_size = font_size
        self.text_color = text_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.text_id = None
        self.stroke_ids = []
        self.bind("<Configure>", self.on_resize)
        self.redraw()

    def config_text(self, text=None, text_color=None, font_size=None):
        if text is not None: self.text = text
        if text_color is not None: self.text_color = text_color
        if font_size is not None: self.font_size = font_size
        self.redraw()

    def on_resize(self, event):
        self.redraw()
    def redraw(self):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        
        x = width / 2
        y = height / 2
        
        current_font = (self.font_family, self.font_size, "bold")

        if self.stroke_width > 0:
            for dx in range(-self.stroke_width, self.stroke_width + 1):
                for dy in range(-self.stroke_width, self.stroke_width + 1):
                    if dx == 0 and dy == 0: continue
                    self.create_text(x + dx, y + dy, text=self.text, font=current_font, 
                                   fill=self.stroke_color, width=width-20, justify="center")

        self.create_text(x, y, text=self.text, font=current_font, 
                       fill=self.text_color, width=width-20, justify="center")

# --- UTILS ---
def select_roi_fullscreen(image_np):
    """Tam ekran pencerede ROI seçimi yaptırır."""
    window_name = "ALAN SECIMI (Onay: ENTER, Iptal: C)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    
    # Görüntüyü göster ve seçim bekle
    roi = cv2.selectROI(window_name, image_np, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    return roi

def list_available_cameras(max_check=3):
    available_ports = ["PC Ekranı"]
    for i in range(max_check):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                available_ports.append(f"Kamera / Capture Card (Port {i})")
            cap.release()
    return available_ports

# --- STARTUP SCREEN ---
class StartupScreen:
    def __init__(self, app_instance):
        self.app = app_instance 
        self.root = ctk.CTkToplevel()
        self.root.title(APP_NAME + " Launcher")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        try:
            if os.path.exists(LOGO_FILENAME):
                self.root.iconbitmap(LOGO_FILENAME)
        except Exception:
            pass
        
        w, h = 550, 700
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        self.root.geometry('%dx%d+%d+%d' % (w, h, (ws/2)-(w/2), (hs/2)-(h/2)))
        self.root.resizable(False, False)

        # Header
        header_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        header_frame.pack(pady=(30, 10))
        
        ctk.CTkLabel(header_frame, text=APP_NAME, font=("Segoe UI", 40, "bold"), text_color="#00d2d3").pack()
        ctk.CTkLabel(header_frame, text="HIZLI OYUN ÇEVİRİ ASİSTANI", font=("Segoe UI", 12, "bold"), text_color="gray").pack()

        # Content
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(pady=20, padx=30, fill="both", expand=True)

        # Source Selection
        ctk.CTkLabel(main_frame, text="1. Görüntü Kaynağı", font=("Segoe UI", 14, "bold")).pack(pady=(15, 5), padx=20, anchor="w")
        self.combo_source = ctk.CTkComboBox(main_frame, values=["Yükleniyor..."], width=350)
        self.combo_source.set("PC Ekranı")
        self.combo_source.pack(pady=5, padx=20)
        
        threading.Thread(target=self.load_sources, daemon=True).start()

        # --- YENİ ALAN SEÇİM BUTONU (LAUNCHER İÇİN) ---
        ctk.CTkLabel(main_frame, text="2. Çeviri Alanı Tanımla", font=("Segoe UI", 14, "bold")).pack(pady=(20, 5), padx=20, anchor="w")
        
        btn_area_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_area_frame.pack(fill="x", padx=20)

        self.btn_define_area = ctk.CTkButton(btn_area_frame, text="📷 Kaynaktan Alan Belirle (+Kaydet)", 
                                           command=self.define_area_from_source,
                                           fg_color="#e67e22", hover_color="#d35400", width=250)
        self.btn_define_area.pack(side="left", fill="x", expand=True)
        # -----------------------------------------------

        # Profile Selection (Existing profiles)
        ctk.CTkLabel(main_frame, text="3. Kayıtlı Profil Seç", font=("Segoe UI", 14, "bold")).pack(pady=(20, 5), padx=20, anchor="w")
        
        profile_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        profile_frame.pack(fill="x", padx=20)
        
        self.profiles = ConfigManager.load_profiles()
        self.profile_names = list(self.profiles.keys())
        if not self.profile_names: self.profile_names = ["Kayıtlı Profil Yok"]

        self.combo_profile = ctk.CTkComboBox(profile_frame, values=self.profile_names, width=250)
        self.combo_profile.set(self.profile_names[0])
        self.combo_profile.pack(side="left", fill="x", expand=True)

        self.btn_del_profile = ctk.CTkButton(profile_frame, text="🗑️", width=40, fg_color="#e74c3c", hover_color="#c0392b", command=self.delete_selected_profile)
        self.btn_del_profile.pack(side="right", padx=(10, 0))

        # Buttons
        btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        btn_frame.pack(pady=30)

        self.btn_start = ctk.CTkButton(btn_frame, text="BAŞLAT", command=self.on_start,
                                     font=("Segoe UI", 16, "bold"), fg_color='#6c5ce7', hover_color='#5f27cd', 
                                     width=200, height=50, corner_radius=25)
        self.btn_start.pack(pady=10)
        
        self.btn_settings = ctk.CTkButton(btn_frame, text="AYARLAR", command=self.on_settings,
                                       font=("Segoe UI", 12, "bold"), fg_color='#444444', hover_color='#2d3436', 
                                       width=150, height=35)
        self.btn_settings.pack(pady=5)

    def load_sources(self):
        ports = list_available_cameras()
        try:
            self.combo_source.configure(values=ports)
            self.combo_source.set(ports[0])
        except:
            pass

    def define_area_from_source(self):
        """Kaynağı geçici olarak açar, tek kare alır ve alan seçtirir."""
        selection_src = self.combo_source.get()
        if selection_src == "Yükleniyor...": return

        # 1. Kaynağı Belirle
        is_camera = "PC Ekranı" not in selection_src
        cam_idx = 0
        if is_camera:
            try: cam_idx = int(selection_src.split("Port ")[1].replace(")", ""))
            except: cam_idx = 0
        
        # 2. Görüntüyü Yakala (Tek Kare)
        frame = None
        
        if not is_camera:
            try:
                screen_shot = ImageGrab.grab()
                screen_np = np.array(screen_shot)
                frame = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)
            except Exception as e:
                messagebox.showerror("Hata", f"Ekran görüntüsü alınamadı: {e}")
                return
        else:
            try:
                cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                
                if not cap.isOpened():
                    messagebox.showerror("Hata", "Kamera açılamadı!")
                    return

                # Capture Card ISINMA TURU (Siyah ekranı önlemek için)
                # İlk 10 kareyi oku ve at
                for _ in range(10):
                    cap.read()
                    time.sleep(0.05)

                # Şimdi gerçek kareyi al
                ret, frame = cap.read()
                cap.release() # Hemen serbest bırak!

                if not ret:
                    messagebox.showerror("Hata", "Kameradan görüntü alınamadı (Sinyal yok mu?)")
                    return
            except Exception as e:
                messagebox.showerror("Hata", f"Kamera hatası: {e}")
                return

        # 3. Alan Seçimi Penceresini Aç
        self.root.withdraw() # Launcher'ı gizle
        try:
            roi = select_roi_fullscreen(frame) # Tam ekran seçim
            nx, ny, nw, nh = [int(v) for v in roi]
            
            if nw > 0 and nh > 0:
                save_name = simpledialog.askstring("Profili Kaydet", "Bu alan için bir isim girin:")
                if save_name:
                    ConfigManager.save_profile(save_name, [nx, ny, nw, nh])
                    # Listeyi güncelle
                    self.profiles = ConfigManager.load_profiles()
                    self.profile_names = list(self.profiles.keys())
                    self.combo_profile.configure(values=self.profile_names)
                    self.combo_profile.set(save_name)
                    messagebox.showinfo("Başarılı", f"'{save_name}' profili seçildi ve kaydedildi.")
            
        except Exception as e:
            messagebox.showerror("Hata", f"Seçim sırasında hata: {e}")
        
        self.root.deiconify() # Launcher'ı geri getir

    def delete_selected_profile(self):
        selection = self.combo_profile.get()
        if selection == "Kayıtlı Profil Yok":
            return
        if messagebox.askyesno("Onay", f"'{selection}' profilini silmek istiyor musunuz?"):
            ConfigManager.delete_profile(selection)
            self.profiles = ConfigManager.load_profiles()
            self.profile_names = list(self.profiles.keys())
            if not self.profile_names: self.profile_names = ["Kayıtlı Profil Yok"]
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
            except:
                cam_idx = 0
        self.app.set_source(source_type, cam_idx)

        selection_prof = self.combo_profile.get()
        saved_roi = None
        if selection_prof != "Kayıtlı Profil Yok" and selection_prof in self.profiles:
            saved_roi = tuple(self.profiles[selection_prof])
        else:
             messagebox.showwarning("Uyarı", "Lütfen bir profil seçin veya yeni alan belirleyin!")
             return

        self.root.destroy()
        self.app.show_hud(initial_roi=saved_roi)

    def on_settings(self):
        self.app.open_settings()

    def on_close(self):
        self.root.destroy()
        self.app.close_app()

# --- PREVIEW WINDOW ---
class PreviewWindow(ctk.CTkToplevel):
    def __init__(self, master_app):
        super().__init__()
        self.app = master_app
        self.title("Canlı Kaynak Önizleme")
        self.geometry("480x270")
        self.attributes("-topmost", True)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.label = tk.Label(self, bg="black", text="Yükleniyor...", fg="white")
        self.label.pack(fill="both", expand=True)
        
    def update_image(self, img_pil):
        try:
            w = self.winfo_width()
            h = self.winfo_height()
            if w < 10 or h < 10: return
            
            img_resized = img_pil.resize((w, h), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(img_resized)
            self.label.configure(image=photo, text="")
            self.label.image = photo 
        except Exception as e:
            pass

    def on_close(self):
        self.app.close_preview()
        self.destroy()

# --- MAIN APPLICATION ---
class TranslationApp:
    def __init__(self, roi_coords=None):
        self.root = ctk.CTk()
        self.root.withdraw() 
        self.root.title(f"{APP_NAME} HUD")
        
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            if os.path.exists(LOGO_FILENAME): self.root.iconbitmap(LOGO_FILENAME)
        except Exception: pass

        self.root.geometry("1000x200+100+100")
        self.root.bind('<Button-1>', self.SaveLastClickPos)
        self.root.bind('<B1-Motion>', self.Dragging)
        
        self.roi = roi_coords 
        self.is_running = False 
        self.should_exit = False
        self.latest_text = "Başlatıldı. 'Başlat' tuşuna basın."
        
        self.source_type = "screen" 
        self.camera_index = 0
        self.cap = None 
        
        # Settings
        self.bg_color = '#121212'  
        self.text_color = '#00FF00'
        self.font_family = "Segoe UI"
        self.font_size = 24
        self.opacity_mode = "Opaque"
        self.ghost_color = "#000001"
        
        self.smart_filter_enabled = tk.BooleanVar(value=False)
        self.hide_buttons_enabled = False 
        self.is_recording_key = False
        self.in_move_mode = False 
        self.target_language = "Türkçe" 

        # Engine Settings
        self.engine_mode = "Gemini" 
        self.paddle_ocr = None
        self.paddle_version = "PP-OCRv5" 
        self.use_mkldnn = True

        # Preview Settings
        self.preview_window_instance = None
        self.current_frame_for_preview = None

        self.hotkey_start = "f9"
        self.hotkey_reselect = "f10"
        self.hotkey_minimal = "f11"
        self.hotkey_move = "f8"
        self.hotkey_exit = "f12"

        self.root.configure(fg_color=self.bg_color) 

        # Control Bar
        self.ctrl_frame = ctk.CTkFrame(self.root, height=40, corner_radius=0, fg_color="#222222")
        self.ctrl_frame.pack(fill='x', side='top')
        self.ctrl_frame.bind('<Button-1>', self.SaveLastClickPos)
        self.ctrl_frame.bind('<B1-Motion>', self.Dragging)

        self.control_buttons = []

        self.btn_toggle = ctk.CTkButton(self.ctrl_frame, text="▶", command=self.toggle_translation, 
                                      font=("Arial", 14), fg_color="transparent", text_color='#2ecc71', 
                                      hover_color="#333333", width=40)
        self.btn_toggle.pack(side='left', padx=2)
        ToolTip(self.btn_toggle, "Çeviriyi Başlat / Durdur") 
        self.control_buttons.append(self.btn_toggle)

        # RE-SELECT BUTTON (Now works even if running, but launcher is safer)
        self.btn_reselect = ctk.CTkButton(self.ctrl_frame, text="📐", command=self.reselect_area, 
                                        font=("Segoe UI Emoji", 12), fg_color="transparent", text_color='#3498db', 
                                        hover_color="#333333", width=40)
        self.btn_reselect.pack(side='left', padx=2)
        ToolTip(self.btn_reselect, "Yeni Çeviri Alanı Seç") 
        self.control_buttons.append(self.btn_reselect)

        self.btn_settings = ctk.CTkButton(self.ctrl_frame, text="⚙", command=self.open_settings, 
                                        font=("Segoe UI Emoji", 14), fg_color="transparent", text_color='white', 
                                        hover_color="#333333", width=40)
        self.btn_settings.pack(side='left', padx=2)
        ToolTip(self.btn_settings, "Ayarlar Menüsü") 
        self.control_buttons.append(self.btn_settings)

        # PREVIEW BUTTON
        self.btn_preview = ctk.CTkButton(self.ctrl_frame, text="👁️", command=self.toggle_preview_window,
                                         font=("Segoe UI Emoji", 14), fg_color="transparent", text_color='#e67e22',
                                         hover_color="#333333", width=40)
        self.btn_preview.pack(side='left', padx=2)
        ToolTip(self.btn_preview, "Canlı Kaynak Önizlemesini Aç/Kapat")
        self.control_buttons.append(self.btn_preview)

        self.btn_exit = ctk.CTkButton(self.ctrl_frame, text="✕", command=self.close_app, 
                                    font=("Arial", 12, "bold"), fg_color="transparent", text_color='#e74c3c', 
                                    hover_color="#333333", width=40)
        self.btn_exit.pack(side='right', padx=2)
        ToolTip(self.btn_exit, "Programdan Çık") 
        
        self.btn_minimize = ctk.CTkButton(self.ctrl_frame, text="_", command=self.minimize_app, 
                                        font=("Arial", 12, "bold"), fg_color="transparent", text_color='white', 
                                        hover_color="#333333", width=40)
        self.btn_minimize.pack(side='right', padx=2)
        ToolTip(self.btn_minimize, "Simge Durumuna Küçült") 

        self.status_label = ctk.CTkLabel(self.ctrl_frame, text=f"Bekleniyor...", text_color="gray", font=("Segoe UI", 12))
        self.status_label.pack(side='left', fill='x', expand=True, padx=10)
        self.control_buttons.append(self.status_label)
        self.control_buttons.append(self.btn_minimize)
        self.control_buttons.append(self.btn_exit)

        self.btn_help = ctk.CTkButton(self.ctrl_frame, text="?", font=("Arial", 12, "bold"), 
                                    fg_color="transparent", text_color='#f39c12', width=30)
        self.update_help_tooltip()
        
        self.text_canvas = StrokeLabel(self.root, text=self.latest_text, 
                                     font_family=self.font_family, font_size=self.font_size,
                                     text_color=self.text_color, bg=self.bg_color)
        self.text_canvas.pack(expand=True, fill='both', pady=5)
        self.text_canvas.bind('<Button-1>', self.SaveLastClickPos) 
        self.text_canvas.bind('<B1-Motion>', self.Dragging)

        # Threads
        self.hotkey_thread = threading.Thread(target=self.hotkey_listener_loop)
        self.hotkey_thread.daemon = True
        self.hotkey_thread.start()

        self.thread = threading.Thread(target=self.translation_loop)
        self.thread.daemon = True
        self.thread.start()

        self.root.after(100, self.update_preview_loop)

    def set_source(self, source_type, cam_idx=0):
        self.source_type = source_type
        self.camera_index = cam_idx
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_capture_frame(self):
        if self.source_type == "screen":
            try:
                screen_shot = ImageGrab.grab()
                screen_np = np.array(screen_shot)
                return cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)
            except: return None
        elif self.source_type == "camera":
            if self.cap is None:
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            if not self.cap.isOpened(): return None
            ret, frame = self.cap.read()
            if ret: return frame
            else: return None
        return None
    
    # --- PREVIEW LOGIC ---
    def toggle_preview_window(self):
        if self.preview_window_instance is None:
            self.preview_window_instance = PreviewWindow(self)
        else:
            self.close_preview()

    def close_preview(self):
        if self.preview_window_instance:
            self.preview_window_instance.destroy()
            self.preview_window_instance = None

    def update_preview_loop(self):
        if self.preview_window_instance and self.current_frame_for_preview is not None:
            try:
                rgb_frame = cv2.cvtColor(self.current_frame_for_preview, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                self.preview_window_instance.update_image(pil_img)
            except Exception:
                pass
        self.root.after(30, self.update_preview_loop)

    def show_hud(self, initial_roi=None):
        self.root.deiconify(); self.root.lift()
        if initial_roi:
            self.roi = initial_roi
            self.set_text(f"Profil Yüklendi. Başlatın.")
        elif self.roi is None:
            self.set_text("Lütfen Alan Seçimi Yapın 📐")

    def start_launcher(self):
        StartupScreen(self)

    def hotkey_listener_loop(self):
        while not self.should_exit:
            try:
                if self.is_recording_key:
                    time.sleep(0.2)
                    continue

                if keyboard.is_pressed(self.hotkey_start):
                    self.root.after(0, self.toggle_translation)
                    time.sleep(0.4) 
                elif keyboard.is_pressed(self.hotkey_reselect):
                    self.root.after(0, self.reselect_area)
                    time.sleep(0.4)
                elif keyboard.is_pressed(self.hotkey_minimal):
                    self.root.after(0, self.toggle_minimal_mode)
                    time.sleep(0.4)
                elif keyboard.is_pressed(self.hotkey_move):
                    self.root.after(0, self.toggle_move_mode)
                    time.sleep(0.4)
                elif keyboard.is_pressed(self.hotkey_exit):
                    self.root.after(0, self.close_app)
                    time.sleep(0.4)
                
                time.sleep(0.05) 
            except Exception:
                time.sleep(1)

    def update_help_tooltip(self):
        help_text = f"Başlat: {self.hotkey_start.upper()}\nAlan: {self.hotkey_reselect.upper()}\nMinimal Mod: {self.hotkey_minimal.upper()}\nTaşıma: {self.hotkey_move.upper()}\nÇıkış: {self.hotkey_exit.upper()}"
        ToolTip(self.btn_help, help_text)
        
    def SaveLastClickPos(self, event): self.lastClickX = event.x; self.lastClickY = event.y
    def Dragging(self, event): x, y = event.x - self.lastClickX + self.root.winfo_x(), event.y - self.lastClickY + self.root.winfo_y(); self.root.geometry("+%s+%s" % (x, y))
    
    def minimize_app(self): 
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.bind("<Map>", self.on_restore)
        
    def on_restore(self, event): 
        if self.root.state() == 'normal': 
            self.root.overrideredirect(True)
            self.root.unbind("<Map>")

    # --- SETTINGS ---
    def open_settings(self):
        sw = ctk.CTkToplevel(self.root)
        sw.title("Ayarlar")
        sw.geometry("700x500")
        sw.attributes("-topmost", True)

        sw.grid_columnconfigure(1, weight=1)
        sw.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(sw, width=200, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        
        content_area = ctk.CTkFrame(sw, corner_radius=0, fg_color="transparent")
        content_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

        def show_frame(page_name):
            for widget in content_area.winfo_children(): widget.destroy()
            ctk.CTkLabel(content_area, text=page_name, font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 20))

            if page_name == "Genel": draw_general_settings(content_area)
            elif page_name == "Görüntü": draw_visual_settings(content_area)
            elif page_name == "Kısayollar": draw_key_settings(content_area)
            elif page_name == "Algılama": draw_detect_settings(content_area)
            elif page_name == "Motor": draw_engine_settings(content_area)

        buttons = ["Genel", "Görüntü", "Kısayollar", "Algılama", "Motor"]
        for btn_text in buttons:
            ctk.CTkButton(sidebar, text=btn_text, command=lambda b=btn_text: show_frame(b),
                        fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                        anchor="w").pack(fill="x", pady=2)

        ctk.CTkLabel(sidebar, text=APP_NAME, font=("Segoe UI", 14, "bold"), text_color="#6c5ce7").pack(side="bottom", pady=20)

        def draw_general_settings(parent):
            ctk.CTkLabel(parent, text="Çeviri Dili:", font=("Arial", 12)).pack(anchor="w")
            langs = {"Türkçe": "tr", "İngilizce": "en", "Almanca": "de", "Fransızca": "fr", "İspanyolca": "es", "Japonca": "ja", "Rusça": "ru"}
            combo_lang = ctk.CTkComboBox(parent, values=list(langs.keys()))
            current_key = [k for k, v in langs.items() if v == self.target_language]
            combo_lang.set(current_key[0] if current_key else "Türkçe")
            combo_lang.pack(fill="x", pady=5)
            def save_lang(event): self.target_language = langs[combo_lang.get()]
            combo_lang.configure(command=save_lang)

            ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=20)

            ctk.CTkLabel(parent, text="Görüntü Kaynağı:", font=("Arial", 12)).pack(anchor="w")
            combo_source = ctk.CTkComboBox(parent, values=["Yükleniyor..."])
            current_display = "PC Ekranı" if self.source_type == "screen" else f"Kamera / Capture Card (Port {self.camera_index})"
            combo_source.set(current_display); combo_source.pack(fill="x", pady=5)

            def update_source_list():
                ports = list_available_cameras()
                self.root.after(0, lambda: combo_source.configure(values=ports))
            threading.Thread(target=update_source_list, daemon=True).start()

            def apply_source():
                selection = combo_source.get()
                if selection == "Yükleniyor...": return
                st = "screen"; idx = 0
                if "PC Ekranı" not in selection:
                    st = "camera"
                    try: idx = int(selection.split("Port ")[1].replace(")", ""))
                    except: idx = 0
                self.set_source(st, idx)
                messagebox.showinfo("Bilgi", "Kaynak değiştirildi. 'Alan Değiştir' ile tekrar seçim yapın.")

            ctk.CTkButton(parent, text="Kaynağı Uygula", command=apply_source, fg_color="#6c5ce7").pack(fill="x", pady=10)

        def draw_visual_settings(parent):
            ctk.CTkLabel(parent, text="Pencere Modu:", font=("Arial", 12)).pack(anchor="w")
            var_op = tk.StringVar(value=self.opacity_mode)
            modes = [("Şeffaf", "Transparent"), ("Yarı Şeffaf", "Semi"), ("Opak", "Opaque")]
            for t, m in modes:
                ctk.CTkRadioButton(parent, text=t, variable=var_op, value=m, command=lambda: [setattr(self, 'opacity_mode', var_op.get()), self.apply_visual_settings()]).pack(anchor="w", pady=2)
            
            ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=10)
            ctk.CTkButton(parent, text="Arka Plan Rengi (Sadece Opak)", command=self.choose_bg_color, fg_color="#555555").pack(fill="x", pady=2)
            ctk.CTkButton(parent, text="Yazı Rengi", command=self.choose_text_color, fg_color="#555555").pack(fill="x", pady=2)
            
            ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=10)
            ctk.CTkLabel(parent, text="Yazı Boyutu:", font=("Arial", 12)).pack(anchor="w")
            
            slider = ctk.CTkSlider(parent, from_=10, to=100, command=lambda v: self.update_font_simple(v))
            slider.set(self.font_size)
            slider.pack(fill="x", pady=5)

        def draw_key_settings(parent):
            ctk.CTkLabel(parent, text="Değiştirmek istediğiniz kısayola tıklayın ve tuşa basın.", text_color="gray").pack(anchor="w", pady=(0,10))
            def create_binder(txt, var_name):
                f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", pady=5)
                ctk.CTkLabel(f, text=txt, width=100, anchor="w").pack(side="left")
                btn = ctk.CTkButton(f, text=getattr(self, var_name).upper(), width=100)
                btn.pack(side="right")
                def record():
                    if self.is_recording_key: return
                    self.is_recording_key = True; btn.configure(text="...", fg_color="#e67e22")
                    threading.Thread(target=lambda: capture_key(btn, var_name), daemon=True).start()
                def capture_key(b, v):
                    try:
                        k = keyboard.read_hotkey(suppress=False)
                        self.root.after(0, lambda: save_key(b, v, k))
                    except:
                        self.root.after(0, lambda: reset_key(b, v))
                def save_key(b, v, k):
                    if k != 'esc': setattr(self, v, k)
                    b.configure(text=getattr(self, v).upper(), fg_color="#3B8ED0"); self.is_recording_key = False; self.update_help_tooltip()
                def reset_key(b, v):
                    b.configure(text=getattr(self, v).upper(), fg_color="#3B8ED0"); self.is_recording_key = False
                btn.configure(command=record)
            create_binder("Başlat/Durdur", "hotkey_start"); create_binder("Alan Seç", "hotkey_reselect")
            create_binder("Minimal Mod", "hotkey_minimal"); create_binder("Taşıma Modu", "hotkey_move"); create_binder("Çıkış", "hotkey_exit")

        def draw_detect_settings(parent):
            ctk.CTkCheckBox(parent, text="Akıllı Filtreleme (Siyah-Beyaz)", variable=self.smart_filter_enabled).pack(anchor="w", pady=10)
            ctk.CTkLabel(parent, text="Açık: Arka plan değişimlerini yoksayar (Önerilen).\nKapalı: Tüm piksel değişimlerini izler (Daha hassas).", text_color="gray", justify="left").pack(anchor="w", padx=20)

        def draw_engine_settings(parent):
            ctk.CTkLabel(parent, text="OCR Motoru:", font=("Arial", 12)).pack(anchor="w")
            combo_engine = ctk.CTkComboBox(parent, values=["Gemini", "PaddleOCR"])
            combo_engine.set(self.engine_mode)
            combo_engine.pack(fill="x", pady=5)
            
            paddle_frame = ctk.CTkFrame(parent, fg_color="transparent")
            
            def update_paddle_visibility(mode):
                if mode == "PaddleOCR":
                    paddle_frame.pack(fill="x", pady=5)
                else:
                    paddle_frame.pack_forget()

            def save_engine(event): 
                self.engine_mode = combo_engine.get()
                update_paddle_visibility(self.engine_mode)
                if self.engine_mode == "PaddleOCR":
                     self.paddle_ocr = None 

            combo_engine.configure(command=save_engine)
            
            ctk.CTkLabel(paddle_frame, text="Paddle Model Sürümü:", font=("Arial", 12)).pack(anchor="w", pady=(5,0))
            combo_version = ctk.CTkComboBox(paddle_frame, values=["PP-OCRv5 (Daha Doğru)", "PP-OCRv4 (Daha Hızlı)"])
            combo_version.set("PP-OCRv5 (Daha Doğru)" if self.paddle_version == "PP-OCRv5" else "PP-OCRv4 (Daha Hızlı)")
            combo_version.pack(fill="x", pady=5)
            
            def save_version(event):
                val = combo_version.get()
                self.paddle_version = "PP-OCRv5" if "v5" in val else "PP-OCRv4"
                self.paddle_ocr = None 
            combo_version.configure(command=save_version)

            var_mkldnn = tk.BooleanVar(value=self.use_mkldnn)
            chk_mkldnn = ctk.CTkCheckBox(paddle_frame, text="CPU Hızlandırma (MKLDNN)", variable=var_mkldnn, 
                                       command=lambda: [setattr(self, 'use_mkldnn', var_mkldnn.get()), setattr(self, 'paddle_ocr', None)])
            chk_mkldnn.pack(anchor="w", pady=5)

            update_paddle_visibility(self.engine_mode)

        show_frame("Genel")

    def update_font_simple(self, size):
        self.font_size = int(size)
        self.text_canvas.config_text(font_size=self.font_size)

    def choose_text_color(self):
        color = colorchooser.askcolor()[1]
        if color: 
            self.text_color = color
            self.text_canvas.config_text(text_color=color)

    def choose_bg_color(self):
        color = colorchooser.askcolor()[1]
        if color:
            self.bg_color = color
            if self.opacity_mode == "Opaque": 
                self.root.configure(fg_color=color)
                self.text_canvas.configure(bg=color)

    def apply_visual_settings(self): self.toggle_minimal_mode(reapply=True)

    def toggle_move_mode(self):
        self.in_move_mode = not self.in_move_mode
        if self.in_move_mode:
            self.root.attributes("-transparentcolor", ""); self.root.attributes("-alpha", 0.8)
            self.root.configure(fg_color="#444444")
            self.text_canvas.configure(bg="#444444")
            self.status_label.configure(text="[TAŞIMA MODU] Sürükle. Çıkmak için F8", text_color="#e67e22")
        else:
            self.apply_visual_settings(); self.status_label.configure(text="Aktif", text_color="#00FF00")

    def toggle_minimal_mode(self, reapply=False):
        if not reapply:
            self.hide_buttons_enabled = not self.hide_buttons_enabled
        
        if self.in_move_mode: return 

        if self.opacity_mode == "Transparent":
            self.root.attributes("-transparentcolor", self.ghost_color)
            self.root.configure(fg_color=self.ghost_color)
            self.text_canvas.configure(bg=self.ghost_color)
            
            if self.hide_buttons_enabled:
                self.ctrl_frame.configure(fg_color=self.ghost_color)
                self.status_label.configure(fg_color=self.ghost_color)
                for btn in self.control_buttons: btn.pack_forget()
                self.btn_help.configure(fg_color=self.ghost_color) 
                self.btn_help.pack(side='right', padx=5)
            else:
                self.ctrl_frame.configure(fg_color="#222222")
                self.status_label.configure(fg_color="transparent")
                self.btn_help.pack_forget()
                self.restore_buttons()

        else:
            self.root.attributes("-transparentcolor", "")
            self.root.configure(fg_color=self.bg_color)
            self.text_canvas.configure(bg=self.bg_color)
            alpha = 0.7 if self.opacity_mode == "Semi" else 1.0
            self.root.attributes("-alpha", alpha)

            if self.hide_buttons_enabled:
                self.ctrl_frame.configure(fg_color=self.bg_color) 
                for btn in self.control_buttons: btn.pack_forget()
                self.btn_help.configure(fg_color=self.bg_color)
                self.btn_help.pack(side='right', padx=5)
            else:
                self.ctrl_frame.configure(fg_color="#222222")
                self.btn_help.pack_forget()
                self.restore_buttons()

    def restore_buttons(self):
        self.btn_toggle.pack(side='left', padx=2)
        self.btn_reselect.pack(side='left', padx=2)
        self.btn_settings.pack(side='left', padx=2)
        self.btn_preview.pack(side='left', padx=2) 
        self.status_label.pack(side='left', fill='x', expand=True, padx=10)
        self.btn_minimize.pack(side='right', padx=2)
        self.btn_exit.pack(side='right', padx=2)

    def toggle_translation(self):
        if self.roi is None: self.reselect_area(); return
        if self.is_running:
            self.is_running = False; self.btn_toggle.configure(text="▶", text_color='#2ecc71')
            self.status_label.configure(text="Duraklatıldı", text_color="yellow"); self.set_text("Bekleniyor...") 
        else:
            self.is_running = True; self.btn_toggle.configure(text="■", text_color='#f39c12')
            self.status_label.configure(text="Çeviri Aktif", text_color="#00FF00")

    def reselect_area(self):
        self.is_running = False; self.btn_toggle.configure(text="▶", text_color='#2ecc71')
        self.status_label.configure(text="Alan seçiliyor...", text_color="#3498db"); self.set_text("")
        self.root.withdraw(); time.sleep(0.5) 
        
        full_frame = None
        if self.current_frame_for_preview is not None:
            full_frame = self.current_frame_for_preview.copy()
        else:
            full_frame = self.get_capture_frame()

        if full_frame is None: messagebox.showerror("Hata", "Görüntü kaynağı alınamadı!"); self.root.deiconify(); return
        try:
            roi = select_roi_fullscreen(full_frame)
            nx, ny, nw, nh = [int(v) for v in roi]
            if nw > 0 and nh > 0: 
                self.roi = (nx, ny, nw, nh); save_name = simpledialog.askstring("Profili Kaydet", "Profil Adı:"); 
                if save_name: ConfigManager.save_profile(save_name, [nx, ny, nw, nh]); self.set_text(f"'{save_name}' kaydedildi. Başlatın.")
                else: self.set_text("Alan Seçildi. Başlatın.")
        except Exception: pass
        self.root.deiconify()

    def start(self):
        self.start_launcher()
        self.root.mainloop()

    def start_launcher(self):
        StartupScreen(self)

    def close_app(self):
        self.close_preview() 
        if hasattr(self, 'cap') and self.cap: self.cap.release()
        self.should_exit = True
        self.root.destroy()
        os._exit(0)

    def set_text(self, text): 
        self.latest_text = text
        self.text_canvas.config_text(text=text)

    def translate_with_gemini(self, text):
        if not text: return ""
        try:
            prompt = f"""
            Translate the following text to Turkish.
            Only provide the translation.
            Text: {text}
            """
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Translation Error: {e}")
            return text 

    def translation_loop(self):
        previous_processed_img = None
        last_check_time = 0
        EMPTY_CODE = "[[NO_TEXT]]"
        
        last_translated_text = ""

        def compress_image(cv2_img):
            height, width = cv2_img.shape[:2]
            if height > 360:
                scale = 360 / height
                new_width = int(width * scale)
                cv2_img = cv2.resize(cv2_img, (new_width, 360), interpolation=cv2.INTER_AREA)
            success, encoded_img = cv2.imencode('.jpg', cv2_img, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            return Image.open(io.BytesIO(encoded_img))
            
        def is_similar_text(text1, text2):
            if not text1 or not text2: return False
            similarity = difflib.SequenceMatcher(None, text1.strip().lower(), text2.strip().lower()).ratio()
            return similarity > 0.80 

        while not self.should_exit:
            
            # --- ALWAYS CAPTURE FRAME FOR PREVIEW ---
            full_frame = self.get_capture_frame()
            if full_frame is not None:
                self.current_frame_for_preview = full_frame.copy() 
            
            if not self.is_running or self.roi is None: 
                time.sleep(0.03) 
                continue
            
            current_time = time.time()
            if current_time - last_check_time < 0.05: 
                time.sleep(0.01)
                continue
            last_check_time = current_time

            if full_frame is None: continue
            
            x, y, w, h = self.roi
            try:
                if y+h > full_frame.shape[0] or x+w > full_frame.shape[1]: continue 
                subtitle_area = full_frame[y:y+h, x:x+w]
                
                processed_img_for_comparison = None
                if self.smart_filter_enabled.get():
                    gray = cv2.cvtColor(subtitle_area, cv2.COLOR_BGR2GRAY)
                    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
                    processed_img_for_comparison = thresh
                else:
                    processed_img_for_comparison = subtitle_area

                if self.check_difference(previous_processed_img, processed_img_for_comparison, threshold=0.96):
                    
                    previous_processed_img = processed_img_for_comparison
                    
                    if self.engine_mode == "Gemini":
                        compressed_pil = compress_image(subtitle_area)
                        prompt = f"""
                        Bu resimdeki metni olduğu gibi oku.
                        Çeviri yapma. Sadece metni yaz.
                        Eğer resimde okunabilir bir metin yoksa sadece '{EMPTY_CODE}' yaz.
                        """
                        try:
                            response = model.generate_content([prompt, compressed_pil])
                            translated = response.text.strip()
                            
                            if EMPTY_CODE in translated or not translated:
                                self.set_text("") 
                                last_translated_text = ""
                            else:
                                if not is_similar_text(translated, last_translated_text):
                                    print(f"Detected: {translated}")
                                    self.set_text(translated)
                                    last_translated_text = translated
                                else:
                                    pass
                        except Exception as e:
                            print(f"Gemini Error: {e}")

                    elif self.engine_mode == "PaddleOCR":
                        if self.paddle_ocr is None:
                             ocr_ver = 'PP-OCRv4' if self.paddle_version == "PP-OCRv4" else 'PP-OCRv5'
                             print(f"Initializing PaddleOCR: {self.paddle_version}, MKLDNN={self.use_mkldnn}")
                             try:
                                 if self.paddle_version == "PP-OCRv4":
                                     self.paddle_ocr = PaddleOCR(
                                        use_doc_orientation_classify=False,
                                        use_doc_unwarping=False,
                                        use_textline_orientation=False,
                                        lang='en',
                                        ocr_version='PP-OCRv4',
                                        enable_mkldnn=self.use_mkldnn
                                     )
                                 else:
                                     self.paddle_ocr = PaddleOCR(
                                        use_doc_orientation_classify=False,
                                        use_doc_unwarping=False,
                                        use_textline_orientation=False,
                                        lang='en',
                                        enable_mkldnn=self.use_mkldnn
                                     )
                             except Exception as e:
                                 print(f"Init Error: {e}")
                                 self.paddle_ocr = PaddleOCR(use_angle_cls=False, lang='en') 
                        
                        try:
                            result = self.paddle_ocr.predict(subtitle_area)
                            full_text = ""
                            if result:
                                for res in result:
                                    if hasattr(res, 'json') and 'res' in res.json and 'rec_texts' in res.json['res']:
                                        rec_texts = res.json['res']['rec_texts']
                                        if rec_texts:
                                            full_text += " ".join(rec_texts) + " "
                            
                            full_text = full_text.strip()
                            
                            if full_text:
                                if not is_similar_text(full_text, last_translated_text):
                                    print(f"Paddle Detected (Raw): {full_text}")
                                    translated_text = self.translate_with_gemini(full_text)
                                    print(f"Translated: {translated_text}")
                                    self.set_text(translated_text)
                                    last_translated_text = full_text 
                            else:
                                self.set_text("")
                                last_translated_text = ""

                        except Exception as e:
                            print(f"Paddle Error: {e}")


            except Exception: pass
    
    def check_difference(self, img1, img2, threshold=0.98):
        if img1 is None or img2 is None: return True
        if img1.shape != img2.shape: return True
        small1 = cv2.resize(img1, (80, 40)); small2 = cv2.resize(img2, (80, 40))
        diff = cv2.absdiff(small1, small2); non_zero_count = np.count_nonzero(diff)
        return (non_zero_count / small1.size) > (1 - threshold)

def main():
    app = TranslationApp(roi_coords=None); app.start()

if __name__ == "__main__":
    main()