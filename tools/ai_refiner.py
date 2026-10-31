"""
NEXUS AI v2 — AI Refiner & Golden DB Builder (NVIDIA Llama-3.1 70B Supported)
Tüm çeviri kaynaklarını (Main DB, AutoLearn DB, YouTube Altyazıları, PDF Senaryosu, Google Translate)
NVIDIA Build API (Llama 3.1 70B) ile puanlayıp süzerek tek bir kusursuz 'nexus_golden.db' oluşturur.

Kullanım:
    python tools/ai_refiner.py
"""
import os
import sys
import time
import json
import sqlite3
import urllib.request
import re
from queue import Queue
from threading import Thread

# NEXUS AI yollarını sisteme ekle
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.config_manager import DATA_DIR

try:
    from deep_translator import GoogleTranslator
    DEEP_AVAILABLE = True
except ImportError:
    DEEP_AVAILABLE = False

NVIDIA_KEY_FILE = os.path.join(DATA_DIR, "nvdia_api.txt")
MAIN_DB_PATH = os.path.join(DATA_DIR, "rdr2_ceviri.db")
CACHE_DB_PATH = os.path.join(DATA_DIR, "translation_cache.db")
SCRIPT_TXT_PATH = os.path.join(DATA_DIR, "rdr2_script.txt")
GOLDEN_DB_PATH = os.path.join(DATA_DIR, "nexus_golden.db")

MODEL_NAME = "meta/llama-3.1-70b-instruct"
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def load_nvidia_key() -> str:
    env_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(NVIDIA_KEY_FILE):
        try:
            with open(NVIDIA_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    return ""


def init_golden_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(GOLDEN_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS golden_translations (
            source_text TEXT PRIMARY KEY,
            target_text TEXT,
            chosen_source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def parse_script_txt(file_path):
    """rdr2_script.txt içindeki İngilizce konuşma çizgilerini ayıklar."""
    if not os.path.exists(file_path):
        return []

    lines_set = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("[") or line.startswith("=="):
                    continue
                # Karakter ismini temizle (Örn: "Arthur Morgan: Hey there" -> "Hey there")
                if ":" in line:
                    parts = line.split(":", 1)
                    # Sol taraf kısa bir isim gibi mi (sahne tarifi değilse)
                    if len(parts[0]) < 35 and not parts[0].startswith("http"):
                        line = parts[1].strip()

                # Parantez içi sahne yönlendirmelerini sil (Örn: "(laughs) Hello")
                line = re.sub(r'\(.*?\)', '', line).strip()
                line = re.sub(r'\[.*?\]', '', line).strip()

                if len(line) > 2:
                    lines_set.add(line)
        return list(lines_set)
    except Exception as e:
        print(f"Script okuma hatası: {e}")
        return []


def get_db_dict(db_path, table_name, src_col, tgt_col):
    """Varolan SQLite veritabanından {source_lower: target} dict getirir."""
    res = {}
    if not os.path.exists(db_path):
        return res
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT {src_col}, {tgt_col} FROM {table_name}")
        for s, t in cursor.fetchall():
            if s and t:
                res[s.strip().lower()] = t.strip()
        conn.close()
    except Exception:
        pass
    return res


def call_nvidia_llm(api_key, english_text, cand_a, cand_b, cand_c):
    """NVIDIA Build API (Llama 3.1 70B) ile en iyi Türkçe çeviriyi seçtirir. HTTP 429 için bekle-tekrar dene eklenmiştir."""
    prompt = f"""
You are an expert game subtitle translator for Red Dead Redemption 2 (Wild West setting, natural conversational Turkish).
English subtitle: "{english_text}"

Candidate 1 (Main DB): "{cand_a or 'N/A'}"
Candidate 2 (AutoLearn/YouTube): "{cand_b or 'N/A'}"
Candidate 3 (Machine Translation): "{cand_c or 'N/A'}"

Select or refine the SINGLE best, most natural, grammatically correct Turkish translation suited for Wild West dialogue.
Do NOT include any explanations, notes, or quotes. Output ONLY the final Turkish translated text.
"""
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 150
    }

    req_data = json.dumps(payload).encode("utf-8")

    # Retry mekanizması (HTTP 429 Rate Limit için)
    for attempt in range(5):
        req = urllib.request.Request(
            API_URL,
            data=req_data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                content = res_data["choices"][0]["message"]["content"].strip()
                return content.strip('"').strip("'")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Limit aşımı: Üslü bekleme (1.5s, 3s, 6s...)
                wait_time = (attempt + 1) * 1.5
                time.sleep(wait_time)
            else:
                break
        except Exception:
            time.sleep(1)

    # Retry sonrası da olmadıysa mevcut en iyi adayı döndür
    return cand_a or cand_b or cand_c or english_text


def worker_thread(api_key, q_in, q_out, main_db, cache_db):
    translator = GoogleTranslator(source='en', target='tr') if DEEP_AVAILABLE else None

    while True:
        english_text = q_in.get()
        if english_text is None:
            break

        clean_key = english_text.lower()

        cand_a = main_db.get(clean_key, "")
        cand_b = cache_db.get(clean_key, "")
        cand_c = ""

        # 1. Öncelik: Eğer Ana DB veya Cache DB'de zaten varsa API harcama!
        if cand_a:
            best_translation = cand_a
            chosen = "MAIN_DB"
        elif cand_b:
            best_translation = cand_b
            chosen = "AUTO_LEARN"
        else:
            # 2. Hiçbir yerde yoksa Google Translate + NVIDIA AI Hakemi
            if translator:
                try:
                    cand_c = translator.translate(english_text)
                except Exception:
                    cand_c = ""

            best_translation = call_nvidia_llm(api_key, english_text, cand_a, cand_b, cand_c)
            chosen = "NVIDIA_AI"
            time.sleep(0.15)  # Rate limit koruması

        q_out.put((english_text, best_translation, chosen))
        q_in.task_done()


def main():
    print("=" * 60)
    print("  NEXUS AI v2 — AI REFINER & GOLDEN DB BUILDER (NVIDIA AI)")
    print("=" * 60)

    api_key = load_nvidia_key()
    if not api_key:
        print(f"\n[Hata] NVIDIA API Anahtarı bulunamadı! ({NVIDIA_KEY_FILE})")
        return
    print(f"✅ NVIDIA API Anahtarı algılandı: {api_key[:12]}...")

    init_golden_db()

    # 1. Mevcut Veritabanlarını Yükle
    print("\n[1/4] Mevcut veritabanları taranıyor...")
    main_db = get_db_dict(MAIN_DB_PATH, "translations", "source_text", "target_text")
    cache_db = get_db_dict(CACHE_DB_PATH, "learned_translations", "source_text", "target_text")
    print(f"-> Main DB (rdr2_ceviri.db): {len(main_db):,} satır")
    print(f"-> AutoLearn DB (translation_cache.db): {len(cache_db):,} satır")

    # 2. PDF Script Metnini Yükle
    print("\n[2/4] Senaryo metni (rdr2_script.txt) ayrıştırılıyor...")
    script_lines = parse_script_txt(SCRIPT_TXT_PATH)
    print(f"-> Senaryodan {len(script_lines):,} diyalog cümlesi çıkarıldı.")

    # 3. Tüm Kaynakları Birleştir
    all_sources = set(script_lines)
    all_sources.update(main_db.keys())
    all_sources.update(cache_db.keys())

    print(f"-> İşlenecek Toplam Benzersiz İngilizce Cümle: {len(all_sources):,}")

    # Zaten Golden DB'de olanları ele
    golden_existing = get_db_dict(GOLDEN_DB_PATH, "golden_translations", "source_text", "target_text")
    to_process = [line for line in all_sources if line.lower() not in golden_existing]

    print(f"-> Daha önce işlenmiş: {len(golden_existing):,} satır")
    print(f"-> Yeni İşlenecek: {len(to_process):,} satır")

    if not to_process:
        print("\n✅ Tüm cümleler zaten Altın Veritabanında (nexus_golden.db) mevcut! İşlem tamam.")
        return

    # 4. Multithreading Hakemlik İşlemi
    print(f"\n[3/4] NVIDIA Llama 3.1 70B Hakemliği Başlatılıyor (4 İş Parçacığı)...")

    num_threads = 4
    q_in = Queue()
    q_out = Queue()

    for line in to_process:
        q_in.put(line)

    threads = []
    for i in range(num_threads):
        t = Thread(target=worker_thread, args=(api_key, q_in, q_out, main_db, cache_db))
        t.start()
        threads.append(t)

    # İlerleme Takibi ve DB Kayıt
    completed = 0
    total = len(to_process)
    start_time = time.time()

    conn = sqlite3.connect(GOLDEN_DB_PATH)
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA journal_mode = MEMORY;")

    while completed < total:
        eng_text, tr_text, chosen = q_out.get()
        completed += 1

        if tr_text:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO golden_translations (source_text, target_text, chosen_source) VALUES (?, ?, ?)",
                    (eng_text.lower(), tr_text, chosen)
                )
            except Exception:
                pass

        if completed % 20 == 0 or completed == total:
            conn.commit()
            percent = int((completed / total) * 100)
            elapsed = time.time() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            sys.stdout.write(f"\r[%-50s] %d%% ({completed}/{total}) | Hız: {speed:.1f} cümle/sn" % ('=' * int(percent / 2), percent))
            sys.stdout.flush()

    conn.commit()
    conn.close()

    # Kapatma
    for _ in range(num_threads):
        q_in.put(None)
    for t in threads:
        t.join()

    print("\n\n" + "=" * 60)
    print(f"🎉 ALTIN VERİTABANI (nexus_golden.db) KUSURSUZ ŞEKİLDE OLUŞTURULDU!")
    print(f"-> Toplam Süre: {time.time() - start_time:.1f} saniye")
    print(f"-> nexus_golden.db içindeki toplam çeviri satırı: {len(golden_existing) + completed:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
