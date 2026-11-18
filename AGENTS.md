# NEXUS AI (v2 / v3) — Ajan Notları ve Mimari Kurallar

Bu dosya projede çalışan AI ajanları (ve geliştirici) için mimari özet, değişmez kurallar ve yapılacaklar listesini içerir.

## Mevcut Mimari Özet (v3 Canlı Yama & Paralel Çift OCR)

Detaylı gerekçe ve dosya haritası için [README.md](README.md) dosyasına bakın.

- **İki Paralel İş Parçacığı (`core/pipeline.py`):**
  - `nexus-sub-pipeline` (`_loop` / `_tick`): Alt-orta altyazı bandını (`auto_subtitle_roi`, `y=0.72..0.98`) `has_subtitle_text_changed()` (~1.2 ms yüksek geçiren kapı) üzerinden denetler ve değişince birincil `self.ocr` (varsayılan `PP-OCRv6 / small / gpu`) + Groq SSE (`on_partial`) ile çevirir. Dünya/menü çevirisi tarafından asla bloklanmaz.
  - `nexus-world-pipeline` (`_world_loop` / `_process_world_pass`): Menü, ipucu ve buton barlarını `world_scan_interval` aralığında ayrı `self.world_ocr` (varsayılan `PP-OCRv6 / small / cpu` + MKLDNN) ve `translate_batch()` ile çevirip `self._box_lock` üzerinden `BoxTracker`'a yazar.
- **Değişmez Kurallar (Invariants):**
  1. **Çoklu Motor & Thread Güvenliği:** `OCREngine` için global `_INIT_LOCK` + örnek bazlı `_predict_lock`; `TranslationEngine` için `_cache_lock`, `_context_lock` ve thread-local `requests.Session` (`_tls`) korunmalıdır.
  2. **MKLDNN Log & Params:** `enable_mkldnn` yalnızca `self.device == "cpu"` iken aktiftir (`_build_params` ve `_ensure_initialized` logu GPU'da `mkldnn=False` gösterir).
  3. **Buton İkonu ve Menü Ayrımı (`core/text_filter.py` & `core/ocr_engine.py`):**
     - `trim_button_icons_from_boxes()` hem OCR'ın elediği tekil tuş kutularını (`X`, `O`, `R`) hem de kısa barların ucundaki kare ikonları (`|gray - median|`) kırpmalıdır.
     - `merge_nearby_boxes()` yatayda büyük harfle başlayan ayrı butonları (`PHOTO STUDIO`, `SELECT`, `BACK`), dikeyde ise `<= 2` kelimelik menü/silah çarkı satırlarını (`Map`, `Game`, `EMPTY`/`EXPLOSIVES`, `UNARMED`/`IN HAND`, `Accelerate`/`Brake and reverse`) veya nokta sonrası ayrı görev satırlarını (`It's gross...` / `Collect the package`) birleştirmemelidir.
     - `is_translatable_game_text()` yayın filigranlarını (`Yemeksepeti`, `SHIRRAKO`, `GTASERIES.COM`, `VI`) ve `[ğüşıöçĞÜŞİÖÇ]` içeren halihazırda Türkçe metinleri elemelidir.
  4. **AutoLearn Varsayılan Kapalı (`auto_learn_enabled: False`):**
     - Kapalıyken `TranslationEngine._lookup_local()` `AutoLearnDB.find()` okumaz, `_record_online()` da `AutoLearnDB.save()` yazmaz.
     - Kullanıcı Ayarlar > Çeviri sekmesinden açıp `btn_clear_learn` ile `data/translation_cache.db` önbelleğini sıfırlayabilir.
  5. **WDA_EXCLUDEFROMCAPTURE:** Tüm overlay/HUD/ayar pencereleri (`PatchOverlayWindow`, `HUDWindow`, `MainWindow`) ekran yakalamadan gizlenmelidir (`ui/qt/app.py`, `core/windows.py`).
  6. **Güvenlik / Gizlilik:** `config/settings.json` içinde `groq_api_key`, `gemini_api_key`, `evren_api_key` repoya daima `""` olarak commit edilmelidir; kullanıcı anahtarları yalnızca yerel diskte veya `.env` dosyasında kalır.

## Yapılacaklar (TODO)

- [ ] **`rapidocr` paketini kaldır.** Denemek için global Python ortamına kuruldu ama projede kullanılmıyor
  (`python -m pip uninstall rapidocr`). Şimdilik kalsın, kullanıcı onayı olmadan silme.
  - Not: RapidOCR CPU'da PaddleOCR'dan yavaş çıktı (v6-tiny 577 ms, v6-small 950 ms; Paddle v5 ~300 ms).
    Ancak GPU (onnxruntime-directml) ile denenmedi.

## Kararlar / Ölçümler

- OCR: PaddleOCR 3.7.0 + `PP-OCRv6` small modeller (~110 ms) seçilebilir. Varsayılan GPU `PP-OCRv6/small` (Altyazı) + CPU+MKLDNN `PP-OCRv6/small` (Dünya/Menü) paralel kurgudur (`core/config_manager.py`). Ayarlar > OCR sekmesinden `PP-OCRv4`/`v5`/`v6` ve `tiny`/`small`/`medium` ile `cpu`/`gpu` bağımsız değiştirilebilir.
- `text_det_limit_type="max"`, `text_det_limit_side_len=960`: İnce altyazı şeritlerinin PaddleX tarafından 4–6 kat büyütülmesini önlemek için sabitlenmiştir.
- Çeviri: DB'siz oyunlar (GTA 6 + Capture Card / Konsol akışı) için paralel GPT-OSS / Groq SSE akışı → EVREN → Gemini zinciri (`core/llm_chain.py`) kullanılır. Reklam edilen gecikmeler (50-120 ms) yerel ağda ölçülmeden doğru kabul edilmemelidir.
- Veritabanı İndeksi (`core/db_manager.py`): Tag'siz O(1) normalize hash tabloları + 3 kelimelik ters kova indeksi (<1.5 ms arama).
