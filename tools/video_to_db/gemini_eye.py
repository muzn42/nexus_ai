"""
Aşama 1 — "Göz": Gemini video anlama ile zaman damgalı ekran yazısı dökümü.

YouTube linki doğrudan Gemini'ye verilir (file_data + video_metadata start/end),
yani Gemini için video indirmeye/yüklemeye gerek yoktur. YouTube otomatik altyazısı
KULLANILMAZ; yalnızca oyunun kendi ekranda gösterdiği yazılar okunur.
"""
from __future__ import annotations

import json
import re
import time

from . import gemini_client as gc
from .common import log


EYE_PROMPT = """You are building a localization database for GTA 6 (Grand Theft Auto VI) from a PS5 gameplay recording.
Watch this clip (video AND audio) and transcribe EVERY piece of English text that the GAME draws on screen.
Do NOT transcribe YouTube captions, channel watermarks or anything that is not part of the game UI.

Categories ("type"):
- "subtitle": in-game dialogue subtitles (bottom center). One entry per subtitle CARD exactly as displayed
  (if a sentence is split across two consecutive cards, output two entries). Keep the on-screen wording exactly.
- "objective": mission objective / task text (usually bottom center, often with colored keywords, e.g. "Go to the car.").
- "hint": help / tutorial / button prompts (usually top-left box or context prompts like "Press R2 to accelerate").
- "menu": pause menu, phone, map, wheel, choice lists, mission titles, "MISSION PASSED" banners.
- "hud": persistent HUD labels (location / street names, money, wanted info, notifications).

For each entry return:
- "t": the FIRST second the text becomes visible, as absolute timestamp of the FULL video "HH:MM:SS".
- "t_end": last second it is visible "HH:MM:SS".
- "type": one of the categories above.
- "speaker": who says it (subtitle only; character name as known in the game, e.g. "Jason", "Lucia", "Cal"; use the voice
  and the picture to decide; "" if unknown or not dialogue).
- "listener": who is being addressed ("Jason", "Lucia", "group", "self", "player", ""...).
- "tone": short tone description of how it is said (e.g. "joking", "angry", "tense whisper", "sarcastic", "neutral instruction").
- "scene": very short description of what is happening in the scene (max ~12 words).
- "english": the exact on-screen English text. Controller button icons inside the text must be written as tags:
  [X] [O] [TRIANGLE] [SQUARE] [R1] [R2] [R3] [L1] [L2] [L3] [OPTIONS] [TOUCHPAD] [DPAD] [LS] [RS].
- "buttons": list of the button tags that appear in the text (e.g. ["R2"]), [] if none.
- "highlights": words or phrases inside the text that are drawn in a DIFFERENT COLOR than the rest of the text
  (GTA objectives/hints color key words, e.g. "Go to the car." with "car" in yellow, or a character name in blue).
  List of {"text": "<exact highlighted words>", "color": "<yellow|blue|green|red|orange|purple|pink|white|other>"}; [] if none.

Be exhaustive and precise; do not paraphrase; do not merge different cards; skip text that is unreadable.
Return ONLY a JSON object: {"subtitles_visible": bool, "events": [ ... ]}."""

_TS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?$")


def parse_ts(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _TS_RE.match(str(value).strip())
    if not m:
        return None
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + (float("0." + m.group(4)) if m.group(4) else 0.0)


def _chunk_events(resp, s, e):
    data = gc.response_json(resp) if resp else None
    if isinstance(data, list):
        data = {"subtitles_visible": None, "events": data}
    data = data or {}
    evs = data.get("events") or []
    # Bazı modeller klibe göre (00:00'dan) zaman verir: aralık dışındaysa ofset ekle
    ts = [x for x in (parse_ts(ev.get("t")) for ev in evs) if x is not None]
    rel = bool(ts) and min(ts) < s - 5 and max(ts) < (e - s) + 5
    for ev in evs:
        for k in ("t", "t_end"):
            v = parse_ts(ev.get(k))
            if v is not None and rel:
                v += s
            ev[k] = v
        ev["chunk"] = [s, e]
    return evs, data.get("subtitles_visible")


def run_eye(url: str, start: float, end: float, model: str = "gemini-3.8-flash",
            chunk_sec: int = 120, workers: int = 4, thinking: str = "low", batch: bool = False) -> dict:
    """[start, end) aralığını chunk_sec'lik dilimlere böler (3 sn bindirmeli) ve Gemini'ye sorar.
    batch=True: tüm dilimler tek bir Batch API işi olarak gönderilir."""
    spans, s = [], float(start)
    while s < end - 1:
        e = min(end, s + chunk_sec)
        spans.append((max(start, s - 3), e))
        s = e
    reqs = [gc.make_request(
        [{"file_data": {"file_uri": url},
          "video_metadata": {"start_offset": f"{int(a)}s", "end_offset": f"{int(b)}s"}},
         {"text": EYE_PROMPT + f"\nThis clip covers {int(a)}s..{int(b)}s of the full video."}],
        temperature=0.2, thinking=thinking, model=model) for a, b in spans]
    t0 = time.time()
    resps = gc.run(model, reqs, batch=batch, label="goz", workers=workers)
    events, chunks, usage = [], [], {}
    for (a, b), resp in zip(spans, resps):
        if not resp:
            chunks.append({"start": a, "end": b, "failed": True})
            log(f"[Göz] {int(a)}-{int(b)} s: YANIT YOK")
            continue
        gc.add_usage(usage, resp, model)
        try:
            evs, vis = _chunk_events(resp, a, b)
        except Exception as ex:
            log(f"[Göz] {int(a)}-{int(b)} s: JSON okunamadı ({ex})")
            chunks.append({"start": a, "end": b, "failed": True})
            continue
        events.extend(evs)
        chunks.append({"start": a, "end": b, "events": len(evs), "subtitles_visible": vis,
                       "usage": resp.get("usageMetadata")})
    usage["seconds"] = round(time.time() - t0, 1)
    events.sort(key=lambda ev: ev.get("t") or 0)
    log(f"[Göz] {len(events)} olay, {usage['seconds']} sn, {sum(1 for c in chunks if c.get('failed'))} başarısız dilim")
    return {"url": url, "model": model, "start": start, "end": end, "events": events,
            "chunks": chunks, "usage": usage, "batch": batch}
