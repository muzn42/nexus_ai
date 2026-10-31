"""
NEXUS AI v2 — Veritabanı Yöneticisi
SQLite çeviri veritabanını yükler, sorgular ve otomatik öğrenme
(auto-learn) özelliği ile online çevirileri yerel DB'ye kaydeder.
"""
import os
import sqlite3
import threading
import difflib


class DBManager:
    """
    Çeviri veritabanını belleğe yükler ve hızlı arama yapar.
    Öncelik: 1. nexus_golden.db (Altın DB), 2. Seçili Oyun DB (rdr2_ceviri.db vb.)
    """

    def __init__(self, db_path: str, on_progress=None):
        self.db_path = db_path
        self.golden_cache = {}    # {source_lower: target_text} (AI Refined Altın DB)
        self.data_cache = {}      # {source_lower: target_text} (Normal DB)
        self.is_loaded = False
        self.entry_count = 0
        self.on_progress = on_progress  # Callback: (loaded, total) -> None
        self.load_thread = threading.Thread(target=self._load_data, daemon=True)
        self.load_thread.start()

    def _load_data(self):
        data_dir = os.path.dirname(self.db_path) if self.db_path else ""
        golden_path = os.path.join(data_dir, "nexus_golden.db")

        # 1. Altın DB varsa yükle (Yapay zeka ile süzülmüş en kaliteli çeviriler)
        if os.path.exists(golden_path):
            try:
                conn_g = sqlite3.connect(golden_path)
                cursor_g = conn_g.cursor()
                cursor_g.execute("SELECT source_text, target_text FROM golden_translations")
                for s, t in cursor_g.fetchall():
                    if s and t:
                        self.golden_cache[s.strip().lower()] = t.strip()
                conn_g.close()
                self.entry_count = len(self.golden_cache)
                self.is_loaded = True
                print(f"[DB] Altın Veritabanı (nexus_golden.db) Yüklendi: {len(self.golden_cache):,} satır.")
            except Exception as e:
                print(f"[DB] Altın DB Yükleme Hatası: {e}")

        # 2. Normal DB Yükle
        if not os.path.exists(self.db_path):
            print(f"[DB] Veritabanı bulunamadı: {self.db_path}")
            self.is_loaded = True
            return

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Toplam satır sayısını öğren (progress bar için)
            cursor.execute("SELECT COUNT(*) FROM translations")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT source_text, target_text FROM translations")
            loaded = 0
            batch_size = 5000

            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for s, t in rows:
                    if s and t:
                        clean_s = s.strip().lower()
                        clean_t = t.strip()

                        # Filtre: Kaynak ve hedef çok benzerse (çevrilmemiş) atla
                        if clean_s == clean_t.lower():
                            continue
                        if difflib.SequenceMatcher(None, clean_s, clean_t.lower()).ratio() > 0.85:
                            continue

                        # Filtre: Hedef hâlâ İngilizce mi?
                        common_eng = {" the ", " is ", " are ", " of ", " to ", " for ",
                                      " with ", " you ", " your ", " they ", " that ",
                                      " this ", " not ", " what ", " where ", " when "}
                        padded = f" {clean_t.lower()} "
                        if any(w in padded for w in common_eng):
                            if not any(c in clean_t for c in "çğıöşüÇĞİÖŞÜ"):
                                continue

                        self.data_cache[clean_s] = clean_t

                loaded += len(rows)
                if self.on_progress and total > 0:
                    self.on_progress(loaded, total)

            conn.close()
            self.entry_count = len(self.golden_cache) + len(self.data_cache)
            self.is_loaded = True
            print(f"[DB] Yüklendi: {len(self.data_cache):,} oyun çeviri satırı.")
        except Exception as e:
            print(f"[DB] Yükleme hatası: {e}")

    def find_translation(self, text: str) -> tuple[str | None, str]:
        """
        Çeviriyi arar.
        Returns: (translated_text, source_tag) -> örn ("Merhaba", "ALTIN") veya ("Merhaba", "DB")
        """
        if not self.is_loaded or not text:
            return None, ""

        search_key = text.strip().lower()

        # 1. Altın DB Tam Eşleşme (NVIDIA AI tarafından süzülmüş)
        if search_key in self.golden_cache:
            return self.golden_cache[search_key], "ALTIN"

        # 2. Oyun DB Tam Eşleşme
        if search_key in self.data_cache:
            return self.data_cache[search_key], "DB"

        # 3. Yakın eşleşme (Altın DB)
        if len(search_key) > 10 and self.golden_cache:
            matches = difflib.get_close_matches(search_key, self.golden_cache.keys(), n=1, cutoff=0.85)
            if matches:
                return self.golden_cache[matches[0]], "ALTIN"

        # 4. Yakın eşleşme (Oyun DB)
        if len(search_key) > 10 and self.data_cache:
            matches = difflib.get_close_matches(search_key, self.data_cache.keys(), n=1, cutoff=0.85)
            if matches:
                return self.data_cache[matches[0]], "DB"

        return None, ""

    def reload(self, new_db_path: str = None, on_progress=None):
        """Yeni bir veritabanı dosyası ile yeniden yükle."""
        if new_db_path:
            self.db_path = new_db_path
        if on_progress:
            self.on_progress = on_progress
        self.data_cache = {}
        self.is_loaded = False
        self.entry_count = 0
        self.load_thread = threading.Thread(target=self._load_data, daemon=True)
        self.load_thread.start()


class AutoLearnDB:
    """
    Online motordan gelen çevirileri yerel SQLite'a kaydeder.
    Böylece aynı cümle tekrar geldiğinde internete gitmeden anında döner.
    'Öğrenen' bir çeviri cache sistemi.
    """

    def __init__(self, data_dir: str):
        self.db_path = os.path.join(data_dir, "translation_cache.db")
        os.makedirs(data_dir, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_translations (
                    source_text TEXT PRIMARY KEY,
                    target_text TEXT,
                    engine TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AutoLearn] DB init hatası: {e}")

    def find(self, text: str) -> str | None:
        """Öğrenilmiş çeviriyi ara."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT target_text FROM learned_translations WHERE source_text = ?",
                (text.strip().lower(),)
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    def save(self, source: str, target: str, engine: str):
        """Yeni çeviriyi kaydet (otomatik öğrenme)."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO learned_translations (source_text, target_text, engine) VALUES (?, ?, ?)",
                (source.strip().lower(), target.strip(), engine)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AutoLearn] Kayıt hatası: {e}")

    @property
    def count(self) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM learned_translations")
            c = cursor.fetchone()[0]
            conn.close()
            return c
        except Exception:
            return 0
