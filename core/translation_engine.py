"""
NEXUS AI v2 — Çeviri Motor Yöneticisi
Veritabanı → Öğrenilmiş Cache → Online Motor hibrit akışı.
Her çevirinin kaynağını izler, istatistik tutar ve sonuçları önbelleğe alır.
"""
import os
from collections import OrderedDict
from core.db_manager import DBManager, AutoLearnDB


# Çeviri kaynağı sabitleri
SOURCE_GOLDEN = "ALTIN"
SOURCE_DB = "DB"
SOURCE_LEARNED = "ÖĞR"
SOURCE_CACHE = "ÖNB"
SOURCE_GOOGLE = "GT"
SOURCE_ARGOS = "ARG"
SOURCE_GEMINI = "GEM"


class TranslationEngine:
    """
    Hibrit çeviri dispatcher:
      1. Bellek içi Cache (0 ms)
      2. Altın Veritabanı (NVIDIA AI Süzülmüş) (0 ms)
      3. Yerel Oyun Veritabanı (0 ms)
      4. Otomatik Öğrenme DB (0 ms)
      5. Seçili Online/Offline Motor (Google / Argos / Gemini)
    """

    def __init__(self, db_manager: DBManager, auto_learn_db: AutoLearnDB,
                 fallback_engine: str = "Google Translate (Ücretsiz)",
                 target_language: str = "Türkçe",
                 gemini_api_key: str = "",
                 auto_learn_enabled: bool = True):

        self.db_manager = db_manager
        self.auto_learn_db = auto_learn_db
        self.fallback_engine = fallback_engine
        self.target_language = target_language
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.auto_learn_enabled = auto_learn_enabled

        # Bellek içi çeviri cache (LRU, max 500)
        self._cache = OrderedDict()
        self._cache_max = 500

        # Oturum istatistikleri
        self.stats = {
            SOURCE_GOLDEN: 0,
            SOURCE_DB: 0,
            SOURCE_LEARNED: 0,
            SOURCE_CACHE: 0,
            SOURCE_GOOGLE: 0,
            SOURCE_ARGOS: 0,
            SOURCE_GEMINI: 0,
        }

        # Lazy-init motor referansları
        self._google_translator = None
        self._gemini_model = None

    @property
    def total_translations(self) -> int:
        return sum(self.stats.values())

    def translate(self, text: str) -> tuple[str, str]:
        """
        Metni çevirir.
        Returns: (çeviri, kaynak_etiketi) — ör: ("Merhaba", "ALTIN")
        """
        if not text or not text.strip():
            return "", ""

        clean_text = text.strip()
        cache_key = clean_text.lower()

        # 1. Bellek Cache
        if cache_key in self._cache:
            self.stats[SOURCE_CACHE] += 1
            result = self._cache[cache_key]
            self._cache.move_to_end(cache_key)
            return result, SOURCE_CACHE

        # 2. Altın DB veya Oyun DB
        db_result, tag = self.db_manager.find_translation(clean_text)
        if db_result:
            source_tag = SOURCE_GOLDEN if tag == "ALTIN" else SOURCE_DB
            self.stats[source_tag] += 1
            self._add_to_cache(cache_key, db_result)
            return db_result, source_tag

        # 3. Otomatik Öğrenme DB
        learned = self.auto_learn_db.find(clean_text)
        if learned:
            self.stats[SOURCE_LEARNED] += 1
            self._add_to_cache(cache_key, learned)
            return learned, SOURCE_LEARNED

        # 4. Online / Offline Yedek Motor
        translated, source = self._fallback_translate(clean_text)
        self.stats[source] += 1
        self._add_to_cache(cache_key, translated)

        # Otomatik öğrenme: Online çeviriyi yerel DB'ye kaydet
        if self.auto_learn_enabled and translated and translated != clean_text:
            self.auto_learn_db.save(clean_text, translated, source)

        return translated, source

    def _add_to_cache(self, key: str, value: str):
        if len(self._cache) >= self._cache_max:
            self._cache.popitem(last=False)
        self._cache[key] = value

    def _fallback_translate(self, text: str) -> tuple[str, str]:
        """Seçili yedek motoru kullanarak çevir."""
        engine = self.fallback_engine

        if engine == "Google Translate (Ücretsiz)":
            return self._translate_google(text), SOURCE_GOOGLE
        elif engine == "Argos Translate (Çevrimdışı)":
            return self._translate_argos(text), SOURCE_ARGOS
        elif engine == "Gemini AI":
            return self._translate_gemini(text), SOURCE_GEMINI
        else:
            return self._translate_google(text), SOURCE_GOOGLE

    # --- GOOGLE TRANSLATE ---
    def _translate_google(self, text: str) -> str:
        try:
            from deep_translator import GoogleTranslator
            lang_code = self._lang_code()
            result = GoogleTranslator(source='auto', target=lang_code).translate(text)
            return result if result else text
        except ImportError:
            return "[Hata] deep-translator paketi yüklü değil"
        except Exception as e:
            print(f"[GT] Hata: {e}")
            return text

    # --- ARGOS TRANSLATE ---
    def _translate_argos(self, text: str) -> str:
        try:
            import argostranslate.translate
            lang_code = self._lang_code()
            result = argostranslate.translate.translate(text, "en", lang_code)
            return result if result else text
        except ImportError:
            return "[Hata] argostranslate paketi yüklü değil"
        except Exception as e:
            print(f"[ARG] Hata: {e}")
            return text

    # --- GEMINI AI (Lazy Import) ---
    def _translate_gemini(self, text: str) -> str:
        if not self.gemini_api_key:
            return "[Hata] Gemini API Anahtarı girilmedi"
        try:
            import google.generativeai as genai

            if self._gemini_model is None:
                genai.configure(api_key=self.gemini_api_key)
                self._gemini_model = genai.GenerativeModel('gemini-2.0-flash')

            lang_name = self.target_language
            prompt = (
                f"Translate the following text to {lang_name}. "
                "You are a subtitle translator. "
                "Output ONLY the translated text. No explanations.\n"
                f"Text: {text}"
            )
            response = self._gemini_model.generate_content(prompt)
            return response.text.strip()
        except ImportError:
            return "[Hata] google-generativeai paketi yüklü değil"
        except Exception as e:
            print(f"[GEM] Hata: {e}")
            return text

    def _lang_code(self) -> str:
        lang_map = {
            "Türkçe": "tr", "İngilizce": "en", "Almanca": "de",
            "Fransızca": "fr", "İspanyolca": "es", "Japonca": "ja", "Rusça": "ru",
        }
        return lang_map.get(self.target_language, "tr")

    def stats_summary(self) -> str:
        """HUD status bar'da gösterilecek istatistik özeti."""
        parts = []
        if self.stats[SOURCE_GOLDEN]: parts.append(f"Altın:{self.stats[SOURCE_GOLDEN]}")
        if self.stats[SOURCE_DB]: parts.append(f"DB:{self.stats[SOURCE_DB]}")
        if self.stats[SOURCE_LEARNED]: parts.append(f"Öğr:{self.stats[SOURCE_LEARNED]}")
        if self.stats[SOURCE_CACHE]: parts.append(f"Önb:{self.stats[SOURCE_CACHE]}")
        if self.stats[SOURCE_GOOGLE]: parts.append(f"GT:{self.stats[SOURCE_GOOGLE]}")
        if self.stats[SOURCE_ARGOS]: parts.append(f"Arg:{self.stats[SOURCE_ARGOS]}")
        if self.stats[SOURCE_GEMINI]: parts.append(f"Gem:{self.stats[SOURCE_GEMINI]}")
        return " | ".join(parts) if parts else "Henüz çeviri yok"
