"""
NEXUS AI v2 — Yapılandırma ve Ayar Yöneticisi
Profil koordinatları ve uygulama ayarlarının kalıcı olarak disk'e
kaydedilip okunmasından sorumlu modül.
"""
import os
import json

# --- YOL YAPISI ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.ico")

APP_NAME = "NEXUS AI"
APP_VERSION = "2.0"

# --- VARSAYILAN AYARLAR ---
DEFAULT_SETTINGS = {
    # Görüntü
    "font_size": 24,
    "font_family": "Segoe UI",
    "text_color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 2,
    "bg_color": "#121212",
    "opacity_mode": "Transparent",    # Transparent / Semi / Opaque

    # Pencere
    "window_geometry": "1000x200+100+100",
    "hide_buttons": False,

    # Çeviri
    "target_language": "Türkçe",
    "fallback_engine": "Google Translate (Ücretsiz)",
    "gemini_api_key": "",
    "db_path": os.path.join(DATA_DIR, "rdr2_ceviri.db"),
    "auto_learn_enabled": True,

    # OCR
    "paddle_version": "PP-OCRv5",
    "use_mkldnn": True,

    # Algılama
    "smart_filter_enabled": False,

    # Kaynak
    "source_type": "screen",
    "camera_index": 0,

    # Kısayollar
    "hotkey_start": "f9",
    "hotkey_reselect": "f10",
    "hotkey_minimal": "f11",
    "hotkey_move": "f8",
    "hotkey_exit": "f12",
}


class ConfigManager:
    """Profil koordinatlarını yönetir (profiles.json)."""

    @staticmethod
    def load_profiles() -> dict:
        if not os.path.exists(PROFILES_FILE):
            return {}
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save_profile(name: str, coords: list):
        data = ConfigManager.load_profiles()
        data[name] = coords
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    @staticmethod
    def delete_profile(name: str):
        data = ConfigManager.load_profiles()
        if name in data:
            del data[name]
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)


class SettingsManager:
    """
    Uygulama ayarlarını yönetir (settings.json).
    Tüm ayarlar program kapandığında kalıcı olarak saklanır.
    """

    @staticmethod
    def load() -> dict:
        settings = DEFAULT_SETTINGS.copy()
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                settings.update(saved)
            except Exception:
                pass

        # Çapraz platform ve dinamik yol çözümleme
        db_p = settings.get("db_path", "")
        if db_p:
            if not os.path.isabs(db_p):
                settings["db_path"] = os.path.normpath(os.path.join(BASE_DIR, db_p))
            elif not os.path.exists(db_p):
                fallback_p = os.path.join(DATA_DIR, os.path.basename(db_p))
                if os.path.exists(fallback_p):
                    settings["db_path"] = fallback_p

        # Ortam değişkeninden API anahtarı desteği (eğer ayarda boşsa)
        if not settings.get("gemini_api_key"):
            settings["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")

        return settings

    @staticmethod
    def save(settings: dict):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        # Sadece varsayılandan farklı olanları kaydet (compact)
        to_save = {}
        for key, value in settings.items():
            if key in DEFAULT_SETTINGS:
                to_save[key] = value
            else:
                to_save[key] = value
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=4)

    @staticmethod
    def get(settings: dict, key: str, fallback=None):
        return settings.get(key, DEFAULT_SETTINGS.get(key, fallback))
