# NEXUS AI (v2 / v3 Canlı Tam Ekran Yama Motoru)

**NEXUS AI**, PC oyunları ile **PS5 / PS6 + Capture Card** (OBS / yakalama önizlemesi veya Chiaki Remote Play) üzerinden gelen oyun görüntülerindeki altyazı, menü, kontrol ipucu ve arayüz yazılarını **gerçek zamanlı OCR + Yerel Sözlük + Paralel Yapay Zeka Akışı** ile Türkçeye (ve seçili hedef dillere) çevirip **orijinal oyunun üzerine yerinde yama (In-Place Patch)** veya **dinamik altyazı HUD** olarak çizen PySide6 tabanlı Windows uygulamasıdır.

> **Hızlı Başlatma:**
> ```bash
> git clone <repo-url>
> cd nexus2-anti
> pip install -r requirements.txt
> python main.py
> ```

---

## İçindekiler

1. [Temel Özellikler & Çalışma Modları](#1-temel-özellikler--çalışma-modları)
2. [Neler Yaptık ve Neden? (Mimari Kararlar & AI Ajan Rehberi)](#2-neler-yaptık-ve-neden-mimari-kararlar--ai-ajan-rehberi)
3. [Veri Akışı: İki Paralel İş Parçacığı (Dual-OCR Pipeline)](#3-veri-akışı-iki-paralel-iş-parçacığı-dual-ocr-pipeline)
4. [Dosya ve Modül Mimarisi](#4-dosya-ve-modül-mimarisi)
5. [Ayarlar (`config/settings.json`) & Kısayol Tuşları](#5-ayarlar-configsettingsjson--kısayol-tuşları)
6. [Bilinen Donanım / PaddleOCR Notları & Kurulum](#6-bilinen-donanım--paddleocr-notları--kurulum)

---

## 1. Temel Özellikler & Çalışma Modları

`F6` kısayolu veya ana pencereden 3 farklı görüntüleme/yama modu arasında anında geçiş yapılır:

| Mod (`patch_mode`) | Davranış | Ne Zaman Kullanılır? |
| :--- | :--- | :--- |
| **`full_patch`** *(Varsayılan)* | Hem alt-orta altyazıları hem de ekranın her yerindeki menüleri, sol-üst ipuçlarını, silah/eşya çarkını ve sağ-alt buton açıklamalarını **orijinal yerlerinde** Buzlu Cam + Bukalemun yaması ile kaplayıp Türkçeleştirir. | GTA 6, RDR2 vb. oyunları tam Türkçe yama gibi oynarken. |
| **`hybrid`** | Alt-orta altyazıları alttaki **dinamik boyutlu HUD** penceresinde gösterir; altyazı dışı tüm dünya/menü yazılarını ise kendi yerlerinde yamalar. | Altyazıyı sabit HUD stilinde okumak, menüleri yine yerinde çevirmek istediğinizde. |
| **`subtitle_only`** | Yalnızca seçilen manuel ROI alanını veya otomatik alt-orta altyazı şeridini okur ve HUD penceresinde gösterir. | Yalnızca diyalog altyazılarına odaklanıp maksimum hız istendiğinde. |

### Ek Canlı Özellikler
- **`F7` Anlık Dondur & Oku (`trigger_freeze_scan`):** Yoğun metinli bir menüde veya hızlı kaybolan ekranda tam çözünürlüklü tek kare yakalayıp tarar ve `❄ DONDURULDU` şeridi ile ekranı sabitler; tekrar `F7` ile canlı moda döner.
- **`WDA_EXCLUDEFROMCAPTURE` Koruması:** `MainWindow`, `HUDWindow`, `PatchOverlayWindow` ve tüm uygulama pencereleri Windows DWM API üzerinden yakalama dışı bırakılır (`core/windows.py`). Böylece OCR kendi çizdiği Türkçe metni asla tekrar okuyup döngüye girmez.
- **SSE Canlı Akış (`stream=True`):** Altyazı LLM çevirisi Groq `GPT-OSS` üzerinden kelime/token aktıkça (`on_partial`) ekranda belirir; cümlenin bitmesini beklemez.
- **Konsol / Capture Card Desteği:** Hem masaüstü/pencere (`ScreenSource` / `WindowSource`) hem Capture Card (`CameraSource`) kaynaklarını ve PS5 Remote Play (`core/chiaki.py`) keşfini destekler.

---

## 2. Neler Yaptık ve Neden? (Mimari Kararlar & AI Ajan Rehberi)

Bu bölüm, projeyi devralan geliştiricilerin ve **kod üzerinde çalışacak başka bir yapay zeka ajanının** her mekanizmanın neden o şekilde yazıldığını anlaması için kararların gerekçelerini özetler.

### 2.1. Yerinde Buzlu Cam + Bukalemun Yama (`ui/qt/patch_overlay.py` & `core/text_filter.py`)
- **Sorun:** Klasik tek renk siyah/opak dikdörtgen yamalar oyunun arayüzünde yamalı duruyor ve alttaki farklı renkli panellerle (GTA 6 menü seçili gri bar, siyah altyazı kutusu, sol-üst koyu ipucu kutusu) uyumsuz görünüyordu. Ayrıca RDR2/GTA görevlerindeki sarı/renkli vurgu kelimeleri kayboluyordu.
- **Çözüm (`sample_box_style` & `PatchOverlayWindow.paintEvent`):**
  1. **Buzlu Cam (`blurred_rgb`):** Orijinal oyun karesindeki kutu kırpımı `cw//4 × ch//4` boyutuna küçültülüp `GaussianBlur` uygulanır ve geri büyütülür. Bu işlem büyük kutularda bile 0.3 ms altında sürer ve alttaki İngilizce harfleri tamamen eritir.
  2. **Bukalemun Zemin (`bg_color`):** Kutunun 2–3 px dış kenar piksellerinin medyan rengi örneklenir ve `chameleon_opacity` (%) ile buzlu camın üzerine doldurulur.
  3. **Orijinal Metin Rengi (`fg_color`) & Hizalama (`align`):** Arka plandan en farklı %15 pikselin medyanından orijinal metin rengi (ör. görev sarısı, kırmızı uyarı, beyaz veya seçili açık menü çubuğundaki koyu yazı) korunur; ekran ortasındaki geniş kutular ortalı, yan kutular sola yaslı çizilir.
  4. **İkonlara Taşmayan Dolgu (`pad_x`):** `PatchOverlayWindow.paintEvent` içinde altyazılar için `pad_x=5.0 px`, altyazı dışı buton/menü etiketleri için ise `pad_x=1.5 px` kullanılır ki sağdaki kontrolcü buton ikonlarının üzerine taşmasın.

### 2.2. Neden İki Ayrı Paralel OCR + Çeviri Thread'i? (`core/pipeline.py`)
- **Sorun:** Tek thread çalışan bir hatta tam ekran dünya/menü OCR'ı ve `translate_batch()` AI çağrısı 600–1500 ms sürdüğünde, o sırada çıkan yeni bir altyazı cümlesi dünya işinin bitmesini beklemek zorunda kalıyordu. Ayrıca GTA 6 gibi PS5/PS6 + Capture Card üzerinden oynanan oyunlarda **PC'nin hem GPU'su hem CPU'su oyun tarafından kullanılmadığı için boşta bekliyordu.**
- **Çözüm:** `TranslationPipeline` iki bağımsız daemon thread başlatır:
  - **`nexus-sub-pipeline` (`_loop` / `_tick`):** Yalnızca alt-orta altyazı şeridiyle (`auto_subtitle_roi`, `y: 0.72..0.98`) ilgilenir. Varsayılan olarak **GPU** (`PP-OCRv6 / small / gpu`) kullanır, altyazı değiştiğinde anında OCR çalıştırır ve SSE `on_partial` ile kelime kelime basar. Dünya hattını **0 ms** bekler.
  - **`nexus-world-pipeline` (`_world_loop` / `_process_world_pass`):** `world_scan_interval` (varsayılan `0.55s`) aralığında tam karedeki menü, sol-üst ipucu, sağ-alt buton barı ve silah çarkını ayrı `world_ocr` motoruyla (varsayılan **CPU + MKLDNN**, `PP-OCRv6 / small / cpu`) okur ve değişen yeni kutuları tek HTTP isteğiyle (`translate_batch`) topluca çevirip `self._box_lock` üzerinden `BoxTracker`'a işler.
  - **Ön koşul:** PaddleOCR/PaddlePaddle'ın çoklu motor ve paralel tahmin sırasında çakışmaması için `core/ocr_engine.py` içinde global `_INIT_LOCK` ve motor bazlı `_predict_lock`, `core/translation_engine.py` içinde ise `_cache_lock`, `_context_lock` ve thread-local `requests.Session` (`_tls`) eklendi.
  - **Yapılandırılabilirlik:** `Ayarlar → OCR` sekmesinde altyazı ve dünya motorları için tüm sürümler (`PP-OCRv6`, `PP-OCRv5`, `PP-OCRv4`), boyutlar (`tiny`, `small`, `medium`) ve işlem birimleri (`gpu`, `cpu`) bağımsız seçilebilir; `dual_ocr_enabled` kapatılırsa her iki hat aynı motoru paylaşır.

### 2.3. Yüksek Geçiren Altyazı Piksel Kapısı & `text_det_limit_type="max"`
- **Neden:**
  1. PaddleOCR 3.x varsayılan olarak `text_det_limit_type="min"` ve `736` kullanır. Bu da `1088×280` gibi ince altyazı şeritlerini deteksiyon öncesinde **4–6 kat büyütüp** GPU/CPU süresini gereksiz yere uzatıyordu. `core/ocr_engine.py` (`_build_params`) içinde `"text_det_limit_type": "max"`, `"text_det_limit_side_len": 960` ayarlanarak gereksiz büyütme engellendi.
  2. Deniz, ağaç, araba ışığı gibi hareketli arka planlar varken altyazı metni sabit kalsa bile standart kare-farkı eşikleri her karede yeniden OCR tetikliyordu. `has_subtitle_text_changed()` (`core/text_filter.py`) şeridi `160×44` gri tona indirip `|gray - GaussianBlur(gray)|` yüksek geçiren kenar maskesi çıkarır (~1–1.5 ms): altyazı sabitken arka plan hareketini yok sayar, altyazı kaybolduğunda (`has_any_text == False`) ise OCR çalıştırmadan anında altyazı kutularını temizler.

### 2.4. Çoklu Alt-Bant Altyazı Takibi (Simultaneous Dialogue + Objective Prompt)
- **Sorun (GTA 6 ekran görüntülerinde gözlendi):** Bazı sahnelerde aynı anda üstte beyaz konuşma altyazısı (*"It's gross. Plus, sharks. And barracudas..."*) ve onun hemen altında görev cümlesi (*"Collect the package"*) çıkar. Eskiden tek altyazı kutusuna veya tek satıra zorlanınca iki farklı metin birleşiyor ve ne sözlükte eşleşiyor ne de temiz yama yerleşimi veriyordu.
- **Çözüm:**
  - `merge_nearby_boxes` içinde cümle sonu noktalama (`"."`, `"!"`, `"?"`) + büyük harfle başlayan alt satır ve dikey boşluk (`y_gap > min_h * 0.35`) kontrolüyle alt görev satırı konuşmadan ayrıldı.
  - `pipeline.py` tek `_active_sub_box` yerine `self._active_sub_boxes: list[TrackedBox]` tutar; `_process_subtitle_band` alt bölgedeki tüm bağımsız blokları korur, her birine ayrı stil (`bg_color`, `fg_color`) çıkarır ve yerli yerinde yamalar (ör. konuşma beyaz, `"Collect the package"` beyaz/pembe vurguyla kendi konumunda kalır).

### 2.5. Buton İkonu Kırpma, Metin Temizleme ve Akıllı Kutu Birleştirme
Gerçek RDR2 / GTA 6 yayın karelerinde tespit edilip doğrudan giderilen hatalar:
1. **Sağ Alt / Sol Alt Buton İkonlarının Kapanması (`trim_button_icons_from_boxes`):**
   - `PHOTO STUDIO [■]  SELECT (X)  BACK (O)` veya `Photo Mode [:::] Select (X) Back (O)` barlarında OCR bazen ikonu metnin genişliğine dahil ediyor, çeviri yaması da yanındaki buton ikonunun üzerini örtüyordu.
   - `trim_button_icons_from_boxes` iki aşamalı çalışır: (A) OCR tarafından yakalanıp elenen kısa ikon kutularının (`X`, `O`, `R` gibi) koordinatını metin kutusundan keser; (B) kısa HUD/menü etiketlerinin (`<= 3` kelime, `bh <= 38`) sol/sağ ucundaki kare ikon bloklarını (`0.45*bh <= run_w <= 1.12*bh`) `|gray - median(gray)|` sütun kontrast profiliyle (hem koyu üstü açık hem `Map` gibi açık üstü koyu barlarda çalışır) tespit edip kutuyu yalnızca metin alanına daraltır.
2. **Yapışık / Kayıp Satır İçi Buton Metinleri (`clean_ocr_game_text`):**
   - `② Help` → `Help` (baştaki ikon gliflerini temizler)
   - `SELECTX` / `SELECT X` → `SELECT` (buton adına yapışan tek harfli konsol tuşunu atar)
   - `Holdwhile` → `Hold while` (OCR satır içi `(X)` ikonunu atladığında birleşen fiil+bağlacı ayırır)
   - `Use R to select your binoculars` → `Use [R] to select your binoculars` (çıplak kalan analog/buton harfini korur)
3. **Menü, İpucu ve Silah Çarkı Ayrımı (`merge_nearby_boxes`):**
   - Yatayda `> 0.45*min_h` (veya tümü büyük harfken `> 0.25*min_h`) boşluk varsa **yalnızca** sağdaki parça küçük harfle başlıyorsa (`Hold` + `to drop the deer` / `Holdwhile steering`) birleştirir; yan yana barlar (`PHOTO STUDIO`, `SELECT`, `BACK`) birleşmez.
   - Dikeyde iki blok da `<= 2` kelimeyse (`Map`, `Game`, `Store`, `Help`, `Photo Studio`, `Settings`; silah çarkındaki `EMPTY` / `EXPLOSIVES`, `UNARMED` / `IN HAND`) veya üst satır `<= 2` kelimelik başlıksa (`Accelerate` / `Brake and reverse`) dikey birleştirme yapılmaz.
4. **Yayın Filigranı, Para/Sayaç ve Türkçe Metin Filtresi (`is_translatable_game_text`):**
   - Yayın overlay sponsorlarını ve kanal logolarını (`Yemeksepeti`, `SHIRRAKO`, `GTASERIES.COM`, `VI`) atlar.
   - `[ğüşıöçĞÜŞİÖÇ]` içeren halihazırda Türkçe metinleri (ör. yayındaki Türkçe altyazı overlay'ini) tekrar çeviriye sokmaz.
   - `$407`, `4 77`, `0 0`, mini-harita pusula harflerini (`N`, `S`, `W`, `E`) ve `<16×11` gürültü kutularını eler.

### 2.6. Dinamik Boyutlu HUD (`ui/qt/subtitle_view.py` & `ui/qt/hud.py`)
- **Sorun:** `hybrid` ve `subtitle_only` modlarında `Opak` / `Yarı Saydam` arka plan seçildiğinde HUD penceresi tüm sabit dikdörtgeni (`1000×200` vb.) boyadığı için kısa altyazılarda ekranın büyük kısmını boş siyah kutu kaplıyordu.
- **Çözüm:** `SubtitleView.compute_layout()` + `text_box_rect()` aktif sarılmış metnin gerçek piksel genişliğini ve yüksekliğini hesaplar; `HUDWindow.paintEvent()` yalnızca bu dinamik kutuyu çizer (altyazı yokken ve kilitliyken zemin tamamen görünmezdir).

### 2.7. O(1) Normalize DB İndeksi & Varsayılan Kapalı `AutoLearnDB` (`core/db_manager.py`)
- **O(1) DB İndeksi:** 355.000+ satırlı `rdr2_ceviri.db` veritabanında `difflib.get_close_matches` eşleşmeyen her cümlede ~800 ms CPU tüketiyordu. Artık yükleme sırasında tag'siz normalize hash tabloları (`_golden_norm`, `_data_norm`) ve 3 kelimelik ters kova indeksi (`_word_index`) hazırlanır; arama <1.5 ms sürer.
- **Özel İsim / Marka Koruması (`core/llm_chain.py`):** GTA 6 / RDR2 yerelleştirme prompt'ları *Lucia, Jason, Arthur, Vice City, Leonida, Ocean Beach, Sprunk, LifeInvader, Weazel News* gibi özel isimlerin ve `[R1]`, `[E]` tuş etiketlerinin çevrilmesini yasaklar. Ayrıca tek başına özel isim döndüyse (`is_proper_noun`) `PatchOverlayWindow` o yerin üzerine gereksiz yama çizmez.
- **Varsayılan Kapalı `AutoLearnDB`:** Deneyler ve yeni oyun testleri sırasında bozuk veya deneysel OCR çıktılarının yerel `data/translation_cache.db` içine kaydedilip sonraki okumaları kirletmemesi için `auto_learn_enabled` varsayılan olarak **`False`** gelir. Kapalıyken `AutoLearnDB` ne okunur ne yazılır (`_lookup_local` ve `_record_online`). İstenirse `Ayarlar → Çeviri → Otomatik öğrenme` ile açılıp **Öğrenilen önbelleği temizle** butonuyla tek tıkla sıfırlanabilir.

---

## 3. Veri Akışı: İki Paralel İş Parçacığı (Dual-OCR Pipeline)

```text
[Oyun / Capture Card / Pencere Karesi] (20 FPS)
   │
   ├─► Hat 1: nexus-sub-pipeline (Altyazı — GPU Öncelikli)
   │     ├─ auto_subtitle_roi (y=0.72..0.98) veya kullanıcı ROI'si
   │     ├─ has_subtitle_text_changed() [~1.2 ms yüksek geçiren kapı]
   │     │     └─ has_any_text == False → altyazıyı anında temizle (OCR yok)
   │     ├─ OCREngine (self.ocr: varsayılan PP-OCRv6/small/gpu)
   │     ├─ clean_ocr_game_text + trim_button_icons + sample_box_style
   │     └─ TranslationEngine → DB (<1 ms) veya LLMChain SSE (on_partial)
   │
   └─► Hat 2: nexus-world-pipeline (Dünya & Menü — CPU+MKLDNN Öncelikli)
         ├─ Dirty-grid kontrolü + world_scan_interval (0.55s)
         ├─ OCREngine (self.world_ocr: varsayılan PP-OCRv6/small/cpu)
         ├─ Altyazı bandını dışla, ikonları kırp, merge_nearby_boxes
         ├─ BoxTracker (IoU eşleştirme + stabilizasyon + piksel kaybolma kontrolü)
         └─ TranslationEngine.translate_batch() → tek HTTP çağrısında toplu çeviri
               │
               ▼ (self._box_lock altında birleşik çıkış)
   [Çıkış Katmanı — WDA_EXCLUDEFROMCAPTURE aktif]
     ├─ full_patch    → PatchOverlayWindow (Buzlu Cam + Bukalemun Yama)
     ├─ hybrid        → Altyazı: HUDWindow (Dinamik Boyut) | Dünya: PatchOverlayWindow
     └─ subtitle_only → HUDWindow (Dinamik Boyutlu Altyazı)
```

---

## 4. Dosya ve Modül Mimarisi

### Çekirdek (`core/`)
| Dosya | Sorumluluk |
| :--- | :--- |
| `core/config_manager.py` | `DEFAULT_SETTINGS`, `SettingsManager`, `ConfigManager`, `.env` yükleme. |
| `core/capture.py` | `ScreenSource`, `WindowSource` (DPI uyumlu pencere yakalama; üstüne gelen başka pencereleri `_mask_occluders` ile siyaha boyar, %85'ten fazlası kapalıysa kareyi atlar), `CameraSource` (Capture Card). |
| `core/windows.py` | Win32 pencere listeleme, `occluding_rects()` (z-sırasında üstteki pencereler, DWM gerçek çerçevesi) ve `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` koruması. |
| `core/button_icons.py` | OCR kelime kutularından tuş ikonlarını (`R2`, `X`…) bulur, orijinal piksellerini saklar; yama katmanı `[R2]` etiketini bu ikonla satır içi çizer. |
| `core/ocr_engine.py` | `OCREngine` (PP-OCRv4/v5/v6, tiny/small/medium, GPU CUDA + CPU MKLDNN fallback, `_INIT_LOCK` + `_predict_lock`, `text_det_limit_type="max"`) ve `merge_nearby_boxes()`. |
| `core/text_filter.py` | `clean_ocr_game_text`, `is_translatable_game_text`, `split_speaker_prefix`, `is_in_auto_subtitle_zone`, `auto_subtitle_roi`, `has_subtitle_text_changed`, `sample_box_style`, `trim_button_icons_from_boxes`. |
| `core/box_tracker.py` | `TrackedBox` & `BoxTracker`: IoU + metin benzerliği takibi, koordinat yumuşatma, `stabilization_frames` onayı, piksel tabanlı kaybolma kontrolü (`check_disappearances`). |
| `core/pipeline.py` | `TranslationPipeline`: `nexus-sub-pipeline` ve `nexus-world-pipeline` paralel iş parçacıkları, `F7` `process_full_frame(..., is_freeze=True)` tam kare taraması. |
| `core/db_manager.py` | `DBManager` (O(1) normalize hash + 3 kelimelik kova indeksi, atomik yükleme) ve `AutoLearnDB` (`find`, `save`, `clear`, `count`, `set_db`; öğrenilenler seçili oyun DB'sinin `learned_translations` tablosuna yazılır, `is_learnable` çöpü eler). |
| `core/db_catalog.py` | Sözlük kütüphanesi keşfi ve kurulumu (`gta6_ceviri.db`, `rdr2_ceviri.db`, `nexus_golden.db`). |
| `core/llm_chain.py` | `LLMChain`: Groq (`openai/gpt-oss-120b`), EVREN, Gemini zinciri; SSE streaming, oyun yerelleştirme prompt'ları (`SYSTEM_PROMPT`, `BATCH_SYSTEM_PROMPT`), özel isim koruma, 429/503 cooldown yönetimi. |
| `core/translation_engine.py` | `TranslationEngine`: thread-safe LRU bellek cache → Altın/Oyun DB → (açıksa) AutoLearn → LLM/Google/Argos zinciri + `translate_batch()`. |
| `core/chiaki.py` | PS5 Remote Play (Chiaki) otomatik keşfi ve ağ kontrolü. |
| `core/theme.py` | Karanlık tema renkleri, tipografi ve PySide6 QSS kuralları. |

### Arayüz (`ui/qt/`)
| Dosya | Sorumluluk |
| :--- | :--- |
| `ui/qt/app.py` | `QApplication` kurulumu, global kısayol köprüsü (`HotkeyBridge`), pencereleri yakalama dışı tutma döngüsü. |
| `ui/qt/controller.py` | Motor yaşam döngüsü (`_build_ocr`, `_build_world_ocr`, `rebuild_ocr`, `cycle_patch_mode`, `toggle_freeze_scan`). |
| `ui/qt/main_window.py` | Ana kontrol paneli: kaynak/pencere seçimi, yama modu seçici, istatistikler ve `Baslat`/`Durdur`. |
| `ui/qt/patch_overlay.py` | `PatchOverlayWindow`: tüm ekranı kaplayan, tıklama geçirgen, DPI-duyarlı Buzlu Cam + Bukalemun yama ve `F7` Dondur rozeti çizicisi. |
| `ui/qt/hud.py` & `ui/qt/subtitle_view.py` | Dinamik metin boyutuna göre daralıp genişleyen altyazı HUD penceresi, sürükle-bırak ve kilit (`F8`). |
| `ui/qt/settings_window.py` | Görünüm, Bağımsız 1. Altyazı / 2. Dünya OCR ayarları, Çeviri (AutoLearn aç/kapat + önbellek temizle + API anahtarları) ve Kısayollar. |
| `ui/qt/roi_selector.py`, `dictionary_window.py`, `chiaki_window.py`, `onboarding.py` | Bölge seçimi, sözlük yöneticisi, Chiaki PS5 kurulumu ve ilk kullanım sihirbazı. |

### Veri & Yapılandırma (`config/`, `data/`, `tools/`)
- `config/settings.json`: Kalıcı kullanıcı ayarları (**Not:** API anahtarları repoya boş string olarak commit edilir; kendi anahtarlarınızı Ayarlar arayüzünden veya `.env` üzerinden girin).
- `config/profiles.json` & `config/dictionaries.json`: Kaydedilmiş ROI profilleri ve sözlük kataloğu.
- `data/`: Oyun sözlük veritabanları (`rdr2_ceviri.db`, `gta6_ceviri.db`, `nexus_golden.db`) ve çalışma zamanı önbelleği (`translation_cache.db`, `.gitignore` ile hariç tutulur).
- `data/gta6/`: GTA 6 karakter defteri (`characters.json`), terim sözlüğü (`glossary.json`), video'dan üretilen satırların tabloları (`tablo_*.md`) ve inceleme listeleri (`inceleme_*.md`).
- `tools/video_to_db/`: YouTube oynanış videosundan GTA 6 sözlüğü üreten araç (Gemini Göz + PaddleOCR + iki çevirmen + hakem). Ayrıntı: [tools/video_to_db/README.md](tools/video_to_db/README.md).
- `packaging/`: PyInstaller tek klasör paket (`build.ps1`, `nexus.spec`) ve son kullanıcı kurulum rehberi (`KURULUM.md`).
- `tests/`: tuş etiketi, satır içi ikon ve gerçek kare testleri (betik olarak veya `pytest` ile).
- Ajan talimatları: [AGENTS.md](AGENTS.md) (tek doğru kaynak), `CLAUDE.md` / `GEMINI.md` (AGENTS.md'ye yönlendirir), Antigravity için `.agents/rules/00-nexus-proje.md` ve `.agents/workflows/`.

---

## 5. Ayarlar (`config/settings.json`) & Kısayol Tuşları

### Varsayılan Kısayollar
| Tuş | İşlev |
| :--- | :--- |
| **`F6`** | Yama modunu değiştir (`full_patch` → `hybrid` → `subtitle_only`) |
| **`F7`** | Anlık Dondur & Oku aç/kapat (tüm ekranı yüksek çözünürlükte sabitler ve çevirir) |
| **`F8`** | HUD kilidi (tıklama geçirgenliğini aç/kapat) |
| **`F9`** | Çeviriyi Başlat / Durdur |
| **`F10`** | Ekrandan yeni bölge (ROI) seç |
| **`F11`** | Ayarlar penceresini aç |
| **`F12`** | Uygulamadan güvenli çıkış |

### Önemli v3 Ayar Anahtarları (`core/config_manager.py`)
```json
{
  "patch_mode": "full_patch",
  "auto_subtitle_detect": true,
  "chameleon_opacity": 78,
  "auto_text_color": true,
  "stabilization_frames": 2,
  "world_scan_interval": 0.55,
  "dual_ocr_enabled": true,
  "paddle_version": "PP-OCRv6",
  "ocr_model_size": "small",
  "ocr_device": "gpu",
  "world_paddle_version": "PP-OCRv6",
  "world_ocr_model_size": "small",
  "world_ocr_device": "cpu",
  "use_mkldnn": true,
  "auto_learn_enabled": false
}
```
> DB olmadan saf AI modunda çalıştırmak için Ayarlar/Sözlük üzerinden veritabanını `"Yok"` (`db_path: ""`) veya `data/gta6_ceviri.db` seçebilirsiniz.

---

## 6. Bilinen Donanım / PaddleOCR Notları & Kurulum

1. **PaddlePaddle 3.3.x oneDNN/PIR Hatası:**
   - `paddlepaddle>=3.3.0` sürümlerinde CPU MKLDNN açıkken `ConvertPirAttribute2RuntimeAttribute` hatası oluşabiliyor.
   - `OCREngine` bu hatayı ilk ön-ısınma (`_dummy_image()`) sırasında yakalayıp otomatik düz CPU moduna düşer; kalıcı olarak yüksek CPU MKLDNN hızı almak için **`paddlepaddle==3.2.2`** kullanın.
2. **GPU (CUDA / cuDNN 9) Kurulumu:**
   - Windows'ta GPU OCR için `paddlepaddle-gpu==3.2.2` ve `nvidia-cudnn-cu12`, `nvidia-cublas-cu12` paketleri gereklidir (`core/ocr_engine.py`, Windows `os.add_dll_directory` ile NVIDIA site-packages DLL yollarını otomatik ekler). GPU bulunamazsa otomatik CPU fallback yapılır.
3. **API Anahtarları & Güvenlik:**
   - Groq (`GROQ_API_KEY`) ve Gemini (`GEMINI_API_KEY`) anahtarları `.env` dosyasında veya yerel `config/settings.json` içinde tutulabilir; `.env` `.gitignore` ile korunur.
