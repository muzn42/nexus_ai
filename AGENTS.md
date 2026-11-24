# NEXUS AI (v2 / v3) — Ajan Notları ve Mimari Kurallar

Bu dosya projede çalışan AI ajanları (Antigravity / Gemini, Claude Code, Codex…) ve geliştirici için **tek doğru kaynaktır**:
mimari özet, değişmez kurallar, güncel durum ve yapılacaklar. Uzun gerekçeler ve dosya haritası [README.md](README.md) içindedir.
Video'dan GTA 6 sözlüğü üreten araç için: [tools/video_to_db/README.md](tools/video_to_db/README.md).

> Dil: Kullanıcıyla **Türkçe** konuşulur. Kod yorumları ve log mesajları da Türkçedir.

## 0. Hızlı Bakış

| Ne | Nerede |
| :--- | :--- |
| Uygulamayı çalıştır | `python main.py` (PySide6, Windows; proje kökünden) |
| Testler | `python tests/test_button_icons.py`, `python tests/test_button_tags.py`, `python tests/test_real_frames.py` (veya `pytest tests/`) |
| Paketleme (tek klasör exe) | `packaging/build.ps1` → `packaging/dist/` ; son kullanıcı kurulumu `packaging/KURULUM.md` |
| Ayarlar | `config/settings.json` (varsayılanlar `core/config_manager.py → DEFAULT_SETTINGS`) |
| Oyun sözlükleri | `data/gta6_ceviri.db`, `data/rdr2_ceviri.db`, `data/nexus_golden.db` |
| GTA 6 bağlam dosyaları | `data/gta6/characters.json`, `data/gta6/glossary.json`, raporlar `data/gta6/tablo_*.md`, `inceleme_*.md` |
| Video → DB aracı | `python -m tools.video_to_db run ...` (bkz. araç README'si) |
| Geçici/ağır çalışma dosyaları | `temp_subs/` (gitignore'lu: videolar, OCR/Gemini ara JSON'ları, hakem paketleri) |

## 1. Mevcut Mimari Özet (v3 Canlı Yama & Paralel Çift OCR)

- **İki Paralel İş Parçacığı (`core/pipeline.py`):**
  - `nexus-sub-pipeline` (`_loop` / `_tick`): Alt-orta altyazı bandını (`auto_subtitle_roi`, `y=0.72..0.98`) `has_subtitle_text_changed()` (~1.2 ms yüksek geçiren kapı) üzerinden denetler ve değişince birincil `self.ocr` (varsayılan `PP-OCRv6 / small / gpu`) + Groq SSE (`on_partial`) ile çevirir. Dünya/menü çevirisi tarafından asla bloklanmaz.
  - `nexus-world-pipeline` (`_world_loop` / `_process_world_pass`): Menü, ipucu ve buton barlarını `world_scan_interval` aralığında ayrı `self.world_ocr` (varsayılan `PP-OCRv6 / small / cpu` + MKLDNN) ve `translate_batch()` ile çevirip `self._box_lock` üzerinden `BoxTracker`'a yazar.
- **Çeviri sırası (`core/translation_engine.py`):** bellek LRU → Altın/Oyun DB (`DBManager`, <1.5 ms) → (açıksa) AutoLearn → LLM zinciri (`core/llm_chain.py`: Groq GPT-OSS SSE → EVREN → Gemini) / Google / Argos.
- **Yakalama (`core/capture.py`):** `ScreenSource` (bölge yakalama), `WindowSource` (seçili pencerenin istemci alanı, her karede yeniden ölçülür), `CameraSource` (capture card). GTA 6 kurulumu: PS5 → PotPlayer penceresi, `full_patch` modu.
- **Satır içi tuş ikonları (`core/button_icons.py` + `ui/qt/patch_overlay.py`):** OCR kelime kutularından `R2`, `X` gibi tuşları bulur, orijinal ikon piksellerini `box["icons"]` içinde saklar; yama katmanı Türkçe metindeki `[R2]` etiketinin yerine bu ikonu satır içi çizer.

## 2. Değişmez Kurallar (Invariants)

1. **Çoklu Motor & Thread Güvenliği:** `OCREngine` için global `_INIT_LOCK` + örnek bazlı `_predict_lock`; `TranslationEngine` için `_cache_lock`, `_context_lock` ve thread-local `requests.Session` (`_tls`) korunmalıdır.
2. **MKLDNN Log & Params:** `enable_mkldnn` yalnızca `self.device == "cpu"` iken aktiftir (`_build_params` ve `_ensure_initialized` logu GPU'da `mkldnn=False` gösterir).
3. **Buton İkonu ve Menü Ayrımı (`core/text_filter.py` & `core/ocr_engine.py`):**
   - `trim_button_icons_from_boxes()` hem OCR'ın elediği tekil tuş kutularını (`X`, `O`, `R`) hem de kısa barların ucundaki kare ikonları (`|gray - median|`) kırpmalıdır.
   - `merge_nearby_boxes()` yatayda büyük harfle başlayan ayrı butonları (`PHOTO STUDIO`, `SELECT`, `BACK`), dikeyde ise `<= 2` kelimelik menü/silah çarkı satırlarını (`Map`, `Game`, `EMPTY`/`EXPLOSIVES`, `UNARMED`/`IN HAND`, `Accelerate`/`Brake and reverse`) veya nokta sonrası ayrı görev satırlarını (`It's gross...` / `Collect the package`) birleştirmemelidir. Birleştirirken kelime kutularını (`words`) korur (ikon çizimi buna dayanır).
   - `is_translatable_game_text()` yayın filigranlarını (`Yemeksepeti`, `SHIRRAKO`, `GTASERIES.COM`, `VI`) ve `[ğüşıöçĞÜŞİÖÇ]` içeren halihazırda Türkçe metinleri elemelidir.
4. **AutoLearn varsayılan kapalı ve OYUNA ÖZEL (`core/db_manager.py → AutoLearnDB`):**
   - `auto_learn_enabled: False` varsayılandır. Kapalıyken `TranslationEngine._lookup_local()` `AutoLearnDB.find()` okumaz, `_record_online()` da `AutoLearnDB.save()` yazmaz.
   - Açıkken öğrenilenler **seçili oyun DB'sinin içindeki `learned_translations` tablosuna** yazılır (ör. `data/gta6_ceviri.db`). Böylece GTA 6'da öğrenilen bir satır başka oyunda hiç aranmaz. Oyun DB'si seçili değilse `data/translation_cache.db` kullanılır.
   - `ui/qt/controller.py → set_dictionary()` sözlük değişince `auto_learn.set_db(...)` çağırır ve çeviri önbelleğini (`translator._cache`, `_cache_lock` altında) temizler.
   - `is_learnable(source, target)` çöpü eler: 4 karakterden kısa ya da 3'ten az harfli kaynak, mesafe/sayı (`120 m`, `3.4 mi`), kaynağa eş hedef, Türkçe harf içeren kaynak, neredeyse aynı kaynak/hedef, dosya yolu/URL. Bu filtre gevşetilmemelidir.
   - Ayarlar > Çeviri sekmesinden açılıp `btn_clear_learn` ile o oyunun öğrenilenleri sıfırlanabilir.
5. **WDA_EXCLUDEFROMCAPTURE:** Tüm overlay/HUD/ayar pencereleri (`PatchOverlayWindow`, `HUDWindow`, `MainWindow`) ekran yakalamadan gizlenmelidir (`ui/qt/app.py`, `core/windows.py`).
6. **Pencere kaynağında üstteki pencereler maskelenir (`core/capture.py → WindowSource._mask_occluders`, `core/windows.py → occluding_rects`):**
   - Pencere yakalama aslında ekran bölgesi yakaladığı için, seçili pencerenin üstüne gelen başka pencereler de okunuyordu. Artık z-sırasında üstteki pencereler (`GW_HWNDPREV`, DWM gerçek çerçevesi) bulunup karede **siyaha boyanır**; bölgenin %85'inden fazlası kapalıysa kare atlanır.
   - Kendi süreç pencereleri, hedefin kendi süreci, görünmez / cloaked / `WS_EX_TRANSPARENT` pencereler sayılmaz. Maliyet ~0.05–0.3 ms. Bu davranış kaldırılmamalıdır.
7. **Güvenlik / Gizlilik:**
   - `config/settings.json` içinde `groq_api_key`, `gemini_api_key`, `evren_api_key` repoya daima `""` olarak commit edilmelidir; kullanıcı anahtarları yalnızca yerel diskte veya `.env` dosyasında kalır.
   - API anahtarları **asla** ekrana, log'a, rapora veya commit mesajına basılmaz. Anahtar dosyası (ör. `--key-file` ile verilen metin dosyası) kopyalanmaz, içeriği yazdırılmaz.
   - `data/gta6/backups/`, `temp_subs/`, `.env`, `.agents/` gitignore'ludur; buralara anahtar yazılmaz.
8. **Oyun DB şeması değişmez:** `DBManager` yalnızca `translations(source_text PRIMARY KEY, target_text)` tablosunu okur. Ek bilgiler (tür, konuşan, sahne, video/zaman, hakem seçimi, adaylar, renkli kelimeler) `video_entries` tablosunda tutulur ve arama hızını etkilemez. Bu araçların yazmadığı mevcut satırların üzerine yazılmaz (çakışma olarak raporlanır).

## 3. Güncel Durum (2026-11-25)

- **`data/gta6_ceviri.db`:** 27.683 `translations` satırı.
  - `video_entries.part = 'part1'`: 3.472 satır (YouTube `YDNs_sPEcJc`, oyunda test edildi).
  - `video_entries.part = 'full'`: 24.180 satır (tam oyun videosu `Ve2M5i_DSKI`, 3:40:00'dan sonrası). Adaylar: `gemini-3.8-flash` (A) + `gemini-4-hydrogen` (B, satırların ~%60'ında). Gemini kredisi bittiği için hakemliği Gemini Neon yerine **Claude** yaptı (A 23.256 / B 1.066 / kendi düzeltmesi 723 / atlanan 223).
  - `learned_translations`: GTA 6 için temizlenmiş, taşınmış AutoLearn kayıtları.
- **İnceleme listesi:** `data/gta6/inceleme_full.md` — çoğu satır yalnız bilgi notu taşır ("tek aday" = hydrogen yoktu). Gerçekten bakılması gerekenler: "yalnız OCR gördü", "altyazı uzun", "hakem emin değil".
- **DB yedekleri:** her yazımdan önce `data/gta6/backups/gta6_ceviri.db.<tarih>.bak`.
- **Kullanıcının çeviri üslubu:** anlam önce; İngilizce deyim/argo varsa en uygun Türkçe deyim; düz satır düz kalır, zorlama deyim/atasözü hatadır; her satır önceki konuşmaya uymalı (cevap, espri, bölünmüş kart); küfür ve ton aynı şiddette.

## 4. Yapılacaklar (TODO)

- [ ] **`rapidocr` paketini kaldır.** Denemek için global Python ortamına kuruldu ama projede kullanılmıyor
  (`python -m pip uninstall rapidocr`). Şimdilik kalsın, kullanıcı onayı olmadan silme.
  - Not: RapidOCR CPU'da PaddleOCR'dan yavaş çıktı (v6-tiny 577 ms, v6-small 950 ms; Paddle v5 ~300 ms).
    Ancak GPU (onnxruntime-directml) ile denenmedi.
- [ ] Renkli kelime (highlight) bilgisini (`video_entries.highlights`) yama katmanında Türkçe metinde renkli çizmek.
- [ ] `temp_subs/video/` altındaki büyük videoları (≈55 GB) kullanıcı onayıyla temizlemek.

## 5. Kararlar / Ölçümler

- OCR: PaddleOCR 3.7.0 + `PP-OCRv6` small modeller (~110 ms) seçilebilir. Varsayılan GPU `PP-OCRv6/small` (Altyazı) + CPU+MKLDNN `PP-OCRv6/small` (Dünya/Menü) paralel kurgudur (`core/config_manager.py`). Ayarlar > OCR sekmesinden `PP-OCRv4`/`v5`/`v6` ve `tiny`/`small`/`medium` ile `cpu`/`gpu` bağımsız değiştirilebilir.
- `text_det_limit_type="max"`, `text_det_limit_side_len=960`: İnce altyazı şeritlerinin PaddleX tarafından 4–6 kat büyütülmesini önlemek için sabitlenmiştir.
- Çeviri: DB'siz oyunlar (GTA 6 + Capture Card / Konsol akışı) için paralel GPT-OSS / Groq SSE akışı → EVREN → Gemini zinciri (`core/llm_chain.py`) kullanılır. Reklam edilen gecikmeler (50-120 ms) yerel ağda ölçülmeden doğru kabul edilmemelidir.
- Groq ücretsiz katmanı (`openai/gpt-oss-120b`): dakikada 8K token. Canlı oyun çevirisi buna dayanır; toplu (binlerce satırlık) işler için Groq kullanılmamalıdır.
- Veritabanı İndeksi (`core/db_manager.py`): Tag'siz O(1) normalize hash tabloları + 3 kelimelik ters kova indeksi (<1.5 ms arama).
- Video → DB: OCR gereklidir (Gemini'nin yazdığı metin OCR anahtarıyla %23 oranında eşleşmiyor; DB anahtarı oyunda OCR'ın okuduğu metin olmalı). Gemini YouTube ofsetlerini ~59.877 sn (16,6 saat) sonrasında reddeder; uzun videoların kalanı yerel kliplerden Files API ile işlenir.
