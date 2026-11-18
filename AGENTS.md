# NEXUS AI v2 — Ajan Notları

Bu dosya projede çalışan AI ajanları (ve geliştirici) için yapılacaklar/notlar listesidir.

## Yapılacaklar (TODO)

- [ ] **`rapidocr` paketini kaldır.** Denemek için global Python ortamına kuruldu ama projede kullanılmıyor
  (`python -m pip uninstall rapidocr`). Şimdilik kalsın, kullanıcı onayı olmadan silme.
  - Not: RapidOCR CPU'da PaddleOCR'dan yavaş çıktı (v6-tiny 577 ms, v6-small 950 ms; Paddle v5 ~300 ms).
    Ancak GPU (onnxruntime-directml) ile denenmedi.

## Kararlar / Ölçümler

- OCR: PaddleOCR 3.7.0 + `PP-OCRv6` small modeller (~110 ms) seçilebilir. Varsayılan hâlâ `PP-OCRv5`.
  Gerçek oyun karelerinde doğruluk testi sonrası varsayılan v6 yapılabilir (`core/config_manager.py`).
- Çeviri: DB'siz oyunlar için hızlı LLM sağlayıcıları (Cerebras → Groq → Gemini) FreeLLMAPI ile planlanıyor.
  Reklam edilen gecikmeler (50-120 ms) yerel ağda ölçülmeden doğru kabul edilmemeli.
