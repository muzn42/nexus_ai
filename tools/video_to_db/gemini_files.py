"""
Gemini Files API ile yerel video kliplerinden Göz çıktısı.

Neden: Gemini, YouTube linkinde ~16 sa 40 dk'dan (≈60.000 sn) sonraki ofsetleri
"invalid argument" ile reddediyor. Uzun videoların kalanı yerel kopyadan 30 dk'lık
720p klipler halinde kesilip (NVENC) yüklenir, Göz istekleri klip içi ofsetlerle batch gönderilir.
Klipler ve yüklemeler work/clips altında tutulur; her adım devam ettirilebilir.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

import requests

from . import gemini_client as gc
from .common import log
from .gemini_eye import EYE_PROMPT, _chunk_events

UPLOAD = "https://generativelanguage.googleapis.com/upload/v1beta/files"


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def cut_clip(video: str, start: float, dur: float, out: str) -> str:
    """[start, start+dur) aralığını 720p / ~1.2 Mbps / sessiz H.264 klip olarak keser (NVENC, olmazsa x264)."""
    if os.path.exists(out) and os.path.getsize(out) > 1_000_000:
        return out
    tmp = out + ".tmp.mp4"
    base = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
            "-i", video, "-an", "-vf", "scale=-2:720", "-r", "30"]
    for enc in (["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "1200k", "-maxrate", "1800k", "-bufsize", "3600k"],
                ["-c:v", "libx264", "-preset", "veryfast", "-b:v", "1200k"]):
        r = subprocess.run(base + enc + ["-movflags", "+faststart", tmp], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1_000_000:
            os.replace(tmp, out)
            return out
        log(f"[Klip] {enc[1]} başarısız: {r.stderr[-200:]}")
    raise RuntimeError(f"klip kesilemedi: {out}")


def upload(path: str, display: str) -> dict:
    key = gc.api_key()
    size = os.path.getsize(path)
    for attempt in range(5):
        try:
            r = requests.post(UPLOAD, headers={
                "x-goog-api-key": key, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": "video/mp4",
                "Content-Type": "application/json"}, json={"file": {"display_name": display}}, timeout=120)
            url = r.headers.get("x-goog-upload-url")
            if not url:
                raise RuntimeError(f"yükleme başlatılamadı HTTP {r.status_code}: {r.text[:200]}")
            with open(path, "rb") as f:
                u = requests.post(url, headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                                                "X-Goog-Upload-Command": "upload, finalize"}, data=f, timeout=3600)
            if u.status_code == 200:
                return u.json()["file"]
            raise RuntimeError(f"yükleme HTTP {u.status_code}: {u.text[:200]}")
        except Exception as ex:
            log(f"[Dosya] {display} yükleme denemesi {attempt + 1}: {ex}")
            time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"yüklenemedi: {path}")


def wait_active(name: str, timeout: float = 1800) -> dict:
    key = gc.api_key()
    t0 = time.time()
    while time.time() - t0 < timeout:
        g = requests.get(f"{gc.BASE}/{name}", headers={"x-goog-api-key": key}, timeout=60)
        if g.status_code == 200:
            st = g.json().get("state")
            if st == "ACTIVE":
                return g.json()
            if st == "FAILED":
                raise RuntimeError(f"{name} işlenemedi")
        time.sleep(10)
    raise RuntimeError(f"{name} {timeout} sn içinde hazır olmadı")


def delete(name: str):
    try:
        requests.delete(f"{gc.BASE}/{name}", headers={"x-goog-api-key": gc.api_key()}, timeout=60)
    except Exception:
        pass


def run_eye_files(video: str, work: str, start: float, end: float, clip_sec: int = 1800, chunk_sec: int = 120,
                  model: str = "gemini-3.8-flash", thinking: str = "low") -> dict:
    """[start, end) aralığı için yerel klip + Files API + Batch ile Göz çıktısı (run_eye ile aynı biçim)."""
    cdir = os.path.join(work, "clips")
    os.makedirs(cdir, exist_ok=True)
    reg_path = os.path.join(cdir, "uploads.json")
    reg = json.load(open(reg_path, encoding="utf-8")) if os.path.exists(reg_path) else {}
    clips, s = [], float(start)
    while s < end - 1:
        clips.append((s, min(end, s + clip_sec)))
        s += clip_sec
    t0 = time.time()
    # 1) kes + yükle (sırayla; yüklenen klip yerel diskten silinir)
    for cs, ce in clips:
        k = str(int(cs))
        if k in reg:
            continue
        path = os.path.join(cdir, f"clip_{int(cs):06d}.mp4")
        cut_clip(video, cs, ce - cs, path)
        f = upload(path, f"gta6-{int(cs)}")
        f = wait_active(f["name"])
        reg[k] = {"name": f["name"], "uri": f["uri"], "start": cs, "end": ce}
        with open(reg_path, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, indent=1)
        os.remove(path)
        log(f"[Dosya] klip {int(cs)}-{int(ce)} sn yüklendi ({len(reg)}/{len(clips)}, {(time.time() - t0) / 60:.0f} dk)")
    # 2) istekler: klip içi ofsetlerle 2 dk'lık dilimler (3 sn bindirmeli)
    spans, reqs = [], []
    for cs, ce in clips:
        info = reg[str(int(cs))]
        a = 0.0
        while a < (ce - cs) - 1:
            b = min(ce - cs, a + chunk_sec)
            a0 = max(0.0, a - 3)
            spans.append((cs, a0, b))
            reqs.append(gc.make_request(
                [{"file_data": {"file_uri": info["uri"], "mime_type": "video/mp4"},
                  "video_metadata": {"start_offset": f"{int(a0)}s", "end_offset": f"{int(b)}s"}},
                 {"text": EYE_PROMPT + f"\nThis clip covers {int(a0)}s..{int(b)}s of the video file."}],
                temperature=0.2, thinking=thinking, model=model))
            a = b
    resps = gc.run(model, reqs, batch=True, label="gozdosya")
    events, chunks, usage = [], [], {}
    for (cs, a, b), resp in zip(spans, resps):
        A, B = cs + a, cs + b
        if not resp:
            chunks.append({"start": A, "end": B, "failed": True, "source": "file"})
            continue
        gc.add_usage(usage, resp, model)
        try:
            evs, vis = _chunk_events(resp, a, b)
        except Exception as ex:
            log(f"[Göz] dosya {int(A)}-{int(B)} s: JSON okunamadı ({ex})")
            chunks.append({"start": A, "end": B, "failed": True, "source": "file"})
            continue
        for ev in evs:
            for kk in ("t", "t_end"):
                if ev.get(kk) is not None:
                    ev[kk] = ev[kk] + cs
            ev["chunk"] = [A, B]
        events.extend(evs)
        chunks.append({"start": A, "end": B, "events": len(evs), "subtitles_visible": vis, "source": "file"})
    usage["seconds"] = round(time.time() - t0, 1)
    log(f"[Göz] dosyalardan {len(events)} olay, {sum(1 for c in chunks if c.get('failed'))} başarısız dilim")
    return {"model": model, "start": start, "end": end, "events": events, "chunks": chunks, "usage": usage,
            "uploads": reg}
