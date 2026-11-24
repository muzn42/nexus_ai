"""
NEXUS AI v2 — Yapılandırma ve Ayar Yöneticisi
Profil koordinatları ve uygulama ayarlarının kalıcı olarak disk'e
kaydedilip okunmasından sorumlu modül.
"""
import os
import sys
import json
import shutil

# --- YOL YAPISI ---
# Geliştirmede (python main.py) her şey depo kökündedir.
# Paketli (PyInstaller) sürümde:
#   BUNDLE_DIR → salt-okunur paket içi (_internal: kod, OCR modelleri)
#   BASE_DIR   → yazılabilir kullanıcı alanı (exe'nin yanı; yazılamıyorsa %APPDATA%\NEXUS AI)
_SEED_DIRS = ("config", "data", "assets", "tools")


def _is_writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".nexus_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _seed_user_dir(src_root: str, dst_root: str):
    """Exe yanındaki varsayılan dosyaları (yoksa) kullanıcı klasörüne kopyalar; mevcutları ezmez."""
    for name in _SEED_DIRS:
        src = os.path.join(src_root, name)
        if not os.path.isdir(src):
            continue
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src_root)
            os.makedirs(os.path.join(dst_root, rel), exist_ok=True)
            for fn in files:
                dst = os.path.join(dst_root, rel, fn)
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(os.path.join(root, fn), dst)
                    except OSError:
                        pass


def _resolve_dirs() -> tuple:
    if not getattr(sys, "frozen", False):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return root, root
    bundle = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    override = os.environ.get("NEXUS_HOME", "").strip()
    if override and _is_writable_dir(override):
        _seed_user_dir(exe_dir, override)
        return override, bundle
    if _is_writable_dir(exe_dir):
        return exe_dir, bundle
    user_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "NEXUS AI")
    os.makedirs(user_dir, exist_ok=True)
    _seed_user_dir(exe_dir, user_dir)
    return user_dir, bundle


BASE_DIR, BUNDLE_DIR = _resolve_dirs()
LOG_DIR = os.path.join(BASE_DIR, "logs")
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
    "bg_opacity": 55,                 # Semi modunda arka plan yüzdesi (0-100)

    # Pencere
    "hud_geometry": "1000x200+100+100",
    "hide_buttons": False,

    # Çeviri
    "target_language": "Türkçe",
    "fallback_engine": "Akıllı Zincir (GPT-OSS → Gemini)",
    "groq_api_key": "",
    "gemini_api_key": "",
    "evren_api_key": "",
    "db_path": os.path.join(DATA_DIR, "rdr2_ceviri.db"),
    "auto_learn_enabled": False,

    # OCR (1: Altyazı hızlı hat · 2: Dünya/menü paralel hat)
    "paddle_version": "PP-OCRv6",
    "ocr_model_size": "small",
    "ocr_device": "gpu",
    "dual_ocr_enabled": True,
    "world_paddle_version": "PP-OCRv6",
    "world_ocr_model_size": "small",
    "world_ocr_device": "cpu",
    "use_mkldnn": True,

    # Algılama
    "smart_filter_enabled": False,

    # Canlı Yama (v3 In-Place)
    "patch_mode": "full_patch",       # full_patch | hybrid | subtitle_only
    "auto_subtitle_detect": True,
    "chameleon_opacity": 78,          # Bukalemun maske opaklığı (%)
    "auto_text_color": True,
    "noise_filter_enabled": True,
    "stabilization_frames": 2,
    "world_scan_interval": 0.55,      # Altyazı dışı dünya/UI tarama aralığı (sn)
    "ocr_max_width_full": 1280,       # Dünya OCR küçültme genişliği (960 → ikon/kutu sınırları kayıyordu)

    # Kaynak
    "source_type": "screen",
    "camera_index": 0,

    # Kısayollar
    "hotkey_mode": "f6",
    "hotkey_freeze": "f7",
    "hotkey_start": "f9",
    "hotkey_reselect": "f10",
    "hotkey_settings": "f11",
    "hotkey_lock": "f8",
    "hotkey_exit": "f12",

    # Görünüm ön ayarı
    "subtitle_preset": "Sinematik",
    "line_spacing": 1.25,
    "max_lines": 3,

    # Hat / ilk kullanım
    "capture_interval": 0.05,
    "onboarding_done": False,
    "last_roi": [],
}


class ConfigManager:
    """Profil koordinatlarını yönetir (profiles.json)."""

    @staticmethod
    def load_profiles() -> dict:
        if not os.path.exists(PROFILES_FILE):
            return {}
        try:
            # utf-8-sig: Windows editörlerinin eklediği BOM'u tolere eder
            with open(PROFILES_FILE, "r", encoding="utf-8-sig") as f:
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
                # utf-8-sig: Windows editörlerinin eklediği BOM'u tolere eder
                # (BOM varsa tüm ayarlar sessizce varsayılana dönerdi)
                with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
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

        # .env dosyası varsa ortam değişkenlerine yükle (API anahtarları için)
        env_file = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8-sig") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and v and not os.environ.get(k):
                            os.environ[k] = v
            except Exception:
                pass

        # Ortam değişkeninden API anahtarı desteği (eğer ayarda boşsa)
        if not settings.get("gemini_api_key"):
            settings["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")
        if not settings.get("groq_api_key"):
            settings["groq_api_key"] = os.environ.get("GROQ_API_KEY", "")
        if not settings.get("evren_api_key"):
            settings["evren_api_key"] = os.environ.get("EVREN_API_KEY", "")

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
