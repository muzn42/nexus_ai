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

# --- CONFIGURATION ---
API_KEY = ""
APP_NAME = "NEXUS AI"
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
    """
    A Canvas-based label that supports text with a stroke (outline) for better readability.
    """
    def __init__(self, master, text="", font_family="Segoe UI", font_size=22, 
                 text_color="#00FF00", stroke_color="#000000", stroke_width=2, **kwargs):
        # Set default background if not provided
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
        
        # Center coordinates
        x = width / 2
        y = height / 2
        
        current_font = (self.font_family, self.font_size, "bold")

        # Draw stroke (multiple offsets)
        if self.stroke_width > 0:
            for dx in range(-self.stroke_width, self.stroke_width + 1):
                for dy in range(-self.stroke_width, self.stroke_width + 1):
                    if dx == 0 and dy == 0: continue
                    self.create_text(x + dx, y + dy, text=self.text, font=current_font, 
                                   fill=self.stroke_color, width=width-20, justify="center")

        # Draw main text
        self.create_text(x, y, text=self.text, font=current_font, 
                       fill=self.text_color, width=width-20, justify="center")

# --- UTILS ---
def select_roi_fullscreen(image_np):
    window_name = "ALAN SECIMI (Onaylamak icin ENTER, Iptal icin C)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
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
        
        w, h = 500, 650
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
        ctk.CTkLabel(main_frame, text="1. Görüntü Kaynağı", font=("Segoe UI", 14, "bold")).pack(pady=(20, 5), padx=20, anchor="w")
        self.combo_source = ctk.CTkComboBox(main_frame, values=["Yükleniyor..."], width=300)
        self.combo_source.set("PC Ekranı")
        self.combo_source.pack(pady=5, padx=20)
        
        threading.Thread(target=self.load_sources, daemon=True).start()

        # Profile Selection
        ctk.CTkLabel(main_frame, text="2. Çeviri Alanı (Profil)", font=("Segoe UI", 14, "bold")).pack(pady=(20, 5), padx=20, anchor="w")
        
        profile_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        profile_frame.pack(fill="x", padx=20)
        
        self.profiles = ConfigManager.load_profiles()
        self.profile_names = ["Yeni Alan Seç (+Kaydet)"] + list(self.profiles.keys())
        
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

    def delete_selected_profile(self):
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
            except:
                cam_idx = 0
        self.app.set_source(source_type, cam_idx)

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
        self.latest_text = "Lütfen Alan Seçimi Yapın 📐"
        
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
        
        # Subtitle Area (Using Custom Canvas for Stroke)
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

        # Layout
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

        buttons = ["Genel", "Görüntü", "Kısayollar", "Algılama"]
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
        self.btn_toggle.pack(side='left', padx=2); self.btn_reselect.pack(side='left', padx=2); self.btn_settings.pack(side='left', padx=2)
        self.status_label.pack(side='left', fill='x', expand=True, padx=10)
        self.btn_minimize.pack(side='right', padx=2); self.btn_exit.pack(side='right', padx=2)

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
        if hasattr(self, 'cap') and self.cap: self.cap.release()
        self.should_exit = True
        self.root.destroy()
        os._exit(0)

    def set_text(self, text): 
        self.latest_text = text
        self.text_canvas.config_text(text=text)

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
            # Use SequenceMatcher for fuzzy comparison
            similarity = difflib.SequenceMatcher(None, text1.strip().lower(), text2.strip().lower()).ratio()
            return similarity > 0.80 # 80% similarity threshold

        while not self.should_exit:
            if not self.is_running or self.roi is None: time.sleep(0.1); continue
            
            # Rate limit checks
            current_time = time.time()
            if current_time - last_check_time < 0.05: # Check every 50ms
                time.sleep(0.01)
                continue
            last_check_time = current_time

            full_frame = self.get_capture_frame()
            if full_frame is None: continue
            x, y, w, h = self.roi
            try:
                if y+h > full_frame.shape[0] or x+w > full_frame.shape[1]: continue 
                subtitle_area = full_frame[y:y+h, x:x+w]
                
                # Pre-processing
                processed_img_for_comparison = None
                if self.smart_filter_enabled.get():
                    gray = cv2.cvtColor(subtitle_area, cv2.COLOR_BGR2GRAY)
                    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
                    processed_img_for_comparison = thresh
                else:
                    processed_img_for_comparison = subtitle_area

                # Direct Change Check (No Stability Delay)
                # If image is different from the last PROCESSED image
                if self.check_difference(previous_processed_img, processed_img_for_comparison, threshold=0.96):
                    
                    previous_processed_img = processed_img_for_comparison
                    
                    compressed_pil = compress_image(subtitle_area)
                    prompt = f"""
                    Bu resimdeki oyun altyazısını {self.target_language} diline çevir.
                    Eğer resimde okunabilir bir altyazı yoksa sadece '{EMPTY_CODE}' yaz.
                    Yorum yapma. Sadece çeviriyi ver.
                    """
                    try:
                        response = model.generate_content([prompt, compressed_pil])
                        translated = response.text.strip()
                        
                        if EMPTY_CODE in translated or not translated:
                            # Don't clear text immediately to avoid flickering, 
                            # only clear if we get NO_TEXT for a sustained period?
                            # For now, let's just clear it as requested behavior might be "hide if no text"
                            # But user complained about "flickering".
                            # Let's keep it simple: if no text, clear.
                            self.set_text("") 
                            last_translated_text = ""
                        else:
                            # Fuzzy Similarity Check
                            if not is_similar_text(translated, last_translated_text):
                                print(f"Gemini: {translated}")
                                self.set_text(translated)
                                last_translated_text = translated
                            else:
                                print(f"Skipped similar: {translated}")

                    except Exception as e:
                        print(f"API Error: {e}")

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
