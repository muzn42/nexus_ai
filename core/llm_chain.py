"""
NEXUS AI v2 — Akıllı LLM Zinciri
Birden fazla OpenAI uyumlu sağlayıcıyı sırayla dener:
  - SSE (stream=True) ile ilk token gelir gelmez kısmi çeviri gösterilebilir.
  - Kayan pencere: son birkaç altyazı bağlam olarak gönderilir (çeviri tutarlılığı).
  - Kota/aşırı yük (429/503) veya zaman aşımında model bir süre "soğumaya" alınır,
    sıradaki modele geçilir. 404 (model kaldırılmış) olan model oturum boyunca kapatılır.
"""
import time
import threading

GROQ_BASE = "https://api.groq.com/openai/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
EVREN_BASE = "https://evren-llmapi.ssyz.org.tr/v1"

# (etiket, model, base_url, anahtar_ayar_adı, ek_parametreler)
# Sıra kıyaslama sonucuna göre: en hızlı ve en kararlı model başta.
DEFAULT_CHAIN = [
    ("GPT-OSS", "openai/gpt-oss-120b", GROQ_BASE, "groq_api_key", {"reasoning_effort": "low"}),
    ("EVREN", "deepseek-v4.1-flash", EVREN_BASE, "evren_api_key", {}),
    ("G3.5L", "gemini-3.5-flash-lite", GEMINI_BASE, "gemini_api_key", {}),
    ("G3.1L", "gemini-3.1-flash-lite", GEMINI_BASE, "gemini_api_key", {}),
    ("G2.5F", "gemini-2.5-flash", GEMINI_BASE, "gemini_api_key", {}),
]

SYSTEM_PROMPT = (
    "You are a video game subtitle translator. Translate the LAST line into {lang}. "
    "Previous lines are context only, do not translate them. "
    "Keep names as they are. Output ONLY the translation of the last line, "
    "without quotes, notes or explanations."
)


class LLMChain:
    def __init__(self, keys: dict, chain=None, request_timeout: float = 4.0):
        self.keys = keys                      # {"groq_api_key": "...", "gemini_api_key": "..."}
        self.chain = chain or DEFAULT_CHAIN
        self.request_timeout = request_timeout
        self._clients = {}
        self._cooldown_until = {}             # model -> epoch saniye
        self._disabled = set()                # 404 alan modeller
        self._lock = threading.Lock()
        self.last_model = ""
        self.last_error = ""

    def update_keys(self, **keys):
        self.keys.update(keys)
        self._clients.clear()
        self._disabled.clear()
        self._cooldown_until.clear()

    def _client(self, base, key):
        from openai import OpenAI
        ck = (base, key)
        if ck not in self._clients:
            headers = {"X-API-Key": key} if "evren" in base else {}
            self._clients[ck] = OpenAI(base_url=base, api_key=key,
                                       default_headers=headers,
                                       timeout=self.request_timeout, max_retries=0)
        return self._clients[ck]

    def _available(self, model):
        if model in self._disabled:
            return False
        return time.time() >= self._cooldown_until.get(model, 0)

    def _penalize(self, model, err):
        msg = str(err)
        status = getattr(err, "status_code", None)
        if status == 404 or "no longer available" in msg:
            self._disabled.add(model)
            return "kaldırılmış"
        if status in (401, 403):
            self._disabled.add(model)
            return "anahtar geçersiz"
        if status == 429:
            wait = 60.0
            try:
                ra = err.response.headers.get("retry-after")
                if ra:
                    wait = max(5.0, min(float(ra), 600.0))
            except Exception:
                pass
            self._cooldown_until[model] = time.time() + wait
            return f"kota ({int(wait)} sn bekleme)"
        # 503, zaman aşımı, bağlantı hatası
        self._cooldown_until[model] = time.time() + 20.0
        return "meşgul/zaman aşımı (20 sn bekleme)"

    def translate(self, text: str, context: list, lang: str, on_partial=None):
        """
        Döner: (çeviri, etiket) ya da hiçbir model çalışmazsa (None, "").
        on_partial(metin): SSE ile gelen kısmi çeviri (isteğe bağlı).
        """
        ctx = "\n".join(f"- {c}" for c in context if c)
        user = (f"Context (previous lines):\n{ctx}\n\n" if ctx else "") + f"Translate:\n{text}"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(lang=lang)},
            {"role": "user", "content": user},
        ]

        for label, model, base, key_name, extra in self.chain:
            key = self.keys.get(key_name, "")
            if not key or not self._available(model):
                continue
            try:
                stream = self._client(base, key).chat.completions.create(
                    model=model, messages=messages, stream=True,
                    temperature=0.2, max_tokens=300, **extra)
                parts = []
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        parts.append(delta)
                        if on_partial:
                            try:
                                on_partial("".join(parts))
                            except Exception:
                                pass
                result = " ".join("".join(parts).split()).strip().strip('"')
                if result:
                    self.last_model = label
                    self.last_error = ""
                    return result, label
                self._penalize(model, Exception("boş cevap"))
            except Exception as e:
                with self._lock:
                    reason = self._penalize(model, e)
                self.last_error = f"{label}: {reason}"
                print(f"[ZİNCİR] {label} atlandı -> {reason}")
        return None, ""

    def status(self) -> str:
        now = time.time()
        parts = []
        for label, model, *_ in self.chain:
            if model in self._disabled:
                parts.append(f"{label}:kapalı")
            elif now < self._cooldown_until.get(model, 0):
                parts.append(f"{label}:{int(self._cooldown_until[model] - now)}sn")
            else:
                parts.append(f"{label}:hazır")
        return " ".join(parts)

