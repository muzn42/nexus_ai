"""
Göz (Gemini) olaylarını OCR görünümleriyle eşleştirir.

- Anahtar her zaman OCR metnidir (oyunda birebir aranacak olan).
- Gemini'den tür / konuşan / dinleyen / ton / sahne bağlamı alınır.
- Gemini'nin zaman damgaları birkaç saniye kayabildiği için önce güvenli eşleşmelerden
  medyan ofset tahmin edilir, sonra ofsetle yeniden eşlenir.
- OCR'ın bulup Gemini'nin kaçırdığı kısa yazılar korunur (tür sezgisel atanır).
- Gemini'nin bulup OCR'ın okuyamadığı satırlar ayrı listeye düşer (DB'ye yazılmaz).
"""
from __future__ import annotations

import difflib
import re
import statistics

_TAG_RE = re.compile(r"\[[A-Z0-9\-]{1,10}\]")
_NORM_RE = re.compile(r"[^a-z0-9\[\] ]")


def _norm(s: str) -> str:
    return " ".join(_NORM_RE.sub(" ", (s or "").lower()).split())


def _body(s: str) -> str:
    """'Jason: Yeah.' -> 'Yeah.' (Gemini bazen ekrandaki konuşmacı adını metne katıyor; OCR anahtarında yok)."""
    from core.text_filter import split_speaker_prefix
    return split_speaker_prefix(s or "")[1] or (s or "")


def text_ratio(a: str, b: str) -> float:
    a, b = _norm(_body(a)), _norm(_body(b))
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    # OCR kartı, Gemini'nin birleştirdiği uzun cümlenin parçası olabilir
    if len(a) >= 12 and a in b:
        r = max(r, 0.9)
    return r


def _guess_world_type(app: dict) -> str:
    x, y, w, h = app["bbox"]
    key = app["key"]
    if _TAG_RE.search(key) or re.match(r"(?i)^(press|hold|tap|use|release)\b", key):
        return "hint"
    if x < 0.30 and y < 0.30:
        return "hint"     # sol üst yardım kutusu
    if y > 0.80 and x < 0.25:
        return "hud"      # sol alt: konum / sokak adı
    if len(key.split()) <= 3:
        return "menu"
    return "hud"


def align(eye: dict, apps: list[dict], window: float = 8.0) -> dict:
    events = [e for e in eye.get("events", []) if e.get("english") and e.get("t") is not None]
    for i, e in enumerate(events):
        e["_id"] = i

    def best_match(app, offset, used_ok=True):
        best, br = None, 0.0
        for e in events:
            if abs((e["t"] - offset) - app["t_first"]) > window:
                continue
            is_sub = e.get("type") == "subtitle"
            r = text_ratio(app["key"], e["english"])
            # bölge/tür uyuşmazlığı ancak çok güçlü metin eşleşmesinde kabul (ör. alttaki silah çarkı menüsü)
            if (app["zone"] == "sub") != is_sub and e.get("type") not in ("objective",) and r < 0.85:
                continue
            if r > br:
                best, br = e, r
        return best, br

    # 1) Ofset tahmini (yalnız güçlü eşleşmeler)
    diffs = []
    for app in apps:
        e, r = best_match(app, 0.0)
        if e is not None and r >= 0.85:
            diffs.append(e["t"] - app["t_first"])
    offset = statistics.median(diffs) if diffs else 0.0

    entries, matched_ids = [], set()
    for app in apps:
        e, r = best_match(app, offset)
        ent = {
            "key": app["key"], "zone": app["zone"], "t": round(app["t_first"], 2),
            "t_end": round(app["t_last"], 2), "ocr_hits": app["hits"], "ocr_score": app["score"],
            "ocr_variants": app["variants"], "speaker_prefix": app.get("speaker_prefix", ""),
            "match_ratio": round(r, 3), "bbox": [round(v, 4) for v in app.get("bbox", [])],
        }
        if e is not None and r >= 0.6:
            matched_ids.add(e["_id"])
            ent.update({
                "type": e.get("type") or ("subtitle" if app["zone"] == "sub" else "hud"),
                "speaker": e.get("speaker") or app.get("speaker_prefix", ""),
                "listener": e.get("listener", ""), "tone": e.get("tone", ""),
                "scene": e.get("scene", ""), "gemini_english": e.get("english", ""),
                "buttons": e.get("buttons") or [],
                # tuş ikonları ([X], [L1]) renkli kelime sayılmaz; overlay onları ayrıca çiziyor
                "highlights": [h for h in (e.get("highlights") or []) if isinstance(h, dict) and h.get("text")
                               and _TAG_RE.sub("", str(h["text"])).strip(" .,!?")],
            })
        else:
            ent.update({
                "type": "subtitle" if app["zone"] == "sub" else _guess_world_type(app),
                "speaker": app.get("speaker_prefix", ""), "listener": "", "tone": "",
                "scene": "", "gemini_english": "", "buttons": _TAG_RE.findall(app["key"]),
                "gemini_missed": True,
            })
        entries.append(ent)

    # Gemini'nin doğrulamadığı OCR görünümlerinde tabela / filigran / yarım okuma gürültüsünü ele
    for ent in entries:
        if not ent.get("gemini_missed"):
            continue
        k = ent["key"]
        words = k.split()
        letters = [c for c in k if c.isalpha()]
        if not letters:
            ent["exclude"] = "harf yok"
        elif ent["zone"] == "sub" and not (any(c.islower() for c in letters) and len(words) >= 2
                                            and ent["ocr_hits"] >= 3 and ent["ocr_score"] >= 0.9):
            ent["exclude"] = "altyazı bandında Gemini'nin görmediği yazı (tabela/yarım okuma)"
        elif ent["zone"] == "sub":
            ent["type"] = "subtitle"   # Gemini atlamış ama konuşma satırına benziyor: tut, çevirmen gerekirse atlar
        elif all(c.isupper() for c in letters) and len(words) <= 3:
            ent["exclude"] = "büyük harfli kısa dünya yazısı (tabela)"
        elif re.search(r"(?i)ice\s*and\s*fire|mkice|shirrako", k.replace(" ", "")):
            ent["exclude"] = "kanal filigranı"
        elif sum(c.isdigit() for c in k) >= len(letters):
            ent["exclude"] = "sayı ağırlıklı HUD değeri (mesafe/para) — her değer ayrı anahtar olmaz"
        elif len(words) <= 2 and not _TAG_RE.search(k):
            ent["exclude"] = "Gemini'nin görmediği 1-2 kelimelik dünya yazısı (tabela)"
        elif ent["ocr_hits"] < 4:
            ent["exclude"] = "çok kısa görünen doğrulanmamış yazı"

    # Aynı anahtarın tekrarları (ör. 'Follow the plane' birkaç kez) tek satır olur
    first = {}
    for ent in entries:
        if ent.get("exclude"):
            continue
        nk = ent["key"].strip().lower()
        if nk in first:
            first[nk]["repeats"] = first[nk].get("repeats", 1) + 1
            ent["exclude"] = "tekrar"
        else:
            first[nk] = ent

    # Eşleşmeyenlere en yakın sahne bağlamını ödünç ver
    for ent in entries:
        if ent["scene"]:
            continue
        near = min(events, key=lambda e: abs((e["t"] - offset) - ent["t"]), default=None)
        if near is not None and abs((near["t"] - offset) - ent["t"]) < 30:
            ent["scene"] = near.get("scene", "")

    missed_by_ocr = [
        {k: e.get(k) for k in ("t", "type", "speaker", "english")}
        for e in events if e["_id"] not in matched_ids
    ]
    return {"offset": round(offset, 2), "entries": entries, "missed_by_ocr": missed_by_ocr,
            "events_total": len(events)}
