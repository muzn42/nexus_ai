# tools/video_to_db — Oynanış Videosundan GTA 6 Türkçe Sözlüğü

GTA 6 için hazır çeviri veritabanı yoktur. Bu araç bir YouTube oynanış videosundan oyunun ekrana yazdığı
İngilizce metinleri (altyazı, görev, ipucu, menü, HUD) çıkarır, bağlamıyla birlikte Türkçeye çevirir ve
`data/gta6_ceviri.db` dosyasına yazar. Canlı uygulama bu DB'yi `DBManager` ile <1.5 ms'de arar.

## Aşamalar

| # | Aşama | Modül | Çıktı (`--work` klasöründe) |
|---|---|---|---|
| 1 | **Göz**: Gemini videoyu izler; zaman damgalı yazı, tür, konuşan/dinleyen, ton, sahne, renkli kelimeler | `gemini_eye.py` (YouTube linki), `gemini_files.py` (yerel klip + Files API) | `eye.json` |
| 2 | **OCR**: PaddleOCR ile videonun kendisi okunur (DB anahtarı oyunda OCR'ın göreceği metin olmalı) | `ocr_scan.py` | `ocr_raw.json`, `ocr.json`, `ocrw_seg_*.json` |
| 3 | **Eşleme**: OCR satırları Göz olaylarıyla zamana/metne göre eşlenir, bağlam OCR anahtarına taşınır | `align.py` | `aligned.json` |
| 4 | **Çeviri**: sahneler iki modelle bağımsız çevrilir (A: `gemini-3.8-flash`, B: `gemini-4-hydrogen`); hakem (`gemini-4-neon`) sahneyi konuşma olarak okuyup seçer ya da kendisi düzeltir | `translator.py` | `translated.json` |
| 5 | **Yazma**: `translations` + `video_entries` tabloları; önce yedek | `db_writer.py` | `report.json`, `data/gta6/tablo_<part>.md`, `data/gta6/inceleme_<part>.md` |

Bağlam dosyaları: `data/gta6/characters.json` (karakter defteri, sen/siz ilişkileri) ve `data/gta6/glossary.json`
(çevrilmeyen adlar `degismez`, sabit arayüz terimleri `terimler`, tuş kalıpları). Çevirmenin önerdiği yeni terimler
`oneriler` / `yeni_konusmacilar` altına eklenir; insan onayıyla asıl listelere taşınmalıdır.

## Çalıştırma

Proje kökünden:

```powershell
python -m tools.video_to_db run --url "https://www.youtube.com/watch?v=<ID>" `
  --video temp_subs/video/<dosya>.mp4 --video-offset 0 --start <sn> --end <sn> `
  --part <ad> --work temp_subs/<ad>_work --batch --fps 2 --ocr-mode eye --dry-run
```

- `--batch`: Gemini Batch API (yarı fiyat, asenkron). Gönderilen batch adları `work/batches/` altında saklanır; komutu yeniden çalıştırmak kaldığı yerden sürer, aynı işi ikinci kez göndermez.
- `--ocr-mode eye`: OCR yalnız Gemini'nin yazı gördüğü anların ±5 sn'sini tarar (uzun videolarda zorunlu). `full` tüm videoyu tarar.
- `--key-file`: anahtar bu metin dosyasından okunur (yazdırılmaz). Verilmezse `config/settings.json` / `.env` içindeki `gemini_api_key` kullanılır.
- `--dry-run`: DB'ye yazmaz, yalnız raporları üretir. Alt komutlar: `eye`, `ocr`, `translate`, `write` (her adım ara JSON'u yeniden kullanır; `--force` yeniden hesaplar).
- Video indirme (OCR için yalnız görüntü yeterli): `yt-dlp -f 299 --download-sections "*HH:MM:SS-HH:MM:SS" -o parca.mp4 <URL>`.

## Bilinen Sınırlar ve Çözümler

- **YouTube ofset sınırı:** Gemini, YouTube linkinde ~59.877 sn'den (16,6 saat) sonraki ofsetleri `INVALID_ARGUMENT` ile reddeder.
  Kalan kısım yerel videodan 30 dk'lık sessiz 720p kliplere (NVENC) kesilip Files API ile yüklenir (`gemini_files.run_eye_files`);
  klipler iş bitince Gemini'den silinir. Sessiz klip olduğu için bu kısımda konuşan bilgisi daha zayıftır.
- **Batch sınırları:** bir batch ≤300 istek / ≤12 MB; büyük işler parçalara bölünüp aynı anda gönderilir.
- **`HTTP 402 RESOURCE_EXHAUSTED`:** Gemini ön ödemeli kredisi bitti. İş durur; kayıtlı batch'ler kaybolmaz, kredi yüklenince aynı komut kaldığı yerden sürer.
- **Groq'a geçme:** Groq ücretsiz katmanı dakikada 8K token verir ve canlı oyun çevirisini besler; toplu iş için uygun değildir.
- **DB koruması:** başka bir videodan (`video_entries.video_id` farklı) gelen satırların üzerine yazılmaz (`kept_other_video`); aracın yazmadığı mevcut satırlar çakışma olarak raporlanır.
- **OCR neden şart:** Gemini'nin yazdığı metin, oyunda OCR'ın okuyacağı metinle satırların ~%23'ünde birebir tutmaz; DB anahtarı OCR metni olmalıdır.

## Kredisiz Bitiriş (2026-11 tam oyun işi)

Tam oyun videosunda (`Ve2M5i_DSKI`, `--part full`) Gemini kredisi çeviri aşamasında bitti: A adayları tamamdı,
B adayları ~%60'tı, hakem hiç çalışmamıştı. Şu yol izlendi (betikler `temp_subs/full_work/` içinde, gitignore'lu):

1. `fetch_cands.py` — kayıtlı batch'lerin sonuçlarını kredi harcamadan çeker → `cands.json` (sahneler + A/B adayları).
2. `make_judge_chunks.py` — sahneleri ~1.200 satırlık metin paketlerine böler → `judge/in_XX.txt`; hakem talimatı `judge/TALIMAT.md`.
3. Hakemlik Claude alt ajanlarıyla yapıldı; her paket yalnız A'dan farklı kararları `judge/out_XX.jsonl` dosyasına yazar
   (`{"id": N, "pick": "B"}`, `{"id": N, "pick": "C", "final": "...", "why": "..."}`, `{"id": N, "skip": true}`).
4. `finalize.py [--dry-run]` — kararları adaylarla birleştirir, `code_checks` teknik denetimini uygular, raporları ve DB'yi yazar.

Aynı yöntem başka bir LLM ile de uygulanabilir: yalnız 3. adımdaki hakem değişir, girdi/çıktı biçimi aynı kalır.
