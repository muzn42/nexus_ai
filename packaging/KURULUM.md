# NEXUS AI — Başka Bilgisayara Kurulum

Python veya başka bir şey kurmanız **gerekmez**. Her şey (Python, PaddleOCR, CUDA/cuDNN, OCR modelleri, sözlükler) paketin içindedir.

## 1. Kurulum

1. `NEXUS-AI-<tarih>-win64.zip` dosyasını **yazılabilir** bir klasöre çıkarın, örn. `D:\Oyunlar\NEXUS AI` veya Masaüstü.
   - `C:\Program Files` içine çıkarmayın. Çıkarırsanız da çalışır, ancak ayarlarınız ve önbellek `%APPDATA%\NEXUS AI` klasörüne yazılır.
   - Klasör yolunda Türkçe karakter olabilir. Yine de sorun yaşarsanız `D:\NEXUS AI` gibi basit bir yol deneyin.
2. `NEXUS AI\NEXUS AI.exe` dosyasını çalıştırın.
   - Windows SmartScreen "Windows bilgisayarınızı korudu" uyarısı verirse **Ek bilgi → Yine de çalıştır** seçin. Exe imzasız olduğu için bu uyarı normaldir.
3. İlk açılışta tanıtım ekranı gelir; çeviri motoru olarak Groq'u seçin. Sonra `F11` (Ayarlar) → **Çeviri** → **API anahtarları** → **Groq** alanına anahtarınızı girin (ücretsiz: https://console.groq.com/keys).
   - Anahtar paketin içinde **gelmez**. Her kullanıcı kendi anahtarını girer.
   - İsterseniz exe'nin yanına `.env` dosyası koyabilirsiniz: `GROQ_API_KEY=gsk_...`

## 2. Ekran kartı (GPU / CPU)

Tek bir paket hem NVIDIA'lı hem NVIDIA'sız bilgisayarda çalışır:

| Bilgisayar | Ne olur? |
| :--- | :--- |
| NVIDIA RTX / GTX (ör. RTX 4050) | Altyazı OCR'ı GPU'da çalışır (~100 ms). |
| NVIDIA yok / AMD / Intel | OCR otomatik olarak CPU'ya geçer. Daha yavaştır ama çalışır. |

- NVIDIA kullanıyorsanız **ekran kartı sürücüsünü güncelleyin**. En az 528, tercihen 576 veya üstü bir sürüm kullanın (GeForce Experience / NVIDIA App → Sürücüler). Ayrıca CUDA Toolkit kurmanız **gerekmez**.
- Hangi cihazın kullanıldığını `logs\nexus.log` içindeki `[OCR] PaddleOCR hazır (... device=gpu ...)` satırından görebilirsiniz.
- Ayarlar → OCR sekmesinden altyazı ve dünya motorlarını ayrı ayrı `gpu`/`cpu` ve `tiny`/`small`/`medium` olarak değiştirebilirsiniz. Zayıf bir CPU'da dünya motorunu `tiny` yapmak hız kazandırır.

## 3. Kullanım (kısa)

- `F9` başlat/durdur · `F6` mod değiştir (Tam Yama / Hibrit / Sadece Altyazı) · `F7` dondur ve oku
- `F8` kilit · `F10` alanı yeniden seç · `F11` ayarlar · `F12` çıkış
- PS5 + capture card: Görüntüyü PotPlayer/OBS önizlemesinde açın. NEXUS AI'da kaynak olarak **Pencere** seçip o pencereyi gösterin.

## 4. Dosyalar nerede?

| Klasör | İçerik |
| :--- | :--- |
| `config\settings.json` | Ayarlarınız ve API anahtarınız (sadece sizin bilgisayarınızda) |
| `data\` | Öğrenme önbelleği (`translation_cache.db`). Sözlük DB'leri pakette yoktur; çeviri AI (Groq) ile yapılır. İsterseniz bir `.db` sözlüğünü buraya kopyalayıp Ayarlar'dan seçebilirsiniz. |
| `logs\nexus.log` | Son çalıştırmanın günlüğü (`nexus.log.1` bir öncekinin) |
| `_internal\` | Programın kendisi. **Dokunmayın.** |

Güncelleme yaparken yeni zip'i aynı yere çıkarın ve `_internal` klasörünün üzerine yazın. `config` ve `data` klasörlerinizi korumak isterseniz bu ikisini yeni dosyalarla değiştirmeyin.

## 5. Sorun giderme

- **Program açılmıyor / hemen kapanıyor:** `NEXUS AI (Konsol).exe` dosyasını çalıştırın. Hata mesajı konsolda görünür. Ayrıca `logs\nexus.log` dosyasına bakın.
- **Çeviri gelmiyor:** API anahtarını Ayarlar → Çeviri sekmesinden kontrol edin. İnternet bağlantınızın olduğundan emin olun.
- **GPU kullanılmıyor:** Sürücüyü güncelleyin. Günlükte `CPU'ya dönülüyor` yazıyorsa yanındaki hata mesajına bakın.
- **Argos Translate (Çevrimdışı) motoru:** Bu pakette yoktur (çok büyük). Groq / Gemini / Google motorlarını kullanın.
- **Antivirüs exe'yi siliyor:** PyInstaller ile paketlenmiş imzasız programlarda yanlış alarm görülebilir. Klasörü antivirüs istisnalarına ekleyin.
