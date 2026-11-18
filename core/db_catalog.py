"""
NEXUS AI — Sözlük (Oyun Veritabanı) Kataloğu

Kullanıcının "Sözlük Kütüphanesi" ekranının arkasındaki mantık:
  - Yerel `data/*.db` dosyalarını otomatik keşfeder ve kaydeder
  - Katalogdan tek tıkla indirir (HTTP, ilerleme bildirimli)
  - Elde olan bir .db dosyasını içe aktarır
  - Şema algılar (translations / golden_translations / özel tablo)
  - iki dilli arama yapar (sözlük içinde arama)

Hiçbir ağ bağlantısı zorunlu değildir: katalog çevrimdışı da çalışır,
yerel dosyalar her zaman önceliklidir.
"""
import json
import os
import shutil
import sqlite3
import threading

from core.config_manager import DATA_DIR, CONFIG_DIR

CATALOG_FILE = os.path.join(CONFIG_DIR, "dictionaries.json")

# Yerel dosyaları asla ezmeyeceğimiz / sözlük saymadığımız dosyalar
_SYSTEM_FILES = {
    "translation_cache.db",   # otomatik öğrenme cache'i
}


# ---------------------------------------------------------------- veri modeli
class Dictionary:
    """Sözlük kataloğundaki tek bir kayıt."""

    def __init__(self, data: dict):
        self.id = str(data.get("id", "")).strip()
        self.game = str(data.get("game", self.id)).strip()
        self.lang_from = str(data.get("lang_from", "en")).strip().lower()
        self.lang_to = str(data.get("lang_to", "tr")).strip().lower()
        self.filename = str(data.get("filename", f"{self.id}.db")).strip()
        self.source_url = str(data.get("source_url", "")).strip()
        self.note = str(data.get("note", "")).strip()
        self.license = str(data.get("license", "")).strip()
        self.version = str(data.get("version", "")).strip()
        self.size_hint = data.get("size_hint", "") or ""

    # --- durum ---
    @property
    def path(self) -> str:
        return os.path.join(DATA_DIR, self.filename)

    def is_installed(self) -> bool:
        return bool(self.filename) and os.path.isfile(self.path)

    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def lang_label(self) -> str:
        return f"{self.lang_from.upper()} → {self.lang_to.upper()}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "game": self.game,
            "lang_from": self.lang_from, "lang_to": self.lang_to,
            "filename": self.filename, "source_url": self.source_url,
            "note": self.note, "license": self.license,
            "version": self.version, "size_hint": self.size_hint,
        }


# ------------------------------------------------------------- şema yardımcı
_KNOWN_GAMES = {
    "rdr2": "Red Dead Redemption 2",
    "golden": "Nexus Golden",
    "oyun": "Genel Oyun Sözlüğü",
}


def _pretty_game_name(stem: str) -> str:
    """
    Dosya adından okunabilir oyun adı üretir.
    Aynı oyunun birden fazla sürümü varsa (rdr2_ceviri, rdr2_ceviri1)
    sürüm eki korunur ama tekrar eden kelimeler temizlenir.
    """
    low = stem.lower()
    # "rdr2_ceviri1" → taban "rdr2", ek "1"
    suffix = ""
    import re
    m = re.match(r"^(.*?)(\d+)$", stem)
    base = stem
    if m:
        base, num = m.group(1), m.group(2)
        suffix = f" ({num})"

    for key, pretty in _KNOWN_GAMES.items():
        if key in base.lower():
            # "ceviri" / "dict" gibi dolgu kelimeleri at
            if pretty == "Nexus Golden":
                return pretty + suffix
            return pretty + suffix

    name = base.replace("_", " ").replace("-", " ").strip()
    return (name.title() if name else stem) + suffix


def inspect_db(path: str) -> dict:
    """
    Bir SQLite sözlüğünü inceler.
    Döner: {"ok": bool, "table": str, "source_col": str, "target_col": str,
            "count": int, "error": str}
    """
    info = {"ok": False, "table": "", "source_col": "", "target_col": "",
            "count": 0, "error": ""}
    if not path or not os.path.isfile(path):
        info["error"] = "Dosya yok"
        return info
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]

        preferred = ["translations", "golden_translations", "dictionary", "entries"]
        ordered = [t for t in preferred if t in tables] + [t for t in tables if t not in preferred]

        for table in ordered:
            cur.execute(f'PRAGMA table_info("{table}")')
            cols = [row[1] for row in cur.fetchall()]
            low = {c.lower(): c for c in cols}
            src = (low.get("source_text") or low.get("source") or low.get("en")
                   or low.get("original") or low.get("key"))
            tgt = (low.get("target_text") or low.get("target") or low.get("tr")
                   or low.get("translation") or low.get("value"))
            if src and tgt:
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = cur.fetchone()[0]
                info.update(ok=True, table=table, source_col=src,
                            target_col=tgt, count=count)
                break
        conn.close()
    except Exception as e:
        info["error"] = str(e)[:120]
    return info


def format_size(num_bytes: int) -> str:
    n = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ------------------------------------------------------------------ kütüphane
class DictionaryLibrary:
    """
    Sözlük kütüphanesi: keşif + katalog + indirme + içe aktarma + arama.
    Tüm ağ işlemleri çağıranın thread'inde yürür; UI tarafı bunu bir
    QThread / worker içinde kullanmalıdır.
    """

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._catalog: list[Dictionary] = []
        self.load_catalog()
        self.scan_local()          # yereldeki dosyaları otomatik kaydet

    # ---------- katalog kalıcılığı ----------
    def load_catalog(self):
        raw = []
        if os.path.isfile(CATALOG_FILE):
            try:
                with open(CATALOG_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                raw = data.get("dictionaries", data if isinstance(data, list) else [])
            except Exception as e:
                print(f"[SÖZLÜK] Katalog okunamadı: {e}")
                raw = []

        self._catalog = [Dictionary(d) for d in raw if d.get("id")]
        # Yinelenen id'leri temizle (son kazanır)
        seen = {}
        for d in self._catalog:
            seen[d.id] = d
        self._catalog = list(seen.values())

    def save_catalog(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        payload = {"version": 1,
                   "dictionaries": [d.to_dict() for d in self._catalog]}
        try:
            with open(CATALOG_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[SÖZLÜK] Katalog yazılamadı: {e}")

    # ---------- sorgular ----------
    def all(self) -> list:
        return list(self._catalog)

    def installed(self) -> list:
        return [d for d in self._catalog if d.is_installed()]

    def get(self, dict_id: str):
        for d in self._catalog:
            if d.id == dict_id:
                return d
        return None

    def find_by_path(self, path: str):
        if not path:
            return None
        base = os.path.basename(path).lower()
        for d in self._catalog:
            if d.filename.lower() == base:
                return d
        return None

    # ---------- yerel keşif ----------
    def scan_local(self) -> list:
        """
        data/ içindeki .db dosyalarını tarar, katalogda olmayanları ekler.
        Döner: yeni eklenen sözlükler.
        """
        added = []
        try:
            names = sorted(os.listdir(DATA_DIR))
        except OSError:
            return added

        known = {d.filename.lower() for d in self._catalog}
        for name in names:
            if not name.lower().endswith(".db"):
                continue
            if name.lower() in _SYSTEM_FILES or name.lower() in known:
                continue
            path = os.path.join(DATA_DIR, name)
            info = inspect_db(path)
            if not info["ok"] or info["count"] == 0:
                continue  # sözlük değil (boş / farklı şema)

            stem = os.path.splitext(name)[0]
            game = _pretty_game_name(stem)

            entry = Dictionary({
                "id": stem, "game": game, "filename": name,
                "lang_from": "en", "lang_to": "tr",
                "note": f"Yerel dosya • {info['count']:,} satır",
            })
            self._catalog.append(entry)
            added.append(entry)

        if added:
            self.save_catalog()
            print(f"[SÖZLÜK] {len(added)} yerel sözlük kataloğa eklendi.")
        return added

    # ---------- indirme ----------
    def download(self, entry, progress_cb=None, cancel_event=None) -> tuple:
        """
        Katalogdaki sözlüğü indirir.
        Döner: (başarılı: bool, mesaj: str)
        """
        if not entry.source_url:
            return False, "Bu kaydın indirme adresi yok. 'Dosyadan Yükle' kullanın."
        tmp = entry.path + ".part"
        try:
            import requests
            with requests.get(entry.source_url, stream=True, timeout=30) as r:
                if r.status_code != 200:
                    return False, f"Sunucu hatası: HTTP {r.status_code}"
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=262144):
                        if cancel_event is not None and cancel_event.is_set():
                            raise RuntimeError("İptal edildi")
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
        except RuntimeError as e:
            _safe_remove(tmp)
            return False, str(e)
        except Exception as e:
            _safe_remove(tmp)
            return False, f"İndirme hatası: {str(e)[:140]}"

        # Doğrula: gerçekten SQLite sözlüğü mü?
        info = inspect_db(tmp)
        if not info["ok"]:
            _safe_remove(tmp)
            return False, "İndirilen dosya geçerli bir sözlük değil."

        os.replace(tmp, entry.path)
        entry.note = f"İndirildi • {info['count']:,} satır"
        self.save_catalog()
        return True, f"{entry.game}: {info['count']:,} satır yüklendi."

    # ---------- içe aktarma ----------
    def import_file(self, src_path: str) -> tuple:
        """
        Kullanıcının seçtiği .db dosyasını kütüphaneye ekler.
        Döner: (başarılı: bool, mesaj: str, sözlük|None)
        """
        if not src_path or not os.path.isfile(src_path):
            return False, "Dosya bulunamadı.", None

        info = inspect_db(src_path)
        if not info["ok"] or info["count"] == 0:
            return False, "Bu dosya geçerli bir sözlük değil (boş veya tanınmayan şema).", None

        name = os.path.basename(src_path)
        stem = os.path.splitext(name)[0]
        dest = os.path.join(DATA_DIR, name)

        existing = self.find_by_path(dest)
        if existing:
            existing.note = f"Yeniden yüklendi • {info['count']:,} satır"
            if os.path.abspath(src_path) != os.path.abspath(dest):
                os.makedirs(DATA_DIR, exist_ok=True)
                shutil.copy2(src_path, dest)
            self.save_catalog()
            return True, f"{existing.game}: {info['count']:,} satır.", existing

        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.abspath(src_path) != os.path.abspath(dest):
            shutil.copy2(src_path, dest)

        game = _pretty_game_name(stem)

        entry = Dictionary({
            "id": stem, "game": game, "filename": name,
            "lang_from": "en", "lang_to": "tr",
            "note": f"İçe aktarıldı • {info['count']:,} satır",
        })
        self._catalog.append(entry)
        self.save_catalog()
        return True, f"{game}: {info['count']:,} satır eklendi.", entry

    # ---------- silme ----------
    def remove(self, dict_id: str, delete_file: bool = False) -> tuple:
        entry = self.get(dict_id)
        if not entry:
            return False, "Kayıt bulunamadı."
        if delete_file and entry.is_installed():
            _safe_remove(entry.path)
        self._catalog = [d for d in self._catalog if d.id != dict_id]
        self.save_catalog()
        return True, f"{entry.game} kütüphaneden çıkarıldı."

    # ---------- sözlük içi arama ----------
    def search(self, db_path: str, query: str, limit: int = 200) -> list:
        """
        Bir sözlük dosyasında iki dilli arama yapar.
        Döner: [(source, target), ...]
        """
        query = (query or "").strip()
        if not query:
            return []
        info = inspect_db(db_path)
        if not info["ok"]:
            return []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            sql = (f'SELECT "{info["source_col"]}", "{info["target_col"]}" '
                   f'FROM "{info["table"]}" '
                   f'WHERE "{info["source_col"]}" LIKE ? OR "{info["target_col"]}" LIKE ? '
                   f'LIMIT ?')
            like = f"%{query}%"
            cur.execute(sql, (like, like, limit))
            rows = [(str(a or ""), str(b or "")) for a, b in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            print(f"[SÖZLÜK] Arama hatası: {e}")
            return []

    def stats(self, db_path: str) -> dict:
        return inspect_db(db_path)


def _safe_remove(path: str):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# ------------------------------------------------------- varsayılan katalog
SEED_CATALOG = {
    "version": 1,
    "dictionaries": [
        {
            "id": "rdr2_ceviri",
            "game": "Red Dead Redemption 2",
            "lang_from": "en", "lang_to": "tr",
            "filename": "rdr2_ceviri.db",
            "source_url": "",
            "note": "RDR2 altyazı sözlüğü",
            "version": "1.0",
        },
        {
            "id": "nexus_golden",
            "game": "Nexus Golden (AI süzülmüş)",
            "lang_from": "en", "lang_to": "tr",
            "filename": "nexus_golden.db",
            "source_url": "",
            "note": "AI ile süzülmüş altın çeviriler",
            "version": "1.0",
        },
    ],
}


def ensure_seed_catalog() -> bool:
    """İlk açılışta katalog dosyası yoksa tohum kataloğu yazar."""
    if os.path.isfile(CATALOG_FILE):
        return False
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        with open(CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump(SEED_CATALOG, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False


