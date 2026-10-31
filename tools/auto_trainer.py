"""
NEXUS AI v2 — Auto-Trainer (YouTube Veritabanı Eğiticisi)
YouTube videolarından İngilizce altyazıları indirip çevirerek yerel veritabanına kaydeder.
Kullanım:
    python tools/auto_trainer.py
"""
import os
import sys
import time
import sqlite3
import urllib.request
import urllib.error
import re
from queue import Queue
from threading import Thread

# NEXUS AI yollarını sisteme ekle
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.config_manager import DATA_DIR
from core.db_manager import AutoLearnDB

try:
    import yt_dlp
except ImportError:
    print("yt-dlp yüklü değil! Lütfen 'pip install yt-dlp' komutunu çalıştırın.")
    sys.exit(1)

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("deep-translator yüklü değil! Lütfen 'pip install deep-translator' komutunu çalıştırın.")
    sys.exit(1)


def parse_vtt(file_path):
    """
    VTT dosyasındaki zaman damgalarını temizler ve sadece metinleri alır.
    Aynı cümleleri tekrarlamamak için set kullanır.
    """
    lines_set = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        current_text = ""
        for line in lines:
            line = line.strip()
            # Başlık ve zaman damgalarını atla
            if not line or line.startswith("WEBVTT") or "-->" in line:
                continue
            
            # Auto-generated altyazılardaki <c> veya benzeri tagleri temizle
            clean_line = re.sub(r'<[^>]+>', '', line).strip()
            clean_line = clean_line.replace("&nbsp;", " ")
            
            if clean_line:
                lines_set.add(clean_line)
                
        return list(lines_set)
    except Exception as e:
        print(f"VTT parse hatası: {e}")
        return []


def download_subtitles(url, output_dir):
    """yt-dlp ile sadece İngilizce altyazıları indirir."""
    print(f"\n[1/3] Altyazılar kontrol ediliyor ve indiriliyor: {url}")
    
    ydl_opts = {
        'skip_download': True,        # Videoyu indirme
        'writesubtitles': True,       # Manuel altyazıları yaz
        'writeautomaticsub': True,    # Otomatik altyazıları yaz
        'subtitleslangs': ['en'],     # Sadece İngilizce
        'outtmpl': os.path.join(output_dir, 'video_sub.%(ext)s'),
        'quiet': True,
        'no_warnings': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # İndirilen dosyayı bul
        for file in os.listdir(output_dir):
            if file.startswith("video_sub.") and file.endswith(".vtt"):
                print(f"-> Altyazı bulundu: {file}")
                return os.path.join(output_dir, file)
                
        print("-> Videoda İngilizce altyazı bulunamadı!")
        return None
    except Exception as e:
        print(f"İndirme hatası: {e}")
        return None


def translate_worker(q_in, q_out, index, total):
    """Kuyruktan gelen kelimeleri Google Translate ile çevirir."""
    translator = GoogleTranslator(source='en', target='tr')
    
    while True:
        task = q_in.get()
        if task is None:
            break
            
        en_text = task
        try:
            tr_text = translator.translate(en_text)
            q_out.put((en_text, tr_text))
        except Exception:
            q_out.put((en_text, None)) # Hata durumunda
            
        q_in.task_done()


def main():
    print("="*50)
    print("  NEXUS AI - AUTO-TRAINER (YouTube Veritabanı Eğitici)")
    print("="*50)
    
    url = input("\n🔗 YouTube Oynanış Videosu URL'si girin:\n> ").strip()
    if not url:
        print("Hata: URL boş olamaz.")
        return
        
    temp_dir = os.path.join(BASE_DIR, "temp_subs")
    os.makedirs(temp_dir, exist_ok=True)
    
    # 1. Altyazı İndir
    vtt_file = download_subtitles(url, temp_dir)
    if not vtt_file:
        return
        
    # 2. VTT'yi Ayrıştır (Parse)
    print("\n[2/3] Altyazılar ayrıştırılıyor...")
    unique_lines = parse_vtt(vtt_file)
    print(f"-> {len(unique_lines)} adet benzersiz diyalog/cümle bulundu.")
    
    if len(unique_lines) == 0:
        print("Çevrilecek metin yok, çıkılıyor.")
        return
        
    # 3. Çeviri ve Kayıt
    print(f"\n[3/3] Çeviri işlemi başlıyor (Hedef DB: translation_cache.db)...")
    
    auto_db = AutoLearnDB(DATA_DIR)
    initial_count = auto_db.count
    
    # Multithreading için kuyruk sistemi
    thread_count = 10  # Google Translate'i çok zorlamadan hızlı çeviri için 10 thread
    q_in = Queue()
    q_out = Queue()
    
    # Cümleleri kuyruğa ekle (önceden öğrenilmiş olanları atla)
    to_translate = []
    for line in unique_lines:
        if not auto_db.find(line):
            to_translate.append(line)
            
    if not to_translate:
        print("-> Bu videodaki tüm diyaloglar zaten veritabanında mevcut! İşlem tamam.")
        return
        
    print(f"-> {len(to_translate)} adet yeni cümle çevirilecek...")
    
    for line in to_translate:
        q_in.put(line)
        
    threads = []
    for i in range(thread_count):
        t = Thread(target=translate_worker, args=(q_in, q_out, i, len(to_translate)))
        t.start()
        threads.append(t)
        
    # Ana thread'de progress bar göster
    completed = 0
    total = len(to_translate)
    start_time = time.time()
    
    while completed < total:
        en_text, tr_text = q_out.get()
        completed += 1
        
        if tr_text:
            auto_db.save(en_text, tr_text, engine="Auto-Trainer(Google)")
            
        # Basit progress bar
        percent = int((completed / total) * 100)
        sys.stdout.write(f"\rİlerleme: [%-{50}s] %d%% ({completed}/{total})" % ('=' * int(percent/2), percent))
        sys.stdout.flush()
        
    print("\n\nTemizlik yapılıyor...")
    # Threadleri kapat
    for _ in range(thread_count):
        q_in.put(None)
    for t in threads:
        t.join()
        
    # Temp dosyayı sil
    try:
        os.remove(vtt_file)
    except Exception:
        pass
        
    final_count = auto_db.count
    added = final_count - initial_count
    
    elapsed = time.time() - start_time
    print("="*50)
    print(f"✅ İŞLEM TAMAMLANDI! ({elapsed:.1f} saniye)")
    print(f"-> Veritabanına {added} yeni çeviri eklendi.")
    print(f"-> Toplam Öğrenilmiş Veritabanı (translation_cache.db) boyutu: {final_count} satır.")
    print("Artık oyunu oynarken bu diyaloglar geldiğinde anında internet kullanmadan Türkçe görünecek!")
    print("="*50)


if __name__ == "__main__":
    main()
