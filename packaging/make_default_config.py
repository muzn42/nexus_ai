"""Dağıtım için temiz config/ klasörü üretir (packaging/build.ps1 çağırır).

Depodaki config/settings.json kullanıcının gerçek API anahtarlarını içerebilir; bu yüzden
ASLA kopyalanmaz. settings.json, core.config_manager.DEFAULT_SETTINGS'ten sıfırdan üretilir
ve anahtar alanları boş olduğu doğrulanır (AGENTS.md değişmez kural 6).

Kullanım: python make_default_config.py <repo> <hedef_config_klasörü>
"""
import json
import os
import shutil
import sys

KEY_FIELDS = ("groq_api_key", "gemini_api_key", "evren_api_key")


def main(repo: str, out_dir: str) -> int:
    sys.path.insert(0, repo)
    from core.config_manager import DEFAULT_SETTINGS

    os.makedirs(out_dir, exist_ok=True)
    settings = dict(DEFAULT_SETTINGS)
    for k in KEY_FIELDS:
        settings[k] = ""
    # Sözlük DB'si varsayılan olarak pakette yok → çeviri AI zinciriyle yapılır.
    # --with-db verilirse göreli yol (SettingsManager.load() BASE_DIR'e göre çözer).
    if "--with-db" in sys.argv:
        settings["db_path"] = "data/" + os.path.basename(settings.get("db_path") or "rdr2_ceviri.db")
    else:
        settings["db_path"] = ""
    settings["onboarding_done"] = False

    path = os.path.join(out_dir, "settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

    # Kullanıcıya özel koordinat profilleri boş gelir
    for name in ("profiles.json", "capture_profiles.json"):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write("{}\n")
    # Sözlük kataloğu (sırsız) aynen kopyalanır
    src_cat = os.path.join(repo, "config", "dictionaries.json")
    if os.path.isfile(src_cat):
        shutil.copy2(src_cat, os.path.join(out_dir, "dictionaries.json"))

    # Güvenlik doğrulaması: üretilen hiçbir dosyada anahtar olmamalı
    with open(path, encoding="utf-8") as f:
        check = json.load(f)
    leaked = [k for k in KEY_FIELDS if check.get(k)]
    if leaked:
        print(f"HATA: settings.json içinde anahtar var: {leaked}")
        return 1
    print(f"Temiz config yazıldı: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
