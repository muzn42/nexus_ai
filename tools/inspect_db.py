import xml.etree.ElementTree as ET
import sqlite3
import os
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from sentence_transformers import SentenceTransformer, models, util

# --- AYARLAR ---
MODEL_PATH = r"D:\model_dosyalari" 
SIMILARITY_THRESHOLD = 0.65  

def clean_text(text):
    """Metni RDR2 kodlarından temizler."""
    if not text: return ""
    text = str(text)
    text = text.replace("~n~", " ")
    text = re.sub(r'~[a-zA-Z0-9_]+~', '', text)
    text = re.sub(r'sl:[\d\.]+', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return " ".join(text.split())

def parse_xml_to_dict(xml_file):
    """XML okuma fonksiyonu"""
    data_dict = {}
    print(f"Okunuyor: {os.path.basename(xml_file)}")
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for child in root.findall('String'):
            key_id = child.get('id') or child.get('label')
            raw_text = child.text
            if key_id and raw_text:
                cleaned = clean_text(raw_text)
                if len(cleaned) > 2: 
                    data_dict[key_id] = cleaned
    except Exception as e:
        print(f"Hata: {e}")
    return data_dict

def dosya_sec(baslik):
    root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
    path = filedialog.askopenfilename(title=baslik, filetypes=[("XML", "*.xml")])
    root.destroy()
    return path

def main():
    print("--- RDR2 HİBRİT EŞLEŞTİRİCİ (FİNAL VERSİYON) ---")
    
    # 1. Dosya Kontrolü
    if not os.path.exists(MODEL_PATH):
        print("Model klasörü bulunamadı!")
        return

    # 2. XML Seçimi
    eng_path = dosya_sec("İNGİLİZCE (Kaynak) Dosyayı Seç")
    if not eng_path: return
    tr_path = dosya_sec("TÜRKÇE (Hedef) Dosyayı Seç")
    if not tr_path: return

    # 3. Verileri Oku
    eng_dict = parse_xml_to_dict(eng_path)
    tr_dict = parse_xml_to_dict(tr_path)
    
    # 4. DB Hazırla
    db_name = "rdr2_ceviri.db"
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS translations')
    cursor.execute('CREATE TABLE translations (source_text TEXT PRIMARY KEY, target_text TEXT)')

    # --- AŞAMA 1: ID EŞLEŞTİRME ---
    print("\n[1. AŞAMA] ID Eşleştirmesi yapılıyor...")
    match_count = 0
    leftover_eng = []
    
    # Türkçe metinleri kopyala (AI havuzu için)
    remaining_tr_texts = list(tr_dict.values())
    used_tr_texts = set()

    for key_id, eng_text in eng_dict.items():
        if key_id in tr_dict:
            tr_text = tr_dict[key_id]
            cursor.execute("INSERT OR IGNORE INTO translations VALUES (?, ?)", (eng_text, tr_text))
            match_count += 1
            used_tr_texts.add(tr_text)
        else:
            leftover_eng.append(eng_text)

    leftover_tr = [txt for txt in remaining_tr_texts if txt not in used_tr_texts]
    conn.commit()
    print(f"-> ID ile Eşleşen: {match_count}")
    
    if not leftover_eng:
        print("Tüm dosyalar eşleşti!"); conn.close(); return

    # --- AŞAMA 2: AI EŞLEŞTİRME (DÜZELTİLEN KISIM) ---
    print(f"\n[2. AŞAMA] Model Yükleniyor (Manuel Montaj Modu)...")
    
    try:
        # --- BURASI DEĞİŞTİ: Modeli elle inşa ediyoruz ---
        # 1. Ana Transformer modelini yükle (config.json ve model.safetensors kullanır)
        word_embedding_model = models.Transformer(MODEL_PATH)
        
        # 2. Pooling katmanını elle ekle (Hata veren yer burasıydı, şimdi biz oluşturuyoruz)
        pooling_model = models.Pooling(word_embedding_model.get_word_embedding_dimension())
        
        # 3. Parçaları birleştir
        model = SentenceTransformer(modules=[word_embedding_model, pooling_model])
        print("BAŞARILI! Model yüklendi.")
        
    except Exception as e:
        print(f"MODEL HATASI: {e}"); conn.close(); return

    print("Metinler analiz ediliyor (Vektörleme)...")
    eng_emb = model.encode(leftover_eng, convert_to_tensor=True, show_progress_bar=True)
    tr_emb = model.encode(leftover_tr, convert_to_tensor=True, show_progress_bar=True)

    print("Eşleştirme yapılıyor...")
    hits = util.semantic_search(eng_emb, tr_emb, top_k=1)

    ai_count = 0
    for i, hit in enumerate(hits):
        if hit[0]['score'] > SIMILARITY_THRESHOLD:
            eng = leftover_eng[i]
            tr = leftover_tr[hit[0]['corpus_id']]
            cursor.execute("INSERT OR IGNORE INTO translations VALUES (?, ?)", (eng, tr))
            ai_count += 1

    conn.commit()
    conn.close()

    print("\n" + "="*40)
    print(f"BİTTİ! Toplam: {match_count + ai_count} satır.")
    print(f"Dosya: {os.path.abspath(db_name)}")
    print("="*40)
    
    root = tk.Tk(); root.withdraw()
    messagebox.showinfo("Bitti", f"İşlem Tamam!\nDosya: {db_name}")

if __name__ == "__main__":
    main()