"""
NEXUS AI v3 — Veritabanı Yöneticisi
SQLite çeviri veritabanını yükler, O(1) normalize hash + kelime kovası indeksiyle
milisaniye altı (<1.5 ms) sorgular ve otomatik öğrenme ile yerel DB'ye kaydeder.
"""
import difflib
import html
import os
import re
import sqlite3
import threading
from collections import Counter, defaultdict

_TAG_RE = re.compile(r"^~:[^~]+~")
_LEAD_ARROW_RE = re.compile(r"^[>\s]+")
_NORM_RE = re.compile(r"[^a-z0-9çğıöşü\s]")
_COMMON_ENG = {
    " the ", " is ", " are ", " of ", " to ", " for ",
    " with ", " you ", " your ", " they ", " that ",
    " this ", " not ", " what ", " where ", " when ",
}
_STOPWORDS = {
    "the", "and", "you", "your", "for", "that", "this", "with", "have",
    "are", "was", "not", "but", "what", "here", "there", "just", "from",
}


def _strip_tag(s: str) -> str:
    return _TAG_RE.sub("", (s or "").strip()).strip()


def _clean_target(t: str) -> str:
    t = html.unescape(_strip_tag(t))
    return _LEAD_ARROW_RE.sub("", t).strip()


def _is_valid_translation(clean_s: str, clean_t: str) -> bool:
    """Çevrilmemiş veya hâlâ İngilizce kalmış satırları hızlıca eler."""
    if not clean_s or not clean_t:
        return False
    low_t = clean_t.lower()
    if clean_s == low_t:
        return False
    s_words = clean_s.split()
    if len(s_words) >= 3:
        t_words = set(low_t.split())
        if sum(1 for w in s_words if w in t_words) / float(len(s_words)) > 0.85:
            return False
    padded = f" {low_t} "
    if any(w in padded for w in _COMMON_ENG):
        if not any(c in clean_t for c in "çğıöşüÇĞİÖŞÜ"):
            return False
    return True


def _normalize(s: str) -> str:
    s = _TAG_RE.sub("", (s or "").strip().lower())
    return " ".join(_NORM_RE.sub(" ", s).split())


def _index_words(norm_s: str) -> list[str]:
    words = [w for w in norm_s.split() if len(w) >= 4 and w not in _STOPWORDS]
    if not words:
        words = [w for w in norm_s.split() if len(w) >= 3]
    # En ayırt edici en fazla 3 uzun kelimeyi indeksle (bellek & hız dengesi)
    words.sort(key=len, reverse=True)
    seen = []
    for w in words:
        if w not in seen:
            seen.append(w)
            if len(seen) >= 3:
                break
    return seen


class DBManager:
    """
    Çeviri veritabanını belleğe yükler ve O(1) + hızlı indeksli arama yapar.
    Öncelik: 1. nexus_golden.db (Altın DB), 2. Seçili Oyun DB (rdr2_ceviri.db vb.)
    """

    def __init__(self, db_path: str, on_progress=None):
        self.db_path = db_path
        self.golden_cache = {}
        self.data_cache = {}
        self._golden_norm = {}
        self._data_norm = {}
        self._word_index = {}  # word -> list[(norm_s, target_t, tag)]
        self.is_loaded = False
        self.entry_count = 0
        self.on_progress = on_progress
        self._load_seq = 0
        self.load_thread = threading.Thread(target=self._load_data, args=(self._load_seq,), daemon=True)
        self.load_thread.start()

    def _load_data(self, seq: int = 0):
        # Eğer DB seçilmediyse veya boşsa doğrudan AI modunda çalış
        if not self.db_path or self.db_path.lower() in ("none", "yok", "db_yok", ""):
            self.golden_cache = {}
            self.data_cache = {}
            self._golden_norm = {}
            self._data_norm = {}
            self._word_index = {}
            self.entry_count = 0
            self.is_loaded = True
            print("[DB] Oyun veritabanı devre dışı (Doğrudan Yapay Zeka modu aktif).")
            return

        data_dir = os.path.dirname(self.db_path) if self.db_path else ""
        golden_path = os.path.join(data_dir, "nexus_golden.db")

        local_golden = {}
        local_golden_norm = {}
        local_data = {}
        local_data_norm = {}
        local_index = defaultdict(list)

        # 1. Altın DB varsa yükle (Yalnızca RDR2 için geçerli)
        is_rdr2 = "rdr2" in os.path.basename(self.db_path).lower()
        if is_rdr2 and os.path.exists(golden_path):
            try:
                conn_g = sqlite3.connect(golden_path)
                cursor_g = conn_g.cursor()
                cursor_g.execute("SELECT source_text, target_text FROM golden_translations")
                for s, t in cursor_g.fetchall():
                    if seq != self._load_seq:
                        conn_g.close()
                        return
                    if s and t:
                        cs = _strip_tag(s).lower()
                        ct = _clean_target(t)
                        if not _is_valid_translation(cs, ct):
                            continue
                        local_golden[cs] = ct
                        ns = _normalize(cs)
                        if ns and ns not in local_golden_norm:
                            local_golden_norm[ns] = ct
                            if len(ns) > 10:
                                for w in _index_words(ns):
                                    local_index[w].append((ns, ct, "ALTIN"))
                conn_g.close()
                # Altın DB'yi atomik olarak yayınla
                self.golden_cache = local_golden
                self._golden_norm = local_golden_norm
                self._word_index = dict(local_index)
                self.entry_count = len(local_golden)
                self.is_loaded = True
                print(f"[DB] Altın Veritabanı (nexus_golden.db) Yüklendi: {len(local_golden):,} satır.")
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

            cursor.execute("SELECT COUNT(*) FROM translations")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT source_text, target_text FROM translations")
            loaded = 0
            batch_size = 5000

            while True:
                if seq != self._load_seq:
                    conn.close()
                    return
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for s, t in rows:
                    if not s or not t:
                        continue
                    clean_s = _strip_tag(s).lower()
                    clean_t = _clean_target(t)
                    if not _is_valid_translation(clean_s, clean_t):
                        continue

                    local_data[clean_s] = clean_t
                    ns = _normalize(clean_s)
                    if ns and ns not in local_data_norm and ns not in local_golden_norm:
                        local_data_norm[ns] = clean_t
                        if len(ns) > 10:
                            for w in _index_words(ns):
                                local_index[w].append((ns, clean_t, "DB"))

                loaded += len(rows)
                if self.on_progress and total > 0:
                    self.on_progress(loaded, total)

            conn.close()
            if seq != self._load_seq:
                return
            # Atomik referans değişimi (iterasyon sırasında RuntimeError riskini sıfırlar)
            self.data_cache = local_data
            self._data_norm = local_data_norm
            self._word_index = dict(local_index)
            self.entry_count = len(local_golden) + len(local_data)
            self.is_loaded = True
            print(f"[DB] Yüklendi: {len(local_data):,} oyun çeviri satırı.")
        except Exception as e:
            print(f"[DB] Yükleme hatası: {e}")

    def find_translation(self, text: str) -> tuple[str | None, str]:
        """
        Çeviriyi O(1) hash + kelime kovası indeksiyle (<1.5 ms) arar.
        Returns: (translated_text, source_tag) -> örn ("Merhaba", "ALTIN") veya ("Merhaba", "DB")
        """
        if not self.is_loaded or not text:
            return None, ""

        search_key = _strip_tag(text).lower()
        if not search_key:
            return None, ""

        # 1. Tam Eşleşme (O(1))
        g_hit = self.golden_cache.get(search_key)
        if g_hit:
            return g_hit, "ALTIN"
        d_hit = self.data_cache.get(search_key)
        if d_hit:
            return d_hit, "DB"

        # 2. Noktalama/kesme işareti temizlenmiş normalize eşleşme (O(1))
        norm = _normalize(search_key)
        if not norm:
            return None, ""
        gn_hit = self._golden_norm.get(norm)
        if gn_hit:
            return gn_hit, "ALTIN"
        dn_hit = self._data_norm.get(norm)
        if dn_hit:
            return dn_hit, "DB"

        # 3. Kelime + uzunluk kovası üzerinden hızlı yakın eşleşme (<1.5 ms)
        idx = self._word_index
        if len(norm) > 10 and idx:
            q_words = [w for w in norm.split() if len(w) >= 4 and w not in _STOPWORDS]
            if not q_words:
                q_words = [w for w in norm.split() if len(w) >= 3]
            if not q_words:
                return None, ""

            n_len = len(norm)
            min_len = int(n_len * 0.80)
            max_len = int(n_len * 1.25) + 2
            cand_counts = Counter()
            cand_map = {}

            for w in q_words:
                bucket = idx.get(w)
                if not bucket:
                    continue
                # Aşırı yaygın kelimeleri hız için sınırla
                for cand_norm, cand_tr, tag in (bucket[:250] if len(bucket) > 250 else bucket):
                    clen = len(cand_norm)
                    if min_len <= clen <= max_len:
                        cand_counts[cand_norm] += 1
                        if cand_norm not in cand_map or tag == "ALTIN":
                            cand_map[cand_norm] = (cand_tr, tag)

            if not cand_counts:
                return None, ""

            min_shared = 2 if len(q_words) >= 3 else 1
            best_ratio = 0.85
            best_res = (None, "")
            for cand_norm, cnt in cand_counts.most_common(60):
                if cnt < min_shared:
                    break
                r = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
                if r > best_ratio:
                    best_ratio = r
                    best_res = cand_map[cand_norm]
            return best_res

        return None, ""

    def reload(self, new_db_path: str = None, on_progress=None):
        """Yeni bir veritabanı dosyası ile yeniden yükle."""
        self._load_seq += 1
        if new_db_path is not None:
            self.db_path = new_db_path
        if on_progress:
            self.on_progress = on_progress
        self.data_cache = {}
        self.golden_cache = {}
        self._golden_norm = {}
        self._data_norm = {}
        self._word_index = {}
        self.is_loaded = False
        self.entry_count = 0
        self.load_thread = threading.Thread(target=self._load_data, args=(self._load_seq,), daemon=True)
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

    def clear(self):
        """Öğrenilmiş tüm çevirileri temizler."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM learned_translations")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AutoLearn] Temizleme hatası: {e}")

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
