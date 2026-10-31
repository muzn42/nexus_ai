"""
NEXUS AI v2 — PDF to TXT Dönüştürücü
PDF formatındaki oyun senaryolarını veya altyazı dosyalarını okuyup 
data/rdr2_script.txt dosyasına çevirir.

Kullanım:
    python tools/convert_pdf.py [pdf_dosya_yolu]
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_TXT = os.path.join(DATA_DIR, "rdr2_script.txt")

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        print("[Hata] pypdf veya PyPDF2 kütüphanesi bulunamadı.")
        print("Lütfen terminalde 'pip install pypdf' komutunu çalıştırın.")
        sys.exit(1)


def convert_pdf_to_txt(pdf_path: str, output_path: str):
    if not os.path.exists(pdf_path):
        print(f"[Hata] Dosya bulunamadı: {pdf_path}")
        return False

    print(f"📄 PDF okunuyor: {pdf_path}")
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        print(f"-> Toplam {total_pages} sayfa bulundu. Dönüştürme başlıyor...")

        extracted_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                extracted_text.append(text)

            if (i + 1) % 50 == 0 or (i + 1) == total_pages:
                print(f"-> {i + 1}/{total_pages} sayfa işlendi...")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        full_content = "\n".join(extracted_text)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        print("=" * 50)
        print(f"✅ DÖNÜŞTÜRME BAŞARILI!")
        print(f"-> Çıktı Dosyası: {output_path}")
        print(f"-> Toplam Karakter Sayısı: {len(full_content):,}")
        print("=" * 50)
        return True

    except Exception as e:
        print(f"[Hata] Dönüştürme sırasında hata oluştu: {e}")
        return False


def main():
    print("=" * 50)
    print("  NEXUS AI - PDF TO TXT DÖNÜŞTÜRÜCÜ")
    print("=" * 50)

    # 1. Komut satırından dosya verilmiş mi?
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        # 2. data/ klasöründe .pdf var mı kontrol et
        pdf_files = [f for f in os.listdir(DATA_DIR) if f.endswith(".pdf")] if os.path.exists(DATA_DIR) else []
        if pdf_files:
            pdf_path = os.path.join(DATA_DIR, pdf_files[0])
            print(f"-> 'data/' klasöründe otomatik bulunan PDF: {pdf_files[0]}")
        else:
            pdf_path = input("\n📁 PDF dosyanızın yolunu girin (veya dosyayı data/ klasörüne atın):\n> ").strip().strip('"')

    if pdf_path:
        convert_pdf_to_txt(pdf_path, OUTPUT_TXT)


if __name__ == "__main__":
    main()
