# NEXUS AI — Gerçek Zamanlı Oyun Çeviri Asistanı

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PaddleOCR](https://img.shields.io/badge/OCR-PP--OCRv6-orange.svg)](https://github.com/PaddlePaddle/PaddleOCR)
[![UI](https://img.shields.io/badge/UI-PySide6%20(Qt)-41CD52.svg)](https://doc.qt.io/qtforpython-6/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Ekrandaki veya capture card üzerindeki oyun altyazısını okur (OCR), sözlüğünden
ya da yapay zekadan çevirir ve oyunun üstünde **tıklamaları engellemeyen şeffaf
bir katman** olarak gösterir. PS5'te oyunu kendi dilinde oynamak için tasarlandı.

---

## Neden bu sürüm?

Arayüz baştan yazıldı: **Tkinter → PySide6 (Qt)**. Kazançlar:

| Konu | Eski (Tkinter) | Yeni (Qt) |
|---|---|---|
| Altyazı çizimi | Metin başına ~80 nesne | Tek `QPainterPath` stroke+fill |
| Saydamlık | Renk anahtarı, tırtıklı kenar | Gerçek piksel-alfa, anti-aliased |
| Oyun üstünde tıklama geçişi | Yok | `WS_EX_TRANSPARENT` ile gerçek |
| Ayarlar | Anlık geri bildirim yok | **Canlı önizleme** |
| Sözlük tarayıcı | Elle | Tablo + anlık arama |
| İlk kullanım | Keşfetmesi zor | 4 adımlı sihirbaz |

---

## Özellikler

- **PP-OCRv6 / v5 / v4** + model boyutu seçimi (**tiny / small / medium**)
- **CPU (MKLDNN) veya GPU (CUDA)** — GPU'da ~30-70 ms
- **Hibrit çeviri zinciri:**
  1. Bellek içi LRU önbellek (0 ms)
  2. Altın Sözlük (`nexus_golden.db`)
  3. Oyun Sözlüğü (`rdr2_ceviri.db` vb.)
  4. Otomatik öğrenme havuzu
  5. Yapay zeka: Akıllı Zincir (Groq → Gemini) / Google / Argos
- **Sözlük Kütüphanesi:** yerel dosyaları otomatik bulur, tek tıkla indirir,
  `.db` içe aktarır, içinde iki dilli arama yapar
- **Chiaki-ng yardımcısı:** PS5'i ağda otomatik bulur, adım adım rehber
- **Görünüm stüdyosu:** 5 hazır ön ayar + yazı boyutu/renk/çizgi kalınlığı,
  canlı önizleme
- **Şeffaf, tıklama geçirgen HUD** + tekerlekle altyazı geçmişi
- **Sadece seçilen bölge yakalanır** → algılama döngüsü 5-10 kat hızlı
- **Arka planda OCR ısınma:** ilk "Başlat" beklemesiz

---

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### ⚠️ PaddlePaddle sürümü (OCR hızını 3-6 kat etkiler)
`paddlepaddle 3.3.0/3.3.1` sürümlerinde oneDNN (MKLDNN) + PIR hatası var
(`ConvertPirAttribute2RuntimeAttribute` → [Paddle#77340](https://github.com/PaddlePaddle/Paddle/issues/77340)).
OCR sessizce yavaş CPU moduna düşer. Çözüm:

```bash
pip install paddlepaddle==3.2.2
```

GPU için (NVIDIA + CUDA 12.6):
```bash
pip install paddlepaddle-gpu==3.2.2 --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install nvidia-cudnn-cu12 nvidia-cublas-cu12
```

---

## Çalıştırma

```bash
python main.py
```

İlk açılışta sihirbaz sizi 4 adımda hazırlar:

1. **Dil + motor** — anahtarsız başlamak için "Google Translate" seçin
2. **Alan seç** — ekranda altyazının çıktığı dikdörtgeni işaretleyin
3. **Sözlük (opsiyonel)** — varsa çeviriler anında ve bedava gelir
4. **Başlat**

### Kısayollar

| Tuş | İşlev |
|---|---|
| `F9` | Başlat / Durdur |
| `F10` | Altyazı alanını seç |
| `F11` | Ayarlar |
| `F8` | HUD kilidi (tıklamalar oyuna geçsin) |
| `F12` | Çıkış |

Ayarlar → Kısayollar'dan değiştirilebilir.

---

## PS5'te kullanım (Chiaki-ng)

1. PS5 → Ayarlar → Sistem → **Uzaktan Oynatmayı Etkinleştir**
2. Chiaki-ng'yi kur, PS5'i kaydet (8 haneli kod)
3. Nexus AI → **PS5 / Chiaki-ng** ekranı → **PS5'imi Bul** (otomatik IP taraması)
4. Oyunu Chiaki'de aç → Nexus AI'da kaynak "PC Ekranı" → alan seç → `F9`

Chiaki-ng: https://github.com/streetpea/chiaki-ng/releases

---

## Proje yapısı

```text
nexus2-anti/
├── main.py                      # Giriş noktası → ui/qt/app.py
├── core/
│   ├── theme.py                 # Tasarım sistemi (renkler, QSS, ön ayarlar)
│   ├── config_manager.py        # settings.json / profiles.json
│   ├── capture.py               # Ekran / kamera yakalama (ROI optimizasyonu)
│   ├── ocr_engine.py            # PaddleOCR (tiny/small/medium, CPU/GPU)
│   ├── db_manager.py            # Sözlük yükleme + auto-learn
│   ├── db_catalog.py            # Sözlük kütüphanesi (indir/içe aktar/ara)
│   ├── translation_engine.py    # Hibrit çeviri dispatcher
│   ├── llm_chain.py             # Groq → Gemini zinciri (SSE)
│   ├── pipeline.py              # Yakala → OCR → çevir döngüsü
│   └── chiaki.py                # PS5 bulma + rehber
├── ui/qt/
│   ├── app.py                   # QApplication, kısayollar, ısınma
│   ├── controller.py            # Motorlar + sinyaller
│   ├── components.py            # Card, Chip, Toast, SliderRow...
│   ├── main_window.py           # Ana ekran (4 adım)
│   ├── settings_window.py       # 5 sekmeli ayarlar + canlı önizleme
│   ├── dictionary_window.py     # Sözlük kütüphanesi
│   ├── chiaki_window.py         # PS5 yardımcısı
│   ├── onboarding.py            # İlk kullanım sihirbazı
│   ├── subtitle_view.py         # Altyazı çizimi (QPainterPath)
│   ├── hud.py                   # Şeffaf, tıklama geçirgen katman
│   └── roi_selector.py          # Tam ekran alan seçici
├── ui/                          # Eski Tkinter arayüzü (yedek, main_v1.py)
├── config/                      # settings.json, profiles.json, dictionaries.json
└── data/                        # *.db sözlükleri
```


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
git clone https://github.com/muzn42/nexus_ai.git
cd nexus_ai
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

#### ⚠️ Önemli: PaddlePaddle sürümü (OCR hızını 3-6 kat etkiler)
`paddlepaddle 3.3.0 / 3.3.1` sürümlerinde oneDNN (MKLDNN) + PIR yürütücüsü çakışması var
(`ConvertPirAttribute2RuntimeAttribute not support` → [Paddle#77340](https://github.com/PaddlePaddle/Paddle/issues/77340), [Paddle#79749](https://github.com/PaddlePaddle/Paddle/issues/79749)).
Bu durumda OCR sessizce yavaş CPU moduna düşer. Çözüm:

```bash
pip install paddlepaddle==3.2.2
```

GPU kullanacaksanız (NVIDIA + CUDA 12.6):
```bash
pip install paddlepaddle-gpu==3.2.2 --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install nvidia-cudnn-cu12==9.5.1.17 nvidia-cublas-cu12==12.6.4.1
```
Uygulama, GPU başlatılamazsa otomatik olarak CPU moduna döner.

#### 📊 OCR hız ölçümü
Kendi sisteminizde ölçmek için:
```bash
python tools/bench_ocr.py                # CPU (MKLDNN açık/kapalı)
python tools/bench_ocr.py --device gpu   # GPU
```

Ölçüm sonuçları (960×120 altyazı görüntüsü, GTX 1660 Ti + i7 sınıfı CPU):

| Model | paddle 3.3.1 (MKLDNN bozuk) | paddle 3.2.2 CPU + MKLDNN | GPU (CUDA 12.6) |
| :--- | ---: | ---: | ---: |
| PP-OCRv6 tiny | 283 ms | 69 ms | **27 ms** |
| PP-OCRv6 small | 561 ms | 139 ms | **46 ms** |
| PP-OCRv6 medium | 2198 ms | 367 ms | **70 ms** |

Ayarlar → **OCR Ayarları** bölümünden model boyutu (tiny / small / medium) ve işlem birimi (CPU / GPU) seçilebilir.

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
