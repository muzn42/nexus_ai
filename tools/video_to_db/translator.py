"""
Aşama 3 — Çevirmen + ikinci kontrol turu.

1) Satırlar sahnelere bölünür (altyazılar zaman yakınlığına göre, ekran yazıları türüne göre).
2) Her sahne karakter defteri + terim sözlüğü + sahne bağlamıyla tek istekte çevrilir.
3) Kontrol turu: ayrı bir istek anlam / [TAG] korunumu / altyazı uzunluğu / doğal Türkçe denetler,
   gerekiyorsa düzeltir.
4) Kod tarafı denetimleri: tag kümesi eşitliği, uzunluk oranı, İngilizce kalmış satır,
   DBManager'ın yükleme filtresi (_is_valid_translation). Sorunlular inceleme listesine düşer.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import gemini_client as gc
from .common import GTA6_DIR, log

_TAG_RE = re.compile(r"\[[A-Z0-9\-]{1,10}\]")


def load_json(name: str) -> dict:
    with open(os.path.join(GTA6_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _context_block(chars: dict, gloss: dict) -> str:
    return (
        "CHARACTER NOTEBOOK (JSON):\n" + json.dumps(chars, ensure_ascii=False) +
        "\n\nGLOSSARY (JSON) — 'degismez' items stay EXACTLY as written; 'terimler' must always use the given Turkish;"
        " 'tus_kaliplari' show the button-prompt sentence pattern:\n" + json.dumps(gloss, ensure_ascii=False)
    )


TRANSLATE_SYSTEM = """You are the lead Turkish localizer of GTA 6 (Grand Theft Auto VI), producing the official-quality Turkish patch.
You receive one SCENE: a list of on-screen English lines with their type, speaker, listener, tone and scene description.
Translate each line into natural, idiomatic, spoken Turkish as a professional game subtitler would.

RULES
1. MEANING OVER WORDS. Read the whole scene and the previous conversation first, understand what the speaker really means and
   why they say it, then write what a Turkish native would naturally say in that exact situation. Never translate word-by-word.
2. IDIOMS: when English uses an idiom, slang, wordplay or a set phrase, replace it with the best-fitting Turkish idiom / deyim /
   colloquial expression that carries the same meaning and tone (e.g. 'Another day, another dollar' -> 'Ekmek parası işte',
   'haul ass' -> 'tabanları yağla', 'number two' (toilet) -> 'büyük tuvalet'), not a literal rendering.
   Do NOT overdo it: plain English lines get plain, natural spoken Turkish. Add a Turkish idiom to a plain line only when it fits
   perfectly and sounds like what the character would really say; proverbs (atasözü) almost never. Never pick an idiom that
   changes the meaning or makes the line sound theatrical.
3. CONTINUITY: every line must make sense as a reply to the line before it and lead into the next one (questions and answers,
   jokes and callbacks, sentences split across cards). Keep running jokes, nicknames and terms consistent across scenes.
4. Keep humor, sarcasm and swearing at the same intensity (no softening, no added content).
5. Use the speaker/listener/relationship from the notebook to choose 'sen' vs 'siz' and terms of address. Keep it consistent within the scene.
6. Names, places, brands, agencies, vehicle/weapon models in the glossary 'degismez' list stay exactly as written (Turkish suffixes are added with an apostrophe: Vice City'de, Lucia'yı).
7. Button tags such as [X] [R2] [L2] [TRIANGLE] [LS] must appear in the Turkish exactly as many times and spelled exactly the same; place them where natural ('Press [R2] to accelerate' -> 'Gaz vermek için [R2] tuşuna bas'). Imperatives in hints/objectives use the 2nd person singular ('Arabaya bin.', 'Lucia'yı takip et.').
8. Subtitles: keep them short enough to read: ideally not longer than the English (+20% max). Lines that are a fragment of a sentence split across cards must stay a fragment that continues naturally into the next card.
9. Objective / hint / menu / hud lines: concise UI Turkish, same register as an official console localization; menu items are noun phrases or short imperatives ('Harita', 'Fotoğraf Modu').
10. If a line is ONLY a proper noun/brand/place, output it unchanged. If a line is clearly NOT game UI text (random world signage, license plate, OCR garbage), set "skip": true.
11. Two overlapping subtitles may be merged into one line with an embedded speaker label, e.g.
   "Sit tight. We're gonna check on a couple things Cal: What's he doing with the bag?". Translate BOTH parts and keep the
   label exactly ("... Cal: Çantayla ne yapıyor?"). Never drop part of a line.
12. Never output English words that have a common Turkish equivalent, except names/brands from rule 6.

Return JSON: {"lines": [{"id": <id>, "tr": "<turkish>", "skip": false, "note": "<optional short note for reviewer, e.g. ambiguity>"}],
"new_terms": {"<english term>": "<turkish>"}, "new_speakers": {"<name>": "<gender / role / how they speak, if learned>"}}"""

REVIEW_SYSTEM = """You are the senior Turkish localization QA reviewer for GTA 6. You receive English lines with context and their draft Turkish.
Check each line for:
 (a) meaning errors / mistranslation / missing or added content; does the line make sense after the PREVIOUS lines
     (shown with their Turkish) and before the next ones?
 (f) English idioms/slang rendered literally where a fitting Turkish idiom or colloquial phrase exists (meaning first);
     but also the opposite: forced, theatrical idioms or proverbs added to plain lines should be made plain again,
 (b) [TAG] button tags preserved exactly (same tags, same count),
 (c) subtitle length (should not be much longer than English; must be readable),
 (d) natural spoken Turkish (no translationese), correct sen/siz and consistent terms from the glossary,
 (e) grammar, suffix/apostrophe use with proper nouns, punctuation.
If a line needs a change, give the corrected Turkish in "fixed". Only change what is actually wrong or clearly unnatural.
"severity": "ok" (no change), "minor" (style/naturalness fix), "major" (meaning error, wrong tags, wrong person/address).
Return JSON: {"lines": [{"id": <id>, "severity": "ok|minor|major", "issues": "<short Turkish explanation or empty>", "fixed": "<corrected Turkish or empty>"}]}"""


JUDGE_SYSTEM = """You are an expert Turkish game localization editor. For each item you get the English line, its context and
two Turkish candidates A and B. Pick the better one for an official GTA 6 Turkish subtitle/UI: correct meaning (including slang and
jokes) and fit with the surrounding conversation first, then the more idiomatic Turkish expression, natural spoken Turkish, correct spelling, swearing intensity kept, [TAG] tags preserved, concise.
If both are equally good, pick A. Return JSON: {"choices": [{"id": <id>, "pick": "A" or "B", "why": "<short Turkish reason>"}]}"""


def build_scenes(entries: list[dict], gap: float = 25.0, max_lines: int = 45) -> list[list[int]]:
    """Altyazı + hedef satırlarını zaman yakınlığına göre sahnelere böler; kalan UI satırlarını ayrı toplar."""
    order = sorted((i for i in range(len(entries)) if not entries[i].get("exclude")),
                   key=lambda i: entries[i]["t"])
    scenes, cur, last_t = [], [], None
    for i in order:
        e = entries[i]
        if last_t is not None and (e["t"] - last_t > gap or len(cur) >= max_lines):
            scenes.append(cur)
            cur = []
        cur.append(i)
        last_t = e["t"]
    if cur:
        scenes.append(cur)
    return scenes


def _line_payload(i: int, e: dict, with_tr: str | None = None) -> dict:
    d = {"id": i, "type": e["type"], "t": e["t"], "speaker": e.get("speaker", ""),
         "listener": e.get("listener", ""), "tone": e.get("tone", ""), "scene": e.get("scene", ""),
         "english": e["key"]}
    if with_tr is not None:
        d["turkish"] = with_tr
    return d


def code_checks(en: str, tr: str, etype: str) -> list[str]:
    from core.db_manager import _clean_target, _is_valid_translation, _strip_tag
    issues = []
    if sorted(_TAG_RE.findall(en)) != sorted(_TAG_RE.findall(tr)):
        issues.append("tuş etiketi uyuşmazlığı")
    if etype == "subtitle" and len(en) >= 20 and len(tr) > len(en) * 1.45:
        issues.append(f"altyazı uzun ({len(tr)}/{len(en)} karakter)")
    if tr.strip().lower() == en.strip().lower():
        return issues  # özel ad / marka: aynen kalır, DB'ye yazılmaz
    if not _is_valid_translation(_strip_tag(en).lower(), _clean_target(tr)):
        issues.append("DB yükleyicisi bu satırı 'çevrilmemiş' sayıp atlar")
    return issues


def _parse_lines(resp, field="lines") -> list[dict]:
    try:
        data = gc.response_json(resp) if resp else None
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return (data or {}).get(field, []) if isinstance(data, dict) else []


def translate_entries_single(entries: list[dict], model: str = "gemini-3.8-flash",
                      review_model: str = "gemini-3.8-flash", batch: bool = False,
                      thinking: str | None = "medium") -> dict:
    """Üç tur: çeviri -> kontrol -> hakem. batch=True ise her tur tek bir Batch API işi olur."""
    chars, gloss = load_json("characters.json"), load_json("glossary.json")
    ctx = _context_block(chars, gloss)
    usage_tr, usage_rv, usage_judge = {}, {}, {}
    new_terms, new_speakers = {}, {}
    drafts: dict[int, dict] = {}
    timing = {}

    scenes = build_scenes(entries)
    log(f"[Çeviri] {len(entries)} satır, {len(scenes)} sahne ({'batch' if batch else 'anlık'}, {model})")

    # --- 1) Çeviri: sahneler bağımsız istekler; önceki sahnenin son İngilizce satırları bağlam olarak gider
    reqs = []
    for si, idxs in enumerate(scenes):
        prev = scenes[si - 1][-8:] if si else []
        prev_ctx = [f'{entries[i].get("speaker") or "-"} -> {entries[i].get("listener") or "-"}: {entries[i]["key"]}'
                    for i in prev]
        nxt = scenes[si + 1][:5] if si + 1 < len(scenes) else []
        next_ctx = [f'{entries[i].get("speaker") or "-"}: {entries[i]["key"]}' for i in nxt]
        lines = [_line_payload(i, entries[i]) for i in idxs]
        user = (ctx + "\n\nPREVIOUS SCENE (English, context only, do not translate):\n" +
                json.dumps(prev_ctx, ensure_ascii=False) +
                "\n\nSCENE LINES TO TRANSLATE:\n" + json.dumps(lines, ensure_ascii=False) +
                "\n\nNEXT LINES (context only, do not translate):\n" + json.dumps(next_ctx, ensure_ascii=False))
        reqs.append(gc.make_request([{"text": user}], system=TRANSLATE_SYSTEM, temperature=0.3,
                                    thinking=thinking, model=model))
    t0 = time.time()
    resps = gc.run(model, reqs, batch=batch, label="ceviri")
    timing["translate"] = round(time.time() - t0, 1)
    for resp in resps:
        if not resp:
            continue
        gc.add_usage(usage_tr, resp, model)
        try:
            data = gc.response_json(resp) or {}
        except Exception:
            data = {}
        for ln in (data.get("lines") or []) if isinstance(data, dict) else []:
            try:
                drafts[int(ln["id"])] = ln
            except (KeyError, ValueError, TypeError):
                continue
        if isinstance(data, dict):
            new_terms.update(data.get("new_terms") or {})
            new_speakers.update(data.get("new_speakers") or {})

    # --- 2) Kontrol turu
    reqs = []
    for si, idxs in enumerate(scenes):
        lines = [_line_payload(i, entries[i], drafts.get(i, {}).get("tr", "")) for i in idxs
                 if drafts.get(i) and not drafts[i].get("skip")]
        if not lines:
            continue
        prev = scenes[si - 1][-8:] if si else []
        prev_ctx = [f'{entries[i].get("speaker") or "-"}: {entries[i]["key"]} => {drafts.get(i, {}).get("tr", "")}'
                    for i in prev]
        user = (ctx + "\n\nPREVIOUS LINES (with their Turkish, context only):\n" +
                json.dumps(prev_ctx, ensure_ascii=False) +
                "\n\nLINES TO REVIEW:\n" + json.dumps(lines, ensure_ascii=False))
        reqs.append(gc.make_request([{"text": user}], system=REVIEW_SYSTEM, temperature=0.1,
                                    thinking=thinking, model=review_model))
    t0 = time.time()
    reviews: dict[int, dict] = {}
    for resp in gc.run(review_model, reqs, batch=batch, label="kontrol"):
        if not resp:
            continue
        gc.add_usage(usage_rv, resp, review_model)
        for ln in _parse_lines(resp):
            try:
                reviews[int(ln["id"])] = ln
            except (KeyError, ValueError, TypeError):
                continue
    timing["review"] = round(time.time() - t0, 1)

    # --- 3) Hakem: kontrol turunun her düzeltme önerisi taslağa karşı kör karşılaştırılır
    proposals = [i for i, rv in reviews.items()
                 if (rv.get("fixed") or "").strip() and (drafts.get(i, {}).get("tr") or "").strip()
                 and rv["fixed"].strip() != drafts[i]["tr"].strip() and rv.get("severity") in ("minor", "major")]
    reqs = []
    for k in range(0, len(proposals), 60):
        items = [{**_line_payload(i, entries[i]), "A": drafts[i]["tr"], "B": reviews[i]["fixed"]}
                 for i in proposals[k:k + 60]]
        reqs.append(gc.make_request([{"text": ctx + "\n\nITEMS:\n" + json.dumps(items, ensure_ascii=False)}],
                                    system=JUDGE_SYSTEM, temperature=0.0, thinking=thinking, model=review_model))
    t0 = time.time()
    verdicts = {}
    for resp in gc.run(review_model, reqs, batch=batch, label="hakem"):
        if not resp:
            continue
        gc.add_usage(usage_judge, resp, review_model)
        for c in _parse_lines(resp, "choices"):
            try:
                verdicts[int(c["id"])] = c
            except (KeyError, ValueError, TypeError):
                continue
    timing["judge"] = round(time.time() - t0, 1)
    log(f"[Hakem] {len(proposals)} öneri, {sum(1 for v in verdicts.values() if v.get('pick') == 'B')} kabul")

    out = []
    for i, e in enumerate(entries):
        if e.get("exclude"):
            out.append({**e, "tr": "", "tr_draft": "", "skip": True, "review": "", "review_issues": "", "flags": []})
            continue
        d = drafts.get(i, {})
        rv = reviews.get(i, {})
        tr = (d.get("tr") or "").strip()
        draft = tr
        vd = verdicts.get(i, {})
        fixed = (rv.get("fixed") or "").strip()
        accepted = bool(fixed) and fixed != draft and vd.get("pick") == "B"
        if accepted:
            tr = fixed
        elif fixed and draft and fixed != draft and code_checks(e["key"], draft, e["type"]) \
                and not code_checks(e["key"], fixed, e["type"]):
            tr, accepted = fixed, True   # taslak teknik denetimden kalıyor, düzeltme geçiyor
        flags = []
        if not tr and not d.get("skip"):
            flags.append("çeviri yok")
        if fixed and fixed != draft and not accepted:
            flags.append(f"kontrol önerisi reddedildi ({rv.get('severity')}): {fixed} — {rv.get('issues', '')}"
                         + (f" / hakem: {vd.get('why')}" if vd.get("why") else ""))
        elif accepted and rv.get("severity") == "major":
            flags.append("ciddi düzeltme uygulandı — " + (rv.get("issues") or ""))
        if tr and not d.get("skip"):
            flags.extend(code_checks(e["key"], tr, e["type"]))
        if e.get("gemini_missed"):
            flags.append("yalnız OCR gördü (Gemini kaçırdı) — bağlam zayıf")
        if d.get("note"):
            flags.append("çevirmen notu: " + d["note"])
        out.append({**e, "tr": tr, "tr_draft": draft, "skip": bool(d.get("skip")),
                    "review": rv.get("severity", ""), "review_issues": rv.get("issues", ""),
                    "judge": vd.get("pick", ""), "flags": flags})
    return {"entries": out, "new_terms": new_terms, "new_speakers": new_speakers,
            "usage_translate": usage_tr, "usage_review": usage_rv, "usage_judge": usage_judge,
            "timing": timing, "model": model, "review_model": review_model, "batch": batch}


JUDGE2_SYSTEM = """You are the chief editor of the official GTA 6 Turkish localization. You receive one SCENE in order. For every
line you get the English text with context (type, speaker -> listener, tone, scene) and two Turkish candidates A and B
written by two different translators (B may be missing when both are identical).

FIRST, for every line ask yourself what the English REALLY means in this situation (slang and set phrases depend on context:
e.g. smugglers asking "what's our story?" = what do we tell the cops / our cover story; drug bricks dropped in the sea may be
called "soap"; "let him off" = release him). Both translators often miss such meanings and translate literally.

Decide per line, reading the whole scene as a conversation:
- Pick the candidate whose MEANING is right and that fits the conversation (answers the previous line, leads into the next,
  keeps jokes / callbacks / split sentences coherent), in natural spoken Turkish with the same tone and swearing intensity.
- Prefer a fitting Turkish idiom only where the English uses an idiom/slang or where it fits perfectly; plain lines stay plain;
  forced or theatrical idioms and proverbs are a defect.
- If BOTH candidates have a real error (literal rendering that misses the meaning, wrong meaning, broken continuity,
  unnatural Turkish, wrong sen/siz, missing part, wrong [TAG]s), you MUST write a corrected version yourself:
  "pick": "C" and "final": "<your Turkish>". Never pick the lesser of two wrong translations.
- Button tags like [R2] [L3] must appear exactly as in the English.
- If the line has "highlights" (colored words), give "hl": the exact substring(s) of the FINAL Turkish that should carry the same
  color, e.g. English "Go to the car." with car=yellow -> final "Arabaya git." hl [{"en": "car", "tr": "Arabaya", "color": "yellow"}].
  For pick A/B you may copy that candidate's hl if it is correct.
- "doubt": true only if you are unsure about the meaning (unclear English, possible OCR error, missing context).

Return JSON: {"lines": [{"id": <id>, "pick": "A"|"B"|"C", "final": "<only when C>", "hl": [...], "why": "<short Turkish reason>",
"doubt": false}]}"""

HL_RULE = """
13. Some lines have "highlights": words drawn in another color on screen. Return "hl" for them: for each highlighted English
    phrase, the exact substring of YOUR Turkish line that carries the same meaning, plus its color:
    [{"en": "car", "tr": "Arabaya", "color": "yellow"}]. Omit "hl" when the line has no highlights."""


def _parse_json(resp):
    try:
        return gc.response_json(resp) if resp else None
    except Exception:
        return None


def _hl_ok(hl, text):
    good = []
    for h in hl or []:
        if isinstance(h, dict) and h.get("tr") and h["tr"] in text:
            good.append({"en": h.get("en", ""), "tr": h["tr"], "color": h.get("color", "")})
    return good


def translate_entries(entries: list[dict], models: list[str] | None = None, judge_model: str = "gemini-4-neon",
                      batch: bool = False, thinking: str | None = "medium", **_ignored) -> dict:
    """İki (veya daha fazla) çevirmen modeli aynı sahneyi bağımsız çevirir; hakem modeli sahnenin
    tamamını okuyarak her satırda en iyisini seçer veya düzeltir. batch=True: her tur tek Batch işi."""
    from concurrent.futures import ThreadPoolExecutor
    models = models or ["gemini-3.8-flash", "gemini-4-hydrogen"]
    chars, gloss = load_json("characters.json"), load_json("glossary.json")
    ctx = _context_block(chars, gloss)
    system = TRANSLATE_SYSTEM.replace("\n\nReturn JSON:", HL_RULE + "\n\nReturn JSON:", 1)
    system = system.replace('"note": "<optional short note for reviewer, e.g. ambiguity>"}]',
                            '"note": "<optional short note for reviewer, e.g. ambiguity>", "hl": []}]', 1)
    usage = {m: {} for m in models}
    usage_judge = {}
    timing = {}
    new_terms, new_speakers = {}, {}

    def payload(i, e):
        d = _line_payload(i, e)
        if e.get("highlights"):
            d["highlights"] = e["highlights"]
        return d

    scenes = build_scenes(entries)
    log(f"[Çeviri] {len(entries)} satır, {len(scenes)} sahne, çevirmenler {models}, hakem {judge_model}"
        f" ({'batch' if batch else 'anlık'})")
    reqs = []
    for si, idxs in enumerate(scenes):
        prev = scenes[si - 1][-8:] if si else []
        nxt = scenes[si + 1][:5] if si + 1 < len(scenes) else []
        prev_ctx = [f'{entries[i].get("speaker") or "-"} -> {entries[i].get("listener") or "-"}: {entries[i]["key"]}'
                    for i in prev]
        next_ctx = [f'{entries[i].get("speaker") or "-"}: {entries[i]["key"]}' for i in nxt]
        user = (ctx + "\n\nPREVIOUS SCENE (English, context only, do not translate):\n" +
                json.dumps(prev_ctx, ensure_ascii=False) +
                "\n\nSCENE LINES TO TRANSLATE:\n" + json.dumps([payload(i, entries[i]) for i in idxs], ensure_ascii=False) +
                "\n\nNEXT LINES (context only, do not translate):\n" + json.dumps(next_ctx, ensure_ascii=False))
        reqs.append(user)

    # --- 1) Adaylar: modeller paralel (her biri kendi batch işi)
    def run_model(m):
        rq = [gc.make_request([{"text": u}], system=system, temperature=0.3, thinking=thinking, model=m) for u in reqs]
        return m, gc.run(m, rq, batch=batch, label="ceviri-" + m.split("-")[-1])
    t0 = time.time()
    cands: dict[str, dict[int, dict]] = {m: {} for m in models}
    with ThreadPoolExecutor(max_workers=len(models)) as ex:
        for m, resps in ex.map(run_model, models):
            for resp in resps:
                if not resp:
                    continue
                gc.add_usage(usage[m], resp, m)
                data = _parse_json(resp)
                if not isinstance(data, dict):
                    continue
                for ln in data.get("lines") or []:
                    try:
                        cands[m][int(ln["id"])] = ln
                    except (KeyError, ValueError, TypeError):
                        continue
                new_terms.update(data.get("new_terms") or {})
                new_speakers.update(data.get("new_speakers") or {})
            log(f"[Çeviri] {m}: {len(cands[m])} satır")
    timing["candidates"] = round(time.time() - t0, 1)

    # --- 2) Hakem: sahne sahne, sıralı konuşma olarak
    mA, mB = models[0], (models[1] if len(models) > 1 else None)
    jreqs, jscenes = [], []
    for si, idxs in enumerate(scenes):
        items = []
        for i in idxs:
            a = cands[mA].get(i, {})
            b = cands[mB].get(i, {}) if mB else {}
            if a.get("skip") and (not mB or b.get("skip")):
                continue
            it = payload(i, entries[i])
            it["A"] = (a.get("tr") or "").strip()
            if a.get("hl"):
                it["A_hl"] = a["hl"]
            tb = (b.get("tr") or "").strip()
            if tb and tb != it["A"]:
                it["B"] = tb
                if b.get("hl"):
                    it["B_hl"] = b["hl"]
            if not it["A"] and tb:
                it["A"], it["B"] = tb, ""
            items.append(it)
        if not items:
            continue
        prev = scenes[si - 1][-4:] if si else []
        prev_ctx = [f'{entries[i].get("speaker") or "-"}: {entries[i]["key"]}' for i in prev]
        user = (ctx + "\n\nPREVIOUS LINES (English, context):\n" + json.dumps(prev_ctx, ensure_ascii=False) +
                "\n\nSCENE (in order):\n" + json.dumps(items, ensure_ascii=False))
        jreqs.append(gc.make_request([{"text": user}], system=JUDGE2_SYSTEM, temperature=0.1,
                                     thinking="high", model=judge_model))
        jscenes.append(si)
    t0 = time.time()
    verdicts = {}
    for resp in gc.run(judge_model, jreqs, batch=batch, label="hakem"):
        if not resp:
            continue
        gc.add_usage(usage_judge, resp, judge_model)
        data = _parse_json(resp)
        for v in (data or {}).get("lines", []) if isinstance(data, dict) else []:
            try:
                verdicts[int(v["id"])] = v
            except (KeyError, ValueError, TypeError):
                continue
    timing["judge"] = round(time.time() - t0, 1)

    out, picks = [], {"A": 0, "B": 0, "C": 0, "-": 0}
    for i, e in enumerate(entries):
        if e.get("exclude"):
            out.append({**e, "tr": "", "skip": True, "flags": [], "candidates": {}})
            continue
        a = cands[mA].get(i, {})
        b = cands[mB].get(i, {}) if mB else {}
        ta, tb = (a.get("tr") or "").strip(), (b.get("tr") or "").strip()
        skip = bool(a.get("skip")) and (not mB or bool(b.get("skip")))
        v = verdicts.get(i, {})
        pick = v.get("pick") if v.get("pick") in ("A", "B", "C") else "-"
        if pick == "C" and (v.get("final") or "").strip():
            tr, hl = v["final"].strip(), v.get("hl") or []
        elif pick == "B" and tb:
            tr, hl = tb, v.get("hl") or b.get("hl") or []
        else:
            tr, hl = (ta or tb), v.get("hl") or a.get("hl") or b.get("hl") or []
            if pick in ("B", "C"):
                pick = "-"
        picks[pick] = picks.get(pick, 0) + 1
        flags = []
        if tr and not skip and code_checks(e["key"], tr, e["type"]):
            alts = [x for x in (ta, tb) if x and x != tr and not code_checks(e["key"], x, e["type"])]
            if alts:
                flags.append(f"hakem seçimi teknik denetimden kaldı ({'; '.join(code_checks(e['key'], tr, e['type']))}), diğer aday kullanıldı")
                tr = alts[0]
        if not tr and not skip:
            flags.append("çeviri yok")
        if tr and not skip:
            flags.extend(code_checks(e["key"], tr, e["type"]))
        hl_good = _hl_ok(hl, tr)
        if e.get("highlights") and not hl_good:
            flags.append("renkli kelime eşlenemedi")
        if v.get("doubt"):
            flags.append("hakem emin değil: " + (v.get("why") or ""))
        if pick == "C":
            flags.append("hakem kendisi düzeltti: " + (v.get("why") or ""))
        if e.get("gemini_missed"):
            flags.append("yalnız OCR gördü (Gemini kaçırdı) — bağlam zayıf")
        out.append({**e, "tr": tr, "tr_draft": ta, "skip": skip, "pick": pick, "judge_why": v.get("why", ""),
                    "highlights_tr": hl_good, "candidates": {mA: ta, **({mB: tb} if mB else {})},
                    "review": "C" if pick == "C" else "", "review_issues": "", "flags": flags})
    log(f"[Hakem] seçimler: {picks}")
    return {"entries": out, "new_terms": new_terms, "new_speakers": new_speakers,
            "usage_translate": usage, "usage_review": {}, "usage_judge": usage_judge, "picks": picks,
            "timing": timing, "model": "+".join(models), "review_model": judge_model, "batch": batch}
