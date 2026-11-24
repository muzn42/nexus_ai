"""
NEXUS AI v2 — Çeviri Motor Yöneticisi
Veritabanı → Öğrenilmiş Cache → Online Motor hibrit akışı.
Her çevirinin kaynağını izler, istatistik tutar ve sonuçları önbelleğe alır.
"""
import os
import threading
import time
from collections import OrderedDict, deque
from core.db_manager import DBManager, AutoLearnDB
from core.llm_chain import BATCH_SYSTEM_PROMPT, LLMChain, SYSTEM_PROMPT
import re
from core.text_filter import BUTTON_TOKENS, split_speaker_prefix

ENGINE_CHAIN = "Akıllı Zincir (GPT-OSS → Gemini)"

# '[R2]' / '[TRIANGLE]' gibi tuş etiketleri (yalnızca bilinen tuş adları; '[1]' numaraları değil)
_BTN_TAG_RE = re.compile(r"\[([A-Za-z0-9\-]{1,10})\]")


def _bare_button_tags(text: str) -> str:
    """'Press [R2] to fire' -> 'Press R2 to fire' (yalnızca bilinen tuş etiketleri açılır)."""
    if not text or "[" not in text:
        return text
    return _BTN_TAG_RE.sub(
        lambda m: m.group(1) if m.group(1).upper().replace("-", "") in BUTTON_TOKENS else m.group(0),
        text,
    )


# Çeviri kaynağı sabitleri
SOURCE_GOLDEN = "ALTIN"
SOURCE_DB = "DB"
SOURCE_LEARNED = "ÖĞR"
SOURCE_CACHE = "ÖNB"
SOURCE_GOOGLE = "GT"
SOURCE_ARGOS = "ARG"
SOURCE_GEMINI = "GEM"
SOURCE_GROQ = "GROQ"
SOURCE_CHAIN = "ZİNCİR"


class TranslationEngine:
    """
    Hibrit çeviri dispatcher:
      1. Bellek içi Cache (0 ms)
      2. Altın Veritabanı (NVIDIA AI Süzülmüş) (0 ms)
      3. Yerel Oyun Veritabanı (0 ms)
      4. Otomatik Öğrenme DB (0 ms)
      5. Seçili Online/Offline Motor (Groq / Google / Argos / Gemini)
    """

    def __init__(self, db_manager: DBManager, auto_learn_db: AutoLearnDB,
                 fallback_engine: str = "Groq AI (Qwen 27B)",
                 target_language: str = "Türkçe",
                 gemini_api_key: str = "",
                 groq_api_key: str = "",
                 evren_api_key: str = "",
                 auto_learn_enabled: bool = False):

        self.db_manager = db_manager
        self.auto_learn_db = auto_learn_db
        self.fallback_engine = fallback_engine
        self.target_language = target_language
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY", "").strip()
        self.evren_api_key = evren_api_key or os.environ.get("EVREN_API_KEY", "").strip()
        self.auto_learn_enabled = auto_learn_enabled

        # Bellek içi çeviri cache (LRU, max 500) ve paralel hat kilitleri
        self._cache = OrderedDict()
        self._cache_max = 500
        self._cache_lock = threading.Lock()
        self._context_lock = threading.Lock()
        self._tls = threading.local()

        # Oturum istatistikleri
        self.stats = {
            SOURCE_GOLDEN: 0,
            SOURCE_DB: 0,
            SOURCE_LEARNED: 0,
            SOURCE_CACHE: 0,
            SOURCE_GOOGLE: 0,
            SOURCE_ARGOS: 0,
            SOURCE_GEMINI: 0,
            SOURCE_GROQ: 0,
            SOURCE_CHAIN: 0,
        }

        # Lazy-init motor referansları
        self._google_translator = None
        self._google_lang = None
        self._gemini_model = None
        self._groq_client = None
        self._session = None  # requests.Session — her çağrıda SSL/TCP handshake tekrarını önler

        # Akıllı zincir + kayan pencere (son 3 altyazı bağlam olarak gönderilir)
        self.chain = LLMChain({"groq_api_key": self.groq_api_key,
                               "gemini_api_key": self.gemini_api_key,
                               "evren_api_key": self.evren_api_key})
        self.context = deque(maxlen=3)

    def set_keys(self, groq_api_key=None, gemini_api_key=None, evren_api_key=None):
        """Ayarlardan anahtar değişince motoru ve zinciri güncelle."""
        if groq_api_key is not None:
            self.groq_api_key = groq_api_key
            self._groq_client = None
            self._groq_cooldown_until = 0.0
        if gemini_api_key is not None:
            self.gemini_api_key = gemini_api_key
            self._gemini_model = None
        if evren_api_key is not None:
            self.evren_api_key = evren_api_key
        self.chain.update_keys(groq_api_key=self.groq_api_key,
                               gemini_api_key=self.gemini_api_key,
                               evren_api_key=self.evren_api_key)

    @property
    def total_translations(self) -> int:
        return sum(self.stats.values())

    def translate(self, text: str, on_partial=None) -> tuple[str, str]:
        """
        Metni çevirir.
        on_partial(metin): Akıllı Zincir'de SSE ile gelen kısmi çeviri (isteğe bağlı).
        Returns: (çeviri, kaynak_etiketi) — ör: ("Merhaba", "ALTIN")
        """
        if not text or not text.strip():
            return "", ""

        clean_text = text.strip()
        cache_key = clean_text.lower()
        try:
            return self._translate_inner(clean_text, cache_key, on_partial)
        finally:
            # Kayan pencere: hangi kaynaktan çevrilirse çevrilsin bağlama ekle
            with self._context_lock:
                if not self.context or self.context[-1] != clean_text:
                    self.context.append(clean_text)

    def _lookup_local(self, clean_text: str, cache_key: str) -> tuple[str, str]:
        """Önbellek + Altın DB + Oyun DB + (açıksa) Otomatik Öğrenme DB araması (0 ms)."""
        with self._cache_lock:
            if cache_key in self._cache:
                self.stats[SOURCE_CACHE] += 1
                result = self._cache[cache_key]
                self._cache.move_to_end(cache_key)
                return result, SOURCE_CACHE

        # '[R2]' gibi tuş etiketleri DB'de yalın ('Press R2 to fire') saklanır; etiketli arama
        # tutmazsa yalın metinle tekrar dene. DB sonucu etiketsizse olduğu gibi döner.
        variants = [clean_text]
        bare = _bare_button_tags(clean_text)
        if bare and bare != clean_text:
            variants.append(bare)

        for variant in variants:
            db_result, tag = self.db_manager.find_translation(variant)
            if db_result:
                source_tag = SOURCE_GOLDEN if tag == "ALTIN" else SOURCE_DB
                self.stats[source_tag] += 1
                self._add_to_cache(cache_key, db_result)
                return db_result, source_tag

        if self.auto_learn_enabled and self.auto_learn_db is not None:
            for variant in variants:
                learned = self.auto_learn_db.find(variant)
                if learned:
                    self.stats[SOURCE_LEARNED] += 1
                    self._add_to_cache(cache_key, learned)
                    return learned, SOURCE_LEARNED

        return "", ""

    @staticmethod
    def _is_proper_noun(speaker: str, body: str, translated: str, ok: bool = True) -> bool:
        if not ok or speaker or not body or not translated:
            return False
        if len(body.split()) > 4:
            return False
        return translated.strip().lower() == body.strip().lower()

    def _record_online(self, clean_text: str, cache_key: str, translated: str, source: str, ok: bool = True):
        if not ok or not translated or translated.startswith("[Hata]"):
            return
        self.stats[source] = self.stats.get(source, 0) + 1
        self._add_to_cache(cache_key, translated)
        if self.auto_learn_enabled and translated.strip().lower() != clean_text.lower():
            self.auto_learn_db.save(clean_text, translated, source)

    def _translate_inner(self, clean_text: str, cache_key: str, on_partial):
        local_tr, local_src = self._lookup_local(clean_text, cache_key)
        if local_tr:
            return local_tr, local_src

        # 4. Online / Offline Yedek Motor
        self._last_ok = True
        translated, source = self._fallback_translate(clean_text, on_partial)
        self._record_online(clean_text, cache_key, translated, source, ok=self._last_ok)
        return translated, source

    def translate_with_speaker(self, text: str, on_partial=None) -> tuple[str, str, str, bool]:
        """
        Konuşmacı adını ('Lucia: ...') ayırarak çevirir.
        Döner: (çeviri, kaynak, konuşmacı, yalnızca_özel_isim_mi)
        """
        if not text or not text.strip():
            return "", "", "", False
        speaker, body = split_speaker_prefix(text)
        if not body:
            return "", "", speaker, False
        translated, source = self.translate(body, on_partial=on_partial)
        is_proper = self._is_proper_noun(speaker, body, translated, getattr(self, "_last_ok", True))
        return translated, source, speaker, is_proper

    def translate_batch(self, texts: list[str]) -> list[dict]:
        """
        Birden çok metni hibrit akışla (önce DB/Cache, kalanlar tek toplu LLM isteği) çevirir.
        Döner: [{"translated": str, "source": str, "speaker": str, "is_proper_noun": bool}, ...]
        """
        if not texts:
            return []

        results = [None] * len(texts)
        misses = {}  # cache_key -> (body, [indices])
        speakers = [""] * len(texts)
        bodies = [""] * len(texts)

        for idx, raw in enumerate(texts):
            speaker, body = split_speaker_prefix(raw)
            speakers[idx] = speaker
            bodies[idx] = body
            if not body:
                results[idx] = {"translated": "", "source": "", "speaker": speaker, "is_proper_noun": False}
                continue
            cache_key = body.lower()
            local_tr, local_src = self._lookup_local(body, cache_key)
            if local_tr:
                is_pn = self._is_proper_noun(speaker, body, local_tr, True)
                results[idx] = {"translated": local_tr, "source": local_src, "speaker": speaker, "is_proper_noun": is_pn}
            else:
                if cache_key not in misses:
                    misses[cache_key] = [body, []]
                misses[cache_key][1].append(idx)

        if misses:
            miss_items = list(misses.items())
            miss_bodies = [v[0] for _, v in miss_items]

            batch_out = []
            batch_src = ""
            engine = self.fallback_engine

            if engine == ENGINE_CHAIN:
                batch_out, batch_src = self.chain.translate_batch(miss_bodies, self.target_language)
            elif engine == "Groq AI (Qwen 27B)":
                batch_out = self._translate_groq_batch(miss_bodies)
                batch_src = SOURCE_GROQ if batch_out else ""
            elif engine == "Gemini AI":
                batch_out = self._translate_gemini_batch(miss_bodies)
                batch_src = SOURCE_GEMINI if batch_out else ""
            elif engine == "Google Translate (Ücretsiz)":
                batch_out = self._translate_google_batch(miss_bodies)
                batch_src = SOURCE_GOOGLE if batch_out else ""

            for pos, (cache_key, (body, idx_list)) in enumerate(miss_items):
                tr = batch_out[pos].strip() if (batch_out and pos < len(batch_out) and batch_out[pos]) else ""
                src = batch_src
                ok = bool(tr)
                if not tr:
                    self._last_ok = True
                    tr, src = self._fallback_translate(body)
                    ok = getattr(self, "_last_ok", True)
                self._record_online(body, cache_key, tr, src, ok=ok)
                if ok:
                    with self._context_lock:
                        if not self.context or self.context[-1] != body:
                            self.context.append(body)
                for idx in idx_list:
                    sp = speakers[idx]
                    is_pn = self._is_proper_noun(sp, body, tr, ok)
                    results[idx] = {"translated": tr, "source": src, "speaker": sp, "is_proper_noun": is_pn}

        return results

    def _add_to_cache(self, key: str, value: str):
        with self._cache_lock:
            if len(self._cache) >= self._cache_max:
                self._cache.popitem(last=False)
            self._cache[key] = value

    def clear_cache(self):
        """Oturum içi bellek önbelleğini temizler."""
        with self._cache_lock:
            self._cache.clear()

    def _fallback_translate(self, text: str, on_partial=None) -> tuple[str, str]:
        """Seçili yedek motoru kullanarak çevir."""
        engine = self.fallback_engine

        if engine == ENGINE_CHAIN:
            with self._context_lock:
                ctx_snap = list(self.context)
            result, label = self.chain.translate(
                text, ctx_snap, self.target_language, on_partial)
            if result:
                return result, label
            # Zincirdeki tüm modeller kotada/meşgulse oyunu bekletmeden Google'a düş
            return self._translate_google(text), SOURCE_GOOGLE
        elif engine == "Groq AI (Qwen 27B)":
            return self._translate_groq(text, on_partial=on_partial), SOURCE_GROQ
        elif engine == "Google Translate (Ücretsiz)":
            return self._translate_google(text), SOURCE_GOOGLE
        elif engine == "Argos Translate (Çevrimdışı)":
            return self._translate_argos(text), SOURCE_ARGOS
        elif engine == "Gemini AI":
            return self._translate_gemini(text), SOURCE_GEMINI
        else:
            return self._translate_groq(text, on_partial=on_partial), SOURCE_GROQ

    # --- GROQ AI (Lazy Import) ---
    def _groq_call(self, system_prompt: str, user_content: str,
                   max_tokens: int = 80, on_partial=None) -> str:
        try:
            from openai import OpenAI
            if self._groq_client is None:
                self._groq_client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=self.groq_api_key,
                    timeout=10.0
                )
            if on_partial:
                stream = self._groq_client.chat.completions.create(
                    model="qwen/qwen3.8-27b",
                    temperature=0.2,
                    max_tokens=max_tokens,
                    stream=True,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ]
                )
                parts = []
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        parts.append(delta)
                        try:
                            on_partial("".join(parts))
                        except Exception:
                            pass
                return "".join(parts).strip()

            response = self._groq_client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                temperature=0.2,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
            return response.choices[0].message.content.strip()
        except ImportError:
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "qwen/qwen3.8-27b",
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            }
            r = self._http().post("https://api.groq.com/openai/v1/chat/completions",
                                  headers=headers, json=payload, timeout=8.0)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text}")

    def _translate_groq(self, text: str, on_partial=None) -> str:
        if not self.groq_api_key:
            self._last_ok = False
            return "[Hata] Groq API Anahtarı girilmedi"
        system_prompt = SYSTEM_PROMPT.format(lang=self.target_language)
        if time.time() >= getattr(self, "_groq_cooldown_until", 0.0):
            try:
                return self._groq_call(system_prompt, f"Translate:\n{text}",
                                       max_tokens=120, on_partial=on_partial)
            except Exception as e:
                print(f"[GROQ] Hata: {str(e)[:160]}")
                # Kota (429) dolunca her satırda boşuna denemeyelim
                wait = 300.0 if getattr(e, "status_code", None) == 429 else 20.0
                self._groq_cooldown_until = time.time() + wait
        # Groq kotada/hatalıysa önce Akıllı Zincir (GPT-OSS/Gemini), en son Google
        with self._context_lock:
            ctx_snap = list(self.context)
        result, _label = self.chain.translate(text, ctx_snap, self.target_language, on_partial)
        if result:
            return result
        return self._translate_google(text)

    def _translate_groq_batch(self, texts: list[str]) -> list:
        if not self.groq_api_key or not texts:
            return []
        if len(texts) == 1:
            return [self._translate_groq(texts[0])]
        if time.time() >= getattr(self, "_groq_cooldown_until", 0.0):
            numbered = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
            try:
                raw = self._groq_call(
                    BATCH_SYSTEM_PROMPT.format(lang=self.target_language),
                    numbered, max_tokens=max(400, len(texts) * 90))
                return LLMChain._parse_batch_response(raw, len(texts))
            except Exception as e:
                print(f"[GROQ BATCH] Hata: {str(e)[:160]}")
                wait = 300.0 if getattr(e, "status_code", None) == 429 else 20.0
                self._groq_cooldown_until = time.time() + wait
        # Groq kotadaysa toplu isteği Akıllı Zincir'e (GPT-OSS/Gemini) devret
        out, _label = self.chain.translate_batch(texts, self.target_language)
        return out

    # --- GOOGLE TRANSLATE ---
    def _ensure_google(self):
        from deep_translator import GoogleTranslator
        lang_code = self._lang_code()
        if self._google_translator is None or self._google_lang != lang_code:
            self._google_translator = GoogleTranslator(source="auto", target=lang_code)
            self._google_lang = lang_code
        return self._google_translator

    def _translate_google(self, text: str) -> str:
        try:
            gt = self._ensure_google()
            result = gt.translate(text)
            if result:
                return result
            self._last_ok = False
            return text
        except ImportError:
            self._last_ok = False
            return "[Hata] deep-translator paketi yüklü değil"
        except Exception as e:
            print(f"[GT] Hata: {e}")
            self._last_ok = False
            self._google_translator = None
            return text

    def _translate_google_batch(self, texts: list[str]) -> list:
        if not texts:
            return []
        try:
            gt = self._ensure_google()
            out = gt.translate_batch(texts)
            if isinstance(out, list) and len(out) == len(texts):
                return [str(x or "") for x in out]
        except Exception as e:
            print(f"[GT BATCH] Hata: {e}")
            self._google_translator = None
        return []

    def _http(self):
        """İş parçacığına özgü requests oturumu (paralel hatlarda güvenli bağlantı havuzu)."""
        sess = getattr(self._tls, "session", None)
        if sess is None:
            import requests
            sess = requests.Session()
            self._tls.session = sess
        return sess

    # --- ARGOS TRANSLATE ---
    def _translate_argos(self, text: str) -> str:
        try:
            import argostranslate.translate
            lang_code = self._lang_code()
            result = argostranslate.translate.translate(text, "en", lang_code)
            return result if result else text
        except ImportError:
            self._last_ok = False
            return "[Hata] argostranslate paketi yüklü değil"
        except Exception as e:
            print(f"[ARG] Hata: {e}")
            self._last_ok = False
            return text

    # --- GEMINI AI (Lazy Import) ---
    def _gemini_generate(self, prompt: str) -> str:
        import google.generativeai as genai
        if self._gemini_model is None:
            genai.configure(api_key=self.gemini_api_key)
            self._gemini_model = genai.GenerativeModel('gemini-2.5-flash')
        response = self._gemini_model.generate_content(prompt)
        return response.text.strip()

    def _translate_gemini(self, text: str) -> str:
        if not self.gemini_api_key:
            self._last_ok = False
            return "[Hata] Gemini API Anahtarı girilmedi"
        try:
            prompt = f"{SYSTEM_PROMPT.format(lang=self.target_language)}\n\nTranslate:\n{text}"
            return self._gemini_generate(prompt)
        except ImportError:
            self._last_ok = False
            return "[Hata] google-generativeai paketi yüklü değil"
        except Exception as e:
            print(f"[GEM] Hata: {e}")
            self._last_ok = False
            return text

    def _translate_gemini_batch(self, texts: list[str]) -> list:
        if not self.gemini_api_key or not texts:
            return []
        if len(texts) == 1:
            return [self._translate_gemini(texts[0])]
        numbered = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
        try:
            prompt = f"{BATCH_SYSTEM_PROMPT.format(lang=self.target_language)}\n\n{numbered}"
            raw = self._gemini_generate(prompt)
            return LLMChain._parse_batch_response(raw, len(texts))
        except Exception as e:
            print(f"[GEM BATCH] Hata: {e}")
            return []

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
        if self.stats.get(SOURCE_GROQ): parts.append(f"Groq:{self.stats[SOURCE_GROQ]}")
        # Akıllı zincir modelleri (GPT-OSS, G3.1L, G3.8 ...)
        known = {SOURCE_GOLDEN, SOURCE_DB, SOURCE_LEARNED, SOURCE_CACHE, SOURCE_GOOGLE,
                 SOURCE_ARGOS, SOURCE_GEMINI, SOURCE_GROQ, SOURCE_CHAIN}
        for k, v in self.stats.items():
            if k not in known and v:
                parts.append(f"{k}:{v}")
        return " | ".join(parts) if parts else "Henüz çeviri yok"
