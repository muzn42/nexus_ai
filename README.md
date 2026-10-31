# NEXUS AI — Gerçek Zamanlı Oyun Çeviri Asistanı

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PaddleOCR](https://img.shields.io/badge/OCR-PaddleOCR%20v5-orange.svg)](https://github.com/PaddlePaddle/PaddleOCR)
[![UI](https://img.shields.io/badge/UI-CustomTkinter-blueviolet.svg)](https://github.com/TomSchimansky/CustomTkinter)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

NEXUS AI, ekrandaki veya HDMI Capture Card üzerindeki oyun altyazılarını ve metinlerini anlık olarak okuyan (OCR), **Yerel Veritabanı (RDR2 SQLite) + NVIDIA NIM / Google Gemini AI** hibrit altyapısı ile Türkçe'ye çeviren ve şeffaf/özelleştirilebilir bir HUD (overlay) üzerinde gösteren yeni nesil bir çeviri asistanıdır.

---

## ✨ Özellikler

- 🚀 **PP-OCRv5 Desteği:** PaddleOCR PP-OCRv5 ile oyun içi altyazılarda ultra hızlı ve yüksek doğrulukta metin tanıma.
- ⚡ **Hibrit Çok Katmanlı Çeviri Akışı:**
  1. **Bellek İçi LRU Önbellek (0 ms)**: Tekrarlanan replikler anında ekrana gelir.
  2. **Altın Veritabanı (`nexus_golden.db`)**: Yapay zeka ile süzülmüş yüksek kaliteli çeviriler.
  3. **Oyun Veritabanı (`rdr2_ceviri.db`)**: Yerel SQLite veritabanı eşleşmesi.
  4. **Otomatik Öğrenme DB (`AutoLearnDB`)**: Yeni çevrilen cümleler otomatik olarak yerel veritabanına kaydedilir.
  5. **Online & Offline Motorlar**: Google Gemini AI, Argos Translate (tamamen çevrimdışı) veya Google Translate.
- 🎮 **Oyun İçi Şeffaf HUD (Overlay):** Tıklama geçiren (click-through), şeffaf arka planlı, kenarlık (stroke) ve font ayarlı modern arayüz.
- 📹 **HDMI Capture Card & Çift Ekran Desteği:** Konsol oyuncuları için Capture Card üzerinden görüntü alma desteği.

---

## 📁 Proje Klasör Yapısı

```text
nexus2-anti/
├── main.py                     # Ana uygulama başlatıcı (HUD)
├── requirements.txt            # Python bağımlılık listesi
├── .env.example                # API anahtarları için örnek şablon
├── README.md                   # Proje dokümantasyonu
│
├── config/                     # Yapılandırma ve kırpma profilleri
│   ├── profiles.json           # Kayıtlı ekran koordinat profilleri
│   ├── capture_profiles.json   # Capture Card profilleri
│   └── settings.json           # Kullanıcı arayüz ve motor ayarları
│
├── core/                       # Çekirdek modüller
│   ├── config_manager.py       # Ayar ve profil yöneticisi
│   ├── db_manager.py           # SQLite ve Altın DB yöneticisi
│   ├── ocr_engine.py           # PaddleOCR motoru
│   └── translation_engine.py   # Hibrit çeviri yönlendiricisi
│
├── ui/                         # Arayüz bileşenleri
│   ├── hud.py                  # Şeffaf oyun içi HUD overlay
│   ├── launcher.py             # Başlatıcı ve ekran seçim ekranı
│   ├── settings_dialog.py      # Ayarlar penceresi
│   └── widgets.py              # Özel UI bileşenleri
│
├── data/                       # Veritabanı dosyaları
│   ├── nexus_golden.db         # AI ile işlenmiş altın çeviri veritabanı
│   ├── rdr2_ceviri.db          # 27MB RDR2 diyalog veritabanı
│   └── ...
│
├── tools/                      # Yardımcı araçlar ve test betikleri
│   ├── setup_argos.py          # Argos Translate çevrimdışı model indirici
│   ├── ai_refiner.py           # Veritabanı iyileştirme aracı
│   └── convert_pdf.py          # PDF senaryo dönüştürücü
│
└── archive/                    # Eski sürüm ve geliştirme yedekleri
```

---

## 🚀 Kurulum

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/muzn42/nexus-ai.git
cd nexus-ai
```

### 2. Sanal Ortam Oluşturun (Önerilen)
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate
```

### 3. Bağımlılıkları Yükleyin
```bash
pip install -r requirements.txt
```
> **Not:** GPU hızlandırmalı PaddleOCR kullanmak isterseniz sisteminize uygun [PaddlePaddle GPU](https://www.paddlepaddle.org.cn/) sürümünü kurabilirsiniz.

### 4. (İsteğe Bağlı) API Anahtarları
Google Gemini AI kullanmak isterseniz `.env.example` dosyasını `.env` olarak kopyalayabilir veya uygulama içindeki Ayarlar (F11/Settings) menüsünden anahtarınızı girebilirsiniz:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 5. (İsteğe Bağlı) Çevrimdışı Argos Translate Modelini İndirin
İnternetsiz çeviri kullanmak istiyorsanız:
```bash
python tools/setup_argos.py
```

---

## 🎮 Kullanım

Uygulamayı başlatmak için kök dizinde şu komutu çalıştırın:

```bash
python main.py
```

### ⌨️ Klavye Kısayolları

| Tuş | İşlev |
| :--- | :--- |
| **F9** | Çeviriyi Başlat / Durdur |
| **F10** | Yeni Çeviri Alanı (ROI) Seç |
| **F11** | Minimal / Şeffaf Moda Geçiş |
| **F8** | HUD Pencere Taşıma Modu |
| **F12** | Güvenli Çıkış |
