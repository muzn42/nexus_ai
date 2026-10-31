import cv2
import numpy as np
import time
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, colorchooser
import customtkinter as ctk
import google.generativeai as genai
from PIL import Image, ImageTk
import ctypes
import os
import json
import keyboard
from paddleocr import PaddleOCR

# --- CONFIGURATION ---
API_KEY = ""
APP_NAME = "NEXUS AI - LIVE CAPTURE"
LOGO_FILENAME = "logo.ico"
CONFIG_FILE = "capture_profiles.json"
SETTINGS_FILE = "settings.json"

# --- WINDOWS DPI FIX ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

# --- GEMINI SETUP ---
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- THEME ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# --- UTILS ---
class ConfigManager:
    @staticmethod
    def load_profiles():
        if not os.path.exists(CONFIG_FILE): return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}

    @staticmethod
    def save_profile(name, coords):
        data = ConfigManager.load_profiles()
        data[name] = coords
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

    @staticmethod
    def delete_profile(name):
        data = ConfigManager.load_profiles()
        if name in data:
            del data[name]
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

    @staticmethod
    def load_settings():
        defaults = {
            "font_size": 28,
            "text_color": "#f1c40f",
            "bg_color": "#000000",
            "opacity_mode": "Semi", 
            "subtitle_pos_x": 0.5, 
            "subtitle_pos_y": 0.85, 
            "paddle_version": "PP-OCRv5",
            "use_mkldnn": True,
            "hotkey_move": "f8"
        }
        if not os.path.exists(SETTINGS_FILE): return defaults
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                defaults.update(saved)
                return defaults
        except: return defaults

    @staticmethod
    def save_settings(settings):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)

class VideoThread(threading.Thread):
    def __init__(self, source_index=0):
        super().__init__()
        self.source_index = source_index
        self.cap = None
        self.frame = None
        self.running = False
        self.lock = threading.Lock()
        self.connect_camera()

    def connect_camera(self):
        if self.cap: self.cap.release()
        try:
            self.cap = cv2.VideoCapture(self.source_index, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            self.cap.set(cv2.CAP_PROP_FPS, 60)
        except: pass

    def run(self):
        self.running = True
        while self.running:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    with self.lock: self.frame = frame
                else: time.sleep(1)
            else: time.sleep(0.1)
        if self.cap: self.cap.release()

    def get_frame(self):
        with self.lock: return self.frame.copy() if self.frame is not None else None
    
    def stop(self): self.running = False

# --- LIVE PREVIEW FOR SETUP ---
class LivePreviewSelector(ctk.CTkToplevel):
    def __init__(self, parent, source_index, callback_save):
        super().__init__(parent)
        self.title("Alan Seçimi - Kamera Önizleme")
        self.geometry("960x600")
        self.callback_save = callback_save
        self.source_index = source_index
        
        self.video_thread = VideoThread(source_index)
        self.video_thread.start()
        
        self.canvas = tk.Canvas(self, bg="black", cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        self.start_x = self.start_y = 0
        self.cur_x = self.cur_y = 0
        self.selecting = False
        
        self.scale_factor = 1.0
        self.offset_x = self.offset_y = 0
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(10, self.update_frame)
        
        ctk.CTkLabel(self, text="Çevirmek istediğiniz alanı videonun üzerinde çizin.", text_color="yellow").place(x=10, y=10)

    def update_frame(self):
        frame = self.video_thread.get_frame()
        if frame is not None:
            cv_h, cv_w = frame.shape[:2]
            can_w = self.canvas.winfo_width()
            can_h = self.canvas.winfo_height()
            
            if can_w > 1 and can_h > 1:
                scale = min(can_w/cv_w, can_h/cv_h)
                self.scale_factor = scale
                new_w, new_h = int(cv_w * scale), int(cv_h * scale)
                self.offset_x = (can_w - new_w) // 2
                self.offset_y = (can_h - new_h) // 2
                
                img = cv2.resize(frame, (new_w, new_h))
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                self.tk_img = ImageTk.PhotoImage(Image.fromarray(img))
                
                self.canvas.delete("all")
                self.canvas.create_image(can_w//2, can_h//2, image=self.tk_img, anchor="center")
                
                if self.selecting:
                    self.canvas.create_rectangle(self.start_x, self.start_y, self.cur_x, self.cur_y, outline="#e67e22", width=2)
                    
        self.after(20, self.update_frame)

    def on_press(self, event):
        self.selecting = True
        self.start_x = self.cur_x = event.x
        self.start_y = self.cur_y = event.y

    def on_drag(self, event):
        if self.selecting:
            self.cur_x = event.x
            self.cur_y = event.y

    def on_release(self, event):
        self.selecting = False
        x1, x2 = sorted([self.start_x, self.cur_x])
        y1, y2 = sorted([self.start_y, self.cur_y])
        
        w = x2 - x1
        h = y2 - y1
        
        if w > 10 and h > 10:
            roi = (int((x1 - self.offset_x) / self.scale_factor), int((y1 - self.offset_y) / self.scale_factor), 
                   int(w / self.scale_factor), int(h / self.scale_factor))
            roi = tuple(max(0, v) for v in roi)
            
            name = simpledialog.askstring("Kaydet", "Bu profil için bir isim girin:")
            if name:
                self.callback_save(name, roi)
                self.on_close()

    def on_close(self):
        self.video_thread.stop()
        self.destroy()

# --- STARTUP SCREEN ---
class StartupScreen:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title(APP_NAME + " Ayarlar")
        self.settings = ConfigManager.load_settings()
        
        w, h = 550, 400
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        self.root.geometry('%dx%d+%d+%d' % (w, h, (ws/2)-(w/2), (hs/2)-(h/2)))

        ctk.CTkLabel(self.root, text=APP_NAME, font=("Segoe UI", 24, "bold"), text_color="#00d2d3").pack(pady=20)

        ctk.CTkLabel(self.root, text="1. Görüntü Kaynağı (Capture Card)", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=40)
        self.combo_source = ctk.CTkComboBox(self.root, values=["Yükleniyor..."], width=350)
        self.combo_source.pack(pady=5)
        
        ctk.CTkLabel(self.root, text="2. Çeviri Alanı (Profil)", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=40, pady=(15,0))
        prof_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        prof_frame.pack(pady=5)
        
        self.combo_profile = ctk.CTkComboBox(prof_frame, values=[], width=250)
        self.combo_profile.pack(side="left")
        
        ctk.CTkButton(prof_frame, text="+ Yeni", width=60, command=self.open_new_profile_window).pack(side="left", padx=5)
        ctk.CTkButton(prof_frame, text="🗑️", width=30, fg_color="red", command=self.delete_profile).pack(side="left")

        ctk.CTkButton(self.root, text="BAŞLAT", font=("Segoe UI", 16, "bold"), height=50, width=200, 
                      fg_color="#2ecc71", hover_color="#27ae60", command=self.launch_app).pack(pady=30)
        
        self.refresh_sources()
        self.refresh_profiles()
        self.root.mainloop()

    def refresh_sources(self):
        def scan():
            avail = []
            for i in range(5):
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret: avail.append(f"Camera {i}")
                    cap.release()
            if not avail: avail = ["Bulunamadı"]
            self.root.after(0, lambda: self.combo_source.configure(values=avail))
            if avail: self.root.after(0, lambda: self.combo_source.set(avail[0]))
        threading.Thread(target=scan, daemon=True).start()

    def refresh_profiles(self):
        profs = ConfigManager.load_profiles()
        names = list(profs.keys())
        if not names: names = ["Profil Yok"]
        self.combo_profile.configure(values=names)
        self.combo_profile.set(names[0])
        
    def get_selected_source_index(self):
        val = self.combo_source.get()
        try: return int(val.split(" ")[1])
        except: return 0

    def open_new_profile_window(self):
        idx = self.get_selected_source_index()
        LivePreviewSelector(self.root, idx, self.save_profile_callback)

    def save_profile_callback(self, name, roi):
        ConfigManager.save_profile(name, roi)
        self.refresh_profiles()
        self.combo_profile.set(name)
        messagebox.showinfo("Başarılı", f"'{name}' profili kaydedildi.")

    def delete_profile(self):
        val = self.combo_profile.get()
        if val != "Profil Yok" and messagebox.askyesno("Sil", f"'{val}' silinsin mi?"):
            ConfigManager.delete_profile(val)
            self.refresh_profiles()

    def launch_app(self):
        prof_name = self.combo_profile.get()
        profiles = ConfigManager.load_profiles()
        if prof_name not in profiles:
            messagebox.showerror("Hata", "Lütfen geçerli bir profil seçin veya yeni oluşturun.")
            return
        
        # Get values BEFORE destroying root to avoid TclError
        source_idx = self.get_selected_source_index()
        roi = profiles[prof_name]
        
        self.root.destroy()
        TranslationApp(source_idx, roi, self.settings).mainloop()

# --- SETTINGS DIALOG (LIVE) ---
class LiveSettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, current_settings, on_update_callback):
        super().__init__(parent)
        self.title("Canlı - Gelişmiş Ayarlar")
        self.geometry("400x600")
        self.attributes("-topmost", True)
        self.current_settings = current_settings
        self.on_update = on_update_callback
        self.is_recording_key = False

        ctk.CTkLabel(self, text="Görünüm Ayarları", font=("Segoe UI", 16, "bold")).pack(pady=10)
        
        ctk.CTkLabel(self, text="Yazı Boyutu:").pack(anchor="w", padx=10)
        slider_font = ctk.CTkSlider(self, from_=10, to=100, number_of_steps=90, command=self.update_font)
        slider_font.set(current_settings["font_size"])
        slider_font.pack(fill="x", padx=10, pady=5)
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        self.btn_text_color = ctk.CTkButton(btn_frame, text="Yazı Rengi", command=self.pick_text_color, fg_color=current_settings["text_color"])
        self.btn_text_color.pack(side="left", expand=True, padx=2)
        
        self.btn_bg_color = ctk.CTkButton(btn_frame, text="Arka Plan", command=self.pick_bg_color, fg_color=current_settings["bg_color"])
        self.btn_bg_color.pack(side="left", expand=True, padx=2)

        ctk.CTkLabel(self, text="Arka Plan Modu:").pack(anchor="w", padx=10, pady=(10,0))
        self.var_op = tk.StringVar(value=current_settings["opacity_mode"])
        
        def on_mode_change():
            current_settings["opacity_mode"] = self.var_op.get()
            self.on_update(current_settings)
            
        ctk.CTkRadioButton(self, text="Tam Şeffaf (Sadece Yazı)", variable=self.var_op, value="Transparent", command=on_mode_change).pack(anchor="w", padx=20)
        ctk.CTkRadioButton(self, text="Yarı Şeffaf (Koyu Fon)", variable=self.var_op, value="Semi", command=on_mode_change).pack(anchor="w", padx=20)
        ctk.CTkRadioButton(self, text="Opak (Renkli Kutu)", variable=self.var_op, value="Opaque", command=on_mode_change).pack(anchor="w", padx=20)

        ctk.CTkLabel(self, text="Taşıma Kısayolu:", font=("Segoe UI", 12)).pack(anchor="w", padx=10, pady=(20,0))
        self.btn_key = ctk.CTkButton(self, text=current_settings.get("hotkey_move", "f8").upper(), command=self.record_hotkey)
        self.btn_key.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(self, text="* Kısayola basarak 'Taşıma Modu'nu açıp kapatabilirsiniz.", text_color="gray", font=("Segoe UI", 10)).pack()

        ctk.CTkLabel(self, text="OCR Motoru:", font=("Segoe UI", 16, "bold")).pack(pady=10)
        combo_ver = ctk.CTkComboBox(self, values=["PP-OCRv5", "PP-OCRv4"], command=self.update_ocr)
        combo_ver.set(current_settings.get("paddle_version", "PP-OCRv5"))
        combo_ver.pack(fill="x", padx=10, pady=5)
        
        self.var_mkl = tk.BooleanVar(value=current_settings.get("use_mkldnn", True))
        ctk.CTkCheckBox(self, text="MKLDNN Hızlandırma", variable=self.var_mkl, command=self.update_ocr).pack(anchor="w", padx=10, pady=5)

    def update_font(self, val):
        self.current_settings["font_size"] = int(val)
        self.on_update(self.current_settings)

    def pick_text_color(self):
        c = colorchooser.askcolor(color=self.current_settings["text_color"])[1]
        if c: 
            self.current_settings["text_color"] = c
            self.btn_text_color.configure(fg_color=c)
            self.on_update(self.current_settings)

    def pick_bg_color(self):
        c = colorchooser.askcolor(color=self.current_settings["bg_color"])[1]
        if c: 
            self.current_settings["bg_color"] = c
            self.btn_bg_color.configure(fg_color=c)
            self.on_update(self.current_settings)

    def update_ocr(self, _=None):
        self.current_settings["paddle_version"] = _ if isinstance(_, str) else self.current_settings["paddle_version"]
        self.current_settings["use_mkldnn"] = self.var_mkl.get()

    def record_hotkey(self):
        if self.is_recording_key: return
        self.is_recording_key = True
        self.btn_key.configure(text="Tuşa Basın...", fg_color="#e67e22")
        threading.Thread(target=self._wait_key, daemon=True).start()

    def _wait_key(self):
        try:
            k = keyboard.read_hotkey(suppress=False) 
            k = k.lower()
            self.current_settings["hotkey_move"] = k
            self.on_update(self.current_settings) 
            self.after(0, lambda: self.btn_key.configure(text=k.upper(), fg_color="#3a7ebf"))
        except:
            self.after(0, lambda: self.btn_key.configure(text="Hata", fg_color="red"))
        finally:
            self.is_recording_key = False

# --- MAIN PLAYER ---
class TranslationApp(ctk.CTk):
    def __init__(self, source_index, roi, settings):
        super().__init__()
        self.settings = settings
        self.title(APP_NAME + " Player")
        self.geometry("1000x600")
        
        self.source_index = source_index
        self.roi = roi 
        
        self.video_frame = tk.Canvas(self, bg="black", highlightthickness=0)
        self.video_frame.pack(fill="both", expand=True)

        self.btn_settings = ctk.CTkButton(self.video_frame, text="⚙", width=30, height=30, 
                                          fg_color="#333333", hover_color="#555555", 
                                          command=self.open_live_settings)
        self.btn_settings.place(relx=0.96, rely=0.02, anchor="ne")
        
        self.lbl_move_status = ctk.CTkLabel(self.video_frame, text="TAŞIMA MODU AKTİF", text_color="#e67e22", font=("Segoe UI", 14, "bold"), bg_color="black")
        self.lbl_move_status.place(relx=0.5, rely=0.02, anchor="n")
        self.lbl_move_status.place_forget()

        self.subtitle_text = "Çeviri Başlatılıyor..."
        self.move_mode = False
        
        self.drag_data = {"x": 0, "y": 0, "item": None}
        self.video_frame.tag_bind("subtitle", "<ButtonPress-1>", self.on_press)
        self.video_frame.tag_bind("subtitle", "<ButtonRelease-1>", self.on_release)
        self.video_frame.tag_bind("subtitle", "<B1-Motion>", self.on_motion)
        self.video_frame.tag_bind("bg_box", "<ButtonPress-1>", self.on_press)
        self.video_frame.tag_bind("bg_box", "<ButtonRelease-1>", self.on_release)
        self.video_frame.tag_bind("bg_box", "<B1-Motion>", self.on_motion)
        self.video_frame.tag_bind("drag_overlay", "<ButtonPress-1>", self.on_press)
        self.video_frame.tag_bind("drag_overlay", "<ButtonRelease-1>", self.on_release)
        self.video_frame.tag_bind("drag_overlay", "<B1-Motion>", self.on_motion)

        self.bind("<Configure>", self.on_resize)

        self.running = True
        self.video_thread = VideoThread(source_index)
        self.video_thread.start()
        
        # FIX: Init OCR engine BEFORE starting thread
        self.init_ocr_engine()
        
        self.ocr_thread = threading.Thread(target=self.ocr_loop, daemon=True)
        self.ocr_thread.start()
        
        self.after(10, self.update_frame)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.init_hotkeys()

    def init_ocr_engine(self):
        try:
            p_ver = self.settings.get("paddle_version", "PP-OCRv5")
            use_mkl = self.settings.get("use_mkldnn", True)
            
            print(f"Init Paddle: {p_ver}, MKL={use_mkl}")
            if p_ver == "PP-OCRv4":
                self.ocr_engine = PaddleOCR(use_doc_orientation_classify=False,
                                            use_doc_unwarping=False,
                                            use_textline_orientation=False,
                                            lang='en',
                                            ocr_version='PP-OCRv4', 
                                            enable_mkldnn=use_mkl)
            else:
                self.ocr_engine = PaddleOCR(use_doc_orientation_classify=False,
                                            use_doc_unwarping=False,
                                            use_textline_orientation=False,
                                            lang='en',
                                            enable_mkldnn=use_mkl)
        except Exception as e:
            print(f"OCR Init Error: {e}")
            self.ocr_engine = PaddleOCR(lang='en', use_angle_cls=False)

    def init_hotkeys(self):
        hotkey = self.settings.get("hotkey_move", "f8")
        try:
            keyboard.add_hotkey(hotkey, self.toggle_move_mode)
            print(f"Hotkey registered: {hotkey}")
        except: pass

    def toggle_move_mode(self):
        self.move_mode = not self.move_mode
        if self.move_mode:
            self.lbl_move_status.place(relx=0.5, rely=0.02, anchor="n")
        else:
            self.lbl_move_status.place_forget()
        self.after(0, self.draw_subtitle)

    def draw_subtitle(self):
        self.video_frame.delete("subtitle")
        self.video_frame.delete("bg_box")
        self.video_frame.delete("drag_overlay")
        
        if not self.subtitle_text: return
        
        w = self.video_frame.winfo_width()
        h = self.video_frame.winfo_height()
        
        px = self.settings["subtitle_pos_x"] * w
        py = self.settings["subtitle_pos_y"] * h
        
        try: font_spec = ("Arial", self.settings["font_size"], "bold")
        except: font_spec = ("Arial", 28, "bold")
        text_col = self.settings["text_color"]
        mode = self.settings["opacity_mode"]
        
        # Measure
        temp = self.video_frame.create_text(px, py, text=self.subtitle_text, font=font_spec, anchor="center")
        bbox = self.video_frame.bbox(temp)
        self.video_frame.delete(temp)
        
        if bbox:
            pad = 10
            x1, y1, x2, y2 = bbox
            
            # Draw Background logic
            if mode != "Transparent" or self.move_mode:
                if mode == "Opaque":
                    fill_col = self.settings["bg_color"]
                    stipp = "" # Solid
                elif mode == "Semi":
                    fill_col = "black" 
                    stipp = "gray50" 
                else: 
                    fill_col = "" 
                    stipp = ""
                
                if mode == "Transparent":
                    if self.move_mode:
                        self.video_frame.create_rectangle(x1-pad, y1-pad, x2+pad, y2+pad, 
                                                        fill="", outline="#e67e22", width=2, tags="drag_overlay")
                else:
                    self.video_frame.create_rectangle(x1-pad, y1-pad, x2+pad, y2+pad, 
                                                    fill=fill_col, stipple=stipp, outline="", tags="bg_box")
                    
                    if self.move_mode:
                         self.video_frame.create_rectangle(x1-pad, y1-pad, x2+pad, y2+pad, 
                                                        fill="", outline="#e67e22", width=2, tags="drag_overlay")

        # Draw Outline (Stroke)
        stroke_w = 2
        stroke_c = "black"
        for dx in range(-stroke_w, stroke_w+1):
            for dy in range(-stroke_w, stroke_w+1):
                if dx!=0 or dy!=0:
                     self.video_frame.create_text(px+dx, py+dy, text=self.subtitle_text, font=font_spec, fill=stroke_c, anchor="center", tags="subtitle")

        # Draw Main Text
        self.video_frame.create_text(px, py, text=self.subtitle_text, font=font_spec, fill=text_col, anchor="center", tags="subtitle")
        
        self.video_frame.tag_raise("bg_box")
        self.video_frame.tag_raise("subtitle")
        self.video_frame.tag_raise("drag_overlay")
        self.btn_settings.lift()
        self.lbl_move_status.lift()

    def on_press(self, event):
        self.drag_data["item"] = "subtitle" 
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def on_release(self, event):
        self.drag_data["item"] = None
        w = self.video_frame.winfo_width()
        h = self.video_frame.winfo_height()
        items = self.video_frame.find_withtag("subtitle")
        if not items:
             items = self.video_frame.find_withtag("bg_box")
        
        if items and w > 0 and h > 0:
            coords = self.video_frame.coords(items[-1]) 
            if coords:
                self.settings["subtitle_pos_x"] = coords[0] / w
                self.settings["subtitle_pos_y"] = coords[1] / h

    def on_motion(self, event):
        if self.drag_data["item"]:
            dx = event.x - self.drag_data["x"]
            dy = event.y - self.drag_data["y"]
            
            self.video_frame.move("subtitle", dx, dy)
            self.video_frame.move("bg_box", dx, dy)
            self.video_frame.move("drag_overlay", dx, dy)
            
            self.drag_data["x"] = event.x
            self.drag_data["y"] = event.y

    def on_resize(self, event):
        if event.widget == self.video_frame: 
             self.draw_subtitle()

    def open_live_settings(self):
        LiveSettingsDialog(self, self.settings, self.apply_live_settings)

    def apply_live_settings(self, new_settings):
        self.settings = new_settings
        try:
             keyboard.unhook_all_hotkeys()
             keyboard.add_hotkey(new_settings.get("hotkey_move", "f8"), self.toggle_move_mode)
        except: pass
        self.draw_subtitle()

    def update_frame(self):
        try:
            frame = self.video_thread.get_frame()
            if frame is not None:
                cv_h, cv_w = frame.shape[:2]
                can_w = self.video_frame.winfo_width()
                can_h = self.video_frame.winfo_height()
                
                if can_w > 1 and can_h > 1:
                    scale = min(can_w/cv_w, can_h/cv_h)
                    new_w, new_h = int(cv_w * scale), int(cv_h * scale)
                    
                    img = cv2.resize(frame, (new_w, new_h))
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    self.tk_img = ImageTk.PhotoImage(Image.fromarray(img))
                    
                    self.video_frame.delete("vid")
                    self.video_frame.create_image(can_w//2, can_h//2, image=self.tk_img, anchor="center", tags="vid")
                    self.video_frame.tag_lower("vid")
        except: pass
        self.after(20, self.update_frame)

    def ocr_loop(self):
        last_success_text = ""
        while self.running:
            frame = self.video_thread.get_frame()
            if frame is not None:
                x, y, w, h = self.roi
                try:
                    if y+h <= frame.shape[0] and x+w <= frame.shape[1]:
                        roi_img = frame[y:y+h, x:x+w]
                        result = self.ocr_engine.predict(roi_img)
                        full_text = ""
                        if result:
                            for res in result:
                                if hasattr(res, 'json') and 'res' in res.json and 'rec_texts' in res.json['res']:
                                     rec_texts = res.json['res']['rec_texts']
                                     if rec_texts: full_text += " ".join(rec_texts) + " "
                                elif hasattr(res, 'text'): 
                                     full_text += str(res.text) + " "
                        full_text = full_text.strip()
                        
                        if full_text and full_text != last_success_text:
                            try:
                                resp = model.generate_content(f"Translate to Turkish: {full_text}")
                                trans = resp.text.strip()
                                self.subtitle_text = trans
                                self.video_frame.after(0, self.draw_subtitle)
                                last_success_text = full_text
                            except: pass
                        elif not full_text:
                             if self.subtitle_text:
                                 self.subtitle_text = ""
                                 self.video_frame.after(0, self.draw_subtitle)
                except Exception as e: 
                    print(e)
            
            time.sleep(0.5)

    def on_close(self):
        self.running = False
        ConfigManager.save_settings(self.settings)
        try: keyboard.unhook_all_hotkeys()
        except: pass
        self.video_thread.stop()
        self.destroy()
        os._exit(0)

if __name__ == "__main__":
    StartupScreen()
