"""
Gemini istemcisi: aynı istek listesini ya anlık (paralel generateContent) ya da Batch API
(models/{model}:batchGenerateContent, yarı fiyat, asenkron) ile çalıştırır.

Anahtar asla yazdırılmaz. Öncelik: set_key_file() ile verilen dosya > GEMINI_API_KEY ortam
değişkeni > config/settings.json (SettingsManager).
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .common import log

BASE = "https://generativelanguage.googleapis.com/v1beta"
_KEY_FILE = None


def set_key_file(path: str | None):
    global _KEY_FILE
    _KEY_FILE = path


def api_key() -> str:
    if _KEY_FILE:
        with open(_KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
        if k:
            return k
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    from .common import gemini_key
    return gemini_key()


def make_request(parts: list, system: str | None = None, json_out: bool = True, temperature: float = 0.3,
                 thinking: str | None = None, model: str = "", max_tokens: int = 65536) -> dict:
    gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_out:
        gen["responseMimeType"] = "application/json"
    if thinking and not model.startswith("gemini-2"):
        gen["thinkingConfig"] = {"thinkingLevel": thinking}
    req = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    if system:
        req["systemInstruction"] = {"parts": [{"text": system}]}
    return req


def response_text(resp: dict) -> str:
    try:
        parts = resp["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def response_json(resp: dict):
    txt = response_text(resp).strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[txt.find("\n") + 1:] if "\n" in txt else txt
    return json.loads(txt) if txt else None


def add_usage(usage: dict, resp: dict, model: str = ""):
    um = (resp or {}).get("usageMetadata", {}) or {}
    usage["prompt"] = usage.get("prompt", 0) + um.get("promptTokenCount", 0)
    usage["output"] = usage.get("output", 0) + um.get("candidatesTokenCount", 0)
    usage["thoughts"] = usage.get("thoughts", 0) + um.get("thoughtsTokenCount", 0)
    usage["calls"] = usage.get("calls", 0) + 1
    if model:
        usage.setdefault("models", {})
        usage["models"][model] = usage["models"].get(model, 0) + 1


# ------------------------------------------------------------------ anlık
def _direct_one(model: str, req: dict, key: str, timeout: float = 900, tries: int = 5) -> dict:
    last = ""
    for attempt in range(tries):
        try:
            r = requests.post(f"{BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                              json=req, timeout=timeout)
        except requests.RequestException as ex:
            last = f"{type(ex).__name__}"
            log(f"[Gemini] {model} bağlantı hatası ({attempt + 1}/{tries}): {last}")
            continue
        if r.status_code == 200:
            return r.json()
        last = f"HTTP {r.status_code}: {r.text[:160]}"
        log(f"[Gemini] {model} {last} ({attempt + 1}/{tries})")
        if r.status_code == 400 and "thinking" in r.text.lower():
            req.get("generationConfig", {}).pop("thinkingConfig", None)
            continue
        if r.status_code in (429, 500, 503, 504):
            time.sleep(15 * (attempt + 1))
            continue
        break
    raise RuntimeError(f"{model}: {last}")


def run_direct(model: str, reqs: list[dict], workers: int = 4) -> list[dict | None]:
    key = api_key()

    def one(req):
        try:
            return _direct_one(model, req, key)
        except Exception as ex:
            log(f"[Gemini] istek başarısız: {ex}")
            return None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, reqs))


# ------------------------------------------------------------------ batch
def _find(obj, name):
    """İç içe JSON'da ilk 'name' anahtarını bulur (REST yanıtının sarmalayıcıları değişebiliyor)."""
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        for v in obj.values():
            hit = _find(v, name)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find(v, name)
            if hit is not None:
                return hit
    return None


BATCH_STATE_DIR = None   # ayarlanırsa gönderilen batch adları buraya yazılır (çökmede yeniden gönderilmez)
MAX_BATCH_BYTES = 12_000_000
MAX_BATCH_REQS = 300


def _submit(model, reqs, offset, label, key):
    body = {"batch": {"display_name": f"{label}-{int(time.time())}",
                      "input_config": {"requests": {"requests": [
                          {"request": r, "metadata": {"key": f"r{offset + i}"}} for i, r in enumerate(reqs)]}}}}
    for attempt in range(6):
        r = requests.post(f"{BASE}/models/{model}:batchGenerateContent", headers={"x-goog-api-key": key},
                          json=body, timeout=600)
        if r.status_code == 200:
            return r.json().get("name")
        if r.status_code in (429, 500, 503, 504):
            time.sleep(30 * (attempt + 1))
            continue
        break
    raise RuntimeError(f"batch oluşturulamadı: HTTP {r.status_code}: {r.text[:300]}")


def _split(reqs):
    groups, cur, size = [], [], 0
    for i, r in enumerate(reqs):
        n = len(json.dumps(r, ensure_ascii=False).encode("utf-8"))
        if cur and (size + n > MAX_BATCH_BYTES or len(cur) >= MAX_BATCH_REQS):
            groups.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        groups.append(cur)
    return groups


def run_batch(model: str, reqs: list[dict], label: str = "nexus", poll: float = 60.0,
              max_wait: float = 30 * 3600) -> list[dict | None]:
    """Batch API ile çalıştırır; sonuçları istek sırasıyla döndürür (başarısızlar None).
    Büyük işler boyut/sayı sınırına göre birden çok batch'e bölünüp aynı anda gönderilir.
    BATCH_STATE_DIR ayarlıysa her parçanın batch adı içerik özetiyle kaydedilir; yeniden
    çalıştırmada aynı parça tekrar gönderilmez, mevcut batch beklenir."""
    import hashlib
    import os
    key = api_key()
    groups = _split(reqs)
    jobs = []
    for gi, idxs in enumerate(groups):
        part = [reqs[i] for i in idxs]
        h = hashlib.sha1((model + json.dumps(part, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()[:16]
        sfile = os.path.join(BATCH_STATE_DIR, f"batch_{label}_{h}.json") if BATCH_STATE_DIR else None
        name = None
        if sfile and os.path.exists(sfile):
            with open(sfile, encoding="utf-8") as f:
                name = json.load(f).get("name")
            log(f"[Batch] {label} {gi + 1}/{len(groups)}: kayıtlı batch sürdürülüyor ({name})")
        if not name:
            name = _submit(model, part, 0, f"{label}{gi + 1}", key)
            if sfile:
                os.makedirs(BATCH_STATE_DIR, exist_ok=True)
                with open(sfile, "w", encoding="utf-8") as f:
                    json.dump({"name": name, "model": model, "n": len(part)}, f)
            log(f"[Batch] {label} {gi + 1}/{len(groups)}: {len(part)} istek gönderildi ({name}, {model})")
        jobs.append({"name": name, "idxs": idxs, "done": False, "sfile": sfile})

    out: list[dict | None] = [None] * len(reqs)
    t0 = time.time()
    while not all(j["done"] for j in jobs):
        time.sleep(poll)
        for j in jobs:
            if j["done"]:
                continue
            try:
                g = requests.get(f"{BASE}/{j['name']}", headers={"x-goog-api-key": key}, timeout=600)
            except requests.RequestException:
                continue
            if g.status_code != 200:
                log(f"[Batch] durum okunamadı HTTP {g.status_code}")
                if g.status_code == 404:
                    j["done"] = True
                continue
            d = g.json()
            state = _find(d, "state") or ""
            if state != j.get("state"):
                log(f"[Batch] {label} {j['name'].split('/')[-1]}: {state} ({time.time() - t0:.0f} sn)")
                j["state"] = state
            if not (d.get("done") or state.endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"))):
                continue
            j["done"] = True
            inl = _find(d, "inlinedResponses")
            if isinstance(inl, dict):
                inl = inl.get("inlinedResponses", [])
            got = 0
            for pos, item in enumerate(inl or []):
                k = ((item.get("metadata") or {}).get("key") or "")
                li = int(k[1:]) if k.startswith("r") and k[1:].isdigit() else pos
                if item.get("error"):
                    log(f"[Batch] istek hatası: {json.dumps(item['error'])[:200]}")
                    continue
                if 0 <= li < len(j["idxs"]):
                    out[j["idxs"][li]] = item.get("response")
                    got += 1
            log(f"[Batch] {label} {j['name'].split('/')[-1]}: {state}, {got}/{len(j['idxs'])} yanıt")
        if time.time() - t0 > max_wait:
            log(f"[Batch] {label}: {max_wait:.0f} sn doldu, bitmeyenler eksik sayılıyor")
            break
    log(f"[Batch] {label}: toplam {sum(1 for o in out if o)}/{len(reqs)} yanıt, {time.time() - t0:.0f} sn")
    return out


def run(model: str, reqs: list[dict], batch: bool = False, label: str = "nexus", workers: int = 4,
        retry_direct: bool = True) -> list[dict | None]:
    """Batch modunda eksik kalan yanıtları (varsa) anlık modda bir kez daha dener."""
    if not reqs:
        return []
    out = run_batch(model, reqs, label=label) if batch else run_direct(model, reqs, workers=workers)
    missing = [i for i, o in enumerate(out) if o is None]
    if batch and len(missing) > 20:
        log(f"[Batch] {len(missing)} eksik yanıt yeni bir batch ile yeniden deneniyor")
        again = run_batch(model, [reqs[i] for i in missing], label=label + "-tekrar")
        for i, o in zip(missing, again):
            out[i] = o
        missing = [i for i, o in enumerate(out) if o is None]
    if batch and missing and retry_direct:
        log(f"[Batch] {len(missing)} eksik yanıt anlık modda yeniden deneniyor")
        again = run_direct(model, [reqs[i] for i in missing], workers=workers)
        for i, o in zip(missing, again):
            out[i] = o
    return out
