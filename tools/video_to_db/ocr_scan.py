"""
Aşama 2 — OCR doğrulama / tarama.

Videoyu saniyede N kare örnekler ve canlı pipeline ile AYNI yolu izler:
  - Altyazı bandı: auto_subtitle_roi kırpması -> ocr_max_width_sub (1080) küçültme ->
    read_boxes(min_score=0.55) -> Pipeline._filter_and_merge -> _filter_auto_subtitle_boxes
  - Dünya/menü: tam kare -> ocr_max_width_full (1280) -> read_boxes -> _filter_and_merge,
    altyazı bandındakiler hariç.
Veritabanı anahtarı = split_speaker_prefix(...)[1], yani oyunda DB'ye sorulan metnin ta kendisi.
Ardışık örneklerde benzer okumalar tek "görünüm" altında toplanır; en sık/en güvenli okuma seçilir.
"""
from __future__ import annotations

import difflib
import time
from collections import Counter

from .common import log


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _make_engine(device: str):
    from core.ocr_engine import OCREngine
    return OCREngine(version="PP-OCRv6", model_size="small", device=device, word_boxes=True)


def scan_video(path: str, video_offset: float = 0.0, fps: float = 3.0,
               device: str = "gpu", t_from: float = 0.0, t_to: float | None = None, ocr=None) -> dict:
    import cv2
    from core.pipeline import TranslationPipeline as Pipeline
    from core.text_filter import (auto_subtitle_roi, is_in_auto_subtitle_zone,
                                  split_speaker_prefix)

    ocr = ocr or _make_engine(device)
    cap = cv2.VideoCapture(path)
    vfps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = nframes / vfps if nframes else 0
    t_to = min(t_to or dur, dur) if dur else t_to
    step = max(1, int(round(vfps / fps)))
    start_f = int(t_from * vfps)
    end_f = int(t_to * vfps) if t_to else nframes
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    import functools
    filt = functools.partial(Pipeline._filter_and_merge, None)  # self kullanılmıyor
    samples = []
    t0 = time.time()
    ocr_ms = []
    f_idx = start_f
    while f_idx < end_f:
        ok = cap.grab()
        if not ok:
            break
        if (f_idx - start_f) % step:
            f_idx += 1
            continue
        ok, frame = cap.retrieve()
        f_idx += 1
        if not ok:
            continue
        t_local = (f_idx - 1) / vfps
        fh, fw = frame.shape[:2]
        items = []
        # --- altyazı bandı (canlı nexus-sub-pipeline ile aynı)
        sx, sy, sw, sh = auto_subtitle_roi(fw, fh)
        crop = frame[sy:sy + sh, sx:sx + sw]
        small, kx, ky = Pipeline._downscale_if_needed(crop, 1080)
        a = time.time()
        raw = ocr.read_boxes(small, offset_x=sx, offset_y=sy, scale_x=kx, scale_y=ky, min_score=0.55)
        merged = filt(raw, use_noise=True, frame_bgr=None)
        merged = Pipeline._filter_auto_subtitle_boxes(merged, sx, sw, fw, fh)
        for b in sorted(merged, key=lambda b: (b["bbox"][1], b["bbox"][0])):
            items.append(("sub", b))
        # --- dünya / menü (canlı nexus-world-pipeline ile aynı, altyazı bandı hariç)
        small, kx, ky = Pipeline._downscale_if_needed(frame, 1280)
        raw = ocr.read_boxes(small, offset_x=0, offset_y=0, scale_x=kx, scale_y=ky, min_score=0.55)
        merged = filt(raw, use_noise=True, frame_bgr=None)
        ocr_ms.append((time.time() - a) * 1000)
        for b in merged:
            if is_in_auto_subtitle_zone(b["bbox"], fw, fh, None):
                continue
            items.append(("world", b))
        recs = []
        for zone, b in items:
            speaker, body = split_speaker_prefix(b["text"])
            if not body:
                continue
            x, y, w, h = b["bbox"]
            recs.append({"zone": zone, "text": body, "speaker_prefix": speaker, "score": round(b["score"], 3),
                         "bbox": [x / fw, y / fh, w / fw, h / fh]})
        samples.append({"t": round(video_offset + t_local, 2), "items": recs})
        if len(samples) % 150 == 0:
            el = time.time() - t0
            log(f"[OCR] {t_local:.0f}/{(end_f / vfps):.0f} sn işlendi, {len(samples)} kare, {el:.0f} sn")
    cap.release()
    return {"video": path, "offset": video_offset, "fps": fps, "samples": samples,
            "ocr_ms_avg": round(sum(ocr_ms) / max(1, len(ocr_ms)), 1),
            "seconds": round(time.time() - t0, 1)}


def collapse(scan: dict, sim: float = 0.80, min_hits: int = 2) -> list[dict]:
    """
    Kareler arası okumaları "görünüm"lere toplar. Aynı bölgede (zone + yakın y) ardışık
    benzer metinler tek görünüm olur; anahtar olarak en çok okunan varyant seçilir.
    min_hits: en az kaç örnekte görülmeli (geçiş karelerindeki yarım/bozuk okumaları eler).
    """
    gap = 1.6 / max(0.5, scan.get("fps", 3.0)) + 0.5
    open_apps: list[dict] = []
    done: list[dict] = []
    for s in scan["samples"]:
        t = s["t"]
        for it in s["items"]:
            best, br = None, 0.0
            for ap in open_apps:
                if ap["zone"] != it["zone"] or t - ap["t_last"] > gap:
                    continue
                if abs(ap["y"] - it["bbox"][1]) > 0.08:
                    continue
                r = _ratio(ap["key_guess"], it["text"])
                if r > br:
                    best, br = ap, r
            if best is not None and br >= sim:
                best["variants"][it["text"]] += 1
                best["scores"].append(it["score"])
                best["t_last"] = t
                if it["speaker_prefix"]:
                    best["speaker_prefix"][it["speaker_prefix"]] += 1
                best["key_guess"] = best["variants"].most_common(1)[0][0]
            else:
                open_apps.append({"zone": it["zone"], "t_first": t, "t_last": t, "y": it["bbox"][1],
                                  "bbox": it["bbox"], "variants": Counter({it["text"]: 1}),
                                  "scores": [it["score"]], "key_guess": it["text"],
                                  "speaker_prefix": Counter({it["speaker_prefix"]: 1} if it["speaker_prefix"] else {})})
        still = []
        for ap in open_apps:
            (still if t - ap["t_last"] <= gap else done).append(ap)
        open_apps = still
    done.extend(open_apps)
    out = []
    for ap in done:
        hits = sum(ap["variants"].values())
        if hits < min_hits:
            continue
        # En sık okuma; eşitlikte en uzun (fade-in yarım okumalarını yener)
        key = max(ap["variants"].items(), key=lambda kv: (kv[1], len(kv[0])))[0]
        out.append({"zone": ap["zone"], "t_first": ap["t_first"], "t_last": ap["t_last"], "hits": hits,
                    "key": key, "variants": dict(ap["variants"]), "bbox": ap["bbox"],
                    "score": round(sum(ap["scores"]) / len(ap["scores"]), 3),
                    "speaker_prefix": ap["speaker_prefix"].most_common(1)[0][0] if ap["speaker_prefix"] else ""})
    out.sort(key=lambda a: a["t_first"])
    return out


def scan_segmented(path: str, work: str, video_offset: float, start: float, end: float,
                   fps: float = 3.0, device: str = "gpu", seg: float = 600.0) -> dict:
    """Uzun videoyu seg saniyelik parçalar halinde tarar; her parça work/ocr_seg_<s>.json olarak
    kaydedilir ve yeniden çalıştırmada atlanır (gece boyu süren taramada çökme olursa kaldığı yerden devam)."""
    import json
    import os
    ocr = None
    samples, secs, ms = [], 0.0, []
    s = float(start)
    while s < end - 0.5:
        e = min(end, s + seg)
        fpath = os.path.join(work, f"ocr_seg_{int(s):06d}.json")
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                part = json.load(f)
        else:
            if ocr is None:
                ocr = _make_engine(device)
            part = scan_video(path, video_offset=video_offset, fps=fps, device=device,
                              t_from=s - video_offset, t_to=e - video_offset, ocr=ocr)
            with open(fpath + ".tmp", "w", encoding="utf-8") as f:
                json.dump(part, f, ensure_ascii=False)
            os.replace(fpath + ".tmp", fpath)
            log(f"[OCR] parça {int(s)}-{int(e)} sn bitti ({part['seconds']} sn, {len(part['samples'])} kare)")
        samples.extend(part["samples"])
        secs += part.get("seconds", 0)
        ms.append(part.get("ocr_ms_avg", 0))
        s = e
    return {"video": path, "offset": video_offset, "fps": fps, "samples": samples,
            "ocr_ms_avg": round(sum(ms) / max(1, len(ms)), 1), "seconds": round(secs, 1)}


def eye_windows(eye: dict, start: float, end: float, pad: float = 5.0) -> list[tuple[float, float]]:
    """Gemini'nin yazı gördüğü anlardan OCR tarama pencereleri: [t - pad, t_end + pad], birleştirilmiş.
    Uzun süre ekranda kalan yazılar (HUD, görev) kısaltılır: anahtarı okumak için birkaç saniye yeter."""
    spans = []
    for e in eye.get("events", []):
        t = e.get("t")
        if t is None or not e.get("english"):
            continue
        cap = 6 if e.get("type") in ("hud", "menu") else 12
        te = e.get("t_end") if isinstance(e.get("t_end"), (int, float)) and e["t_end"] >= t else t + 4
        te = min(te, t + cap)
        a, b = max(start, t - pad), min(end, te + pad)
        if b > a:
            spans.append((a, b))
    spans.sort()
    out = []
    for a, b in spans:
        if out and a <= out[-1][1] + 1.0:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _seg_ready(fpath: str, mine) -> bool:
    """Dilim dosyası var ve aynı pencerelerle mi taranmış (Göz sonradan genişlerse yeniden taranır)."""
    import json
    import os
    if not os.path.exists(fpath):
        return False
    try:
        with open(fpath, encoding="utf-8") as f:
            w = json.load(f).get("windows")
    except Exception:
        return False
    return w is None or [list(map(float, x)) for x in w] == [[float(a), float(b)] for a, b in mine]


def scan_windows(path: str, work: str, windows: list[tuple[float, float]], fps: float = 3.0,
                 device: str = "gpu", seg: float = 600.0, reverse: bool = False, only_scan: bool = False) -> dict:
    """Yalnız verilen zaman pencerelerini tarar. seg saniyelik dilimler work/ocrw_seg_<s>.json olarak
    kaydedilir (devam ettirilebilir). Aynı anda iki işçi çalışabilir (biri reverse=True): her dilim
    .lock dosyasıyla sahiplenilir. only_scan=True: sonuç toplamadan yalnız tarar (yardımcı işçi)."""
    import json
    import os
    if not windows:
        return {"video": path, "offset": 0, "fps": fps, "samples": [], "ocr_ms_avg": 0, "seconds": 0}
    total = sum(b - a for a, b in windows)
    segs = []
    s = float(int(windows[0][0] // seg * seg))
    while s < windows[-1][1]:
        mine = [(max(a, s), min(b, s + seg)) for a, b in windows if b > s and a < s + seg]
        if mine:
            segs.append((s, mine))
        s += seg
    ocr = None
    t_all = time.time()
    done_sec = 0.0
    def _work_pass():
        nonlocal ocr, done_sec
        for s, mine in (reversed(segs) if reverse else segs):
            fpath = os.path.join(work, f"ocrw_seg_{int(s):06d}.json")
            if _seg_ready(fpath, mine):
                continue
            lock = fpath + ".lock"
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
            except FileExistsError:
                continue
            try:
                if ocr is None:
                    ocr = _make_engine(device)
                part = {"samples": [], "seconds": 0.0, "ocr_ms_avg": 0.0, "windows": [[a, b] for a, b in mine]}
                pm = []
                for a, b in mine:
                    r = scan_video(path, video_offset=0.0, fps=fps, device=device, t_from=a, t_to=b, ocr=ocr)
                    part["samples"].extend(r["samples"])
                    part["seconds"] += r["seconds"]
                    pm.append(r["ocr_ms_avg"])
                part["ocr_ms_avg"] = round(sum(pm) / max(1, len(pm)), 1)
                with open(fpath + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(part, f, ensure_ascii=False)
                os.replace(fpath + ".tmp", fpath)
            finally:
                try:
                    os.remove(lock)
                except OSError:
                    pass
            done_sec += sum(b - a for a, b in mine)
            n_done = sum(1 for x, m in segs if _seg_ready(os.path.join(work, f"ocrw_seg_{int(x):06d}.json"), m))
            log(f"[OCR] dilim {int(s)} sn bitti: {len(mine)} pencere, {len(part['samples'])} kare | "
                f"{n_done}/{len(segs)} dilim hazır, bu işçi {done_sec / 60:.0f} dk video / {(time.time() - t_all) / 60:.0f} dk")

    _work_pass()
    if only_scan:
        return {}
    # diğer işçinin elindeki dilimler bitene kadar bekle; 60 dk'dan eski kilit = çökmüş işçi, devral
    while True:
        missing = [x for x, m in segs if not _seg_ready(os.path.join(work, f"ocrw_seg_{int(x):06d}.json"), m)]
        if not missing:
            break
        for x in missing:
            lk = os.path.join(work, f"ocrw_seg_{int(x):06d}.json.lock")
            if os.path.exists(lk) and time.time() - os.path.getmtime(lk) > 3600:
                os.remove(lk)
        _work_pass()
        time.sleep(30)
    samples, secs, ms = [], 0.0, []
    for s, _ in segs:
        with open(os.path.join(work, f"ocrw_seg_{int(s):06d}.json"), encoding="utf-8") as f:
            part = json.load(f)
        samples.extend(part["samples"])
        secs += part.get("seconds", 0)
        if part.get("ocr_ms_avg"):
            ms.append(part["ocr_ms_avg"])
    samples.sort(key=lambda x: x["t"])
    log(f"[OCR] tüm dilimler hazır: {len(samples)} kare, toplam taranan {total / 3600:.1f} sa")
    return {"video": path, "offset": 0.0, "fps": fps, "samples": samples,
            "ocr_ms_avg": round(sum(ms) / max(1, len(ms)), 1), "seconds": round(secs, 1)}
