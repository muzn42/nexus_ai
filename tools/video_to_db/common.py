"""Ortak yardımcılar: proje yolu, anahtar okuma (asla yazdırılmaz), log."""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data")
GTA6_DIR = os.path.join(DATA_DIR, "gta6")
DEFAULT_DB = os.path.join(DATA_DIR, "gta6_ceviri.db")


def gemini_key() -> str:
    from core.config_manager import SettingsManager
    key = (SettingsManager.load().get("gemini_api_key") or "").strip()
    if not key:
        raise SystemExit("gemini_api_key ayarlı değil (config/settings.json veya .env).")
    return key


def log(msg: str):
    print(time.strftime("%H:%M:%S"), msg, flush=True)
