"""
NEXUS AI — YouTube oynanış videosundan GTA 6 çeviri veritabanı üretici.

Kullanım (proje kökünden):
  python -m tools.video_to_db run --url URL --video parca.mp4 --start 903 --end 1503 --part part1 --work WORKDIR
Ara adımlar ayrı ayrı da çalıştırılabilir (eye / ocr / align / translate / write); her adım
WORKDIR içine JSON bırakır ve varsa yeniden kullanır (--force ile yeniden hesaplar).

Video parçası (OCR için, sadece görüntü yeterli) yt-dlp ile:
  yt-dlp -f 299 --download-sections "*00:15:03-00:25:03" --ffmpeg-location <ffmpeg> -o parca.mp4 URL
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time

from .common import DEFAULT_DB, GTA6_DIR, log


def _p(work, name):
    return os.path.join(work, name)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else (url or "")


def step_eye(a):
    out = _p(a.work, "eye.json")
    if os.path.exists(out) and not a.force:
        return _load(out)
    from .gemini_eye import run_eye
    r = run_eye(a.url, a.start, a.end, model=a.eye_model, chunk_sec=a.chunk, batch=a.batch)
    _save(out, r)
    return r


def step_ocr(a):
    out = _p(a.work, "ocr.json")
    if os.path.exists(out) and not a.force:
        return _load(out)
    from .ocr_scan import collapse, eye_windows, scan_segmented, scan_windows
    voff = a.start if a.video_offset is None else a.video_offset
    if a.ocr_mode == "eye":
        wins = eye_windows(_load(_p(a.work, "eye.json")), a.start, a.end)
        log(f"[OCR] Göz pencereleri: {len(wins)} pencere, {sum(b - x for x, b in wins) / 3600:.1f} sa "
            f"({(a.end - a.start) / 3600:.1f} sa videonun)")
        scan = scan_windows(a.video, a.work, wins, fps=a.fps, device=a.device)
    else:
        scan = scan_segmented(a.video, a.work, video_offset=voff, start=a.start, end=a.end, fps=a.fps, device=a.device)
    apps = collapse(scan)
    r = {"apps": apps, "ocr_ms_avg": scan["ocr_ms_avg"], "seconds": scan["seconds"],
         "frames": len(scan["samples"]), "fps": a.fps}
    _save(_p(a.work, "ocr_raw.json"), scan)
    _save(out, r)
    return r


def step_align(a, eye, ocr):
    from .align import align
    r = align(eye, ocr["apps"])
    _save(_p(a.work, "aligned.json"), r)
    return r


def step_translate(a, aligned):
    out = _p(a.work, "translated.json")
    if os.path.exists(out) and not a.force:
        return _load(out)
    from .translator import translate_entries
    models = [m.strip() for m in a.tr_models.split(",") if m.strip()]
    r = translate_entries(aligned["entries"], models=models, judge_model=a.judge_model, batch=a.batch)
    _save(out, r)
    return r


def _merge_learned(tr):
    """Çevirmenin öğrendiği yeni terim/konuşmacıları kalıcı dosyalara 'öneri' olarak ekler."""
    for fname, key, src in (("glossary.json", "oneriler", tr.get("new_terms")),
                            ("characters.json", "yeni_konusmacilar", tr.get("new_speakers"))):
        if not src:
            continue
        path = os.path.join(GTA6_DIR, fname)
        data = _load(path)
        bucket = data.setdefault(key, {})
        for k, v in src.items():
            bucket.setdefault(k, v)
        _save(path, data)


def write_review(a, tr, aligned):
    rows = [e for e in tr["entries"] if e.get("flags") or e.get("review") in ("minor", "major")]
    path = os.path.join(GTA6_DIR, f"inceleme_{a.part}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# İnceleme listesi — {a.part} ({video_id(a.url)}, {a.start:.0f}-{a.end:.0f} sn)\n\n")
        f.write("| zaman | tür | konuşan | İngilizce (OCR anahtarı) | Türkçe | taslak | sorun |\n|---|---|---|---|---|---|---|\n")
        for e in rows:
            mm = f"{int(e['t']) // 60:02d}:{int(e['t']) % 60:02d}"
            draft = e["tr_draft"] if e["tr_draft"] != e["tr"] else ""
            issues = "; ".join(filter(None, [e.get("review_issues", "")] + e.get("flags", [])))
            f.write("| " + " | ".join(str(x).replace("|", "/") for x in (
                mm, e["type"], e.get("speaker", ""), e["key"], e["tr"], draft, issues)) + " |\n")
        if aligned.get("missed_by_ocr"):
            f.write("\n## Gemini gördü, OCR okuyamadı (DB'ye yazılmadı)\n\n")
            for m in aligned["missed_by_ocr"]:
                t = m.get("t") or 0
                f.write(f"- {int(t) // 60:02d}:{int(t) % 60:02d} [{m.get('type')}] {m.get('speaker') or ''}: {m.get('english')}\n")
    return path


def write_table(a, tr):
    """Yan yana tam tablo: zaman | tür | konuşan -> dinleyen | İngilizce (OCR anahtarı) | Türkçe."""
    path = os.path.join(GTA6_DIR, f"tablo_{a.part}.md")
    rows = sorted((e for e in tr["entries"] if not e.get("exclude") and not e.get("skip") and e.get("tr")),
                  key=lambda e: e["t"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {a.part} — {video_id(a.url)} {int(a.start) // 60:02d}:{int(a.start) % 60:02d}"
                f"–{int(a.end) // 60:02d}:{int(a.end) % 60:02d} ({len(rows)} satır)\n\n")
        f.write("| zaman | tür | konuşan → dinleyen | İngilizce (OCR anahtarı) | Türkçe |\n|---|---|---|---|---|\n")
        for e in rows:
            t = int(e["t"])
            who = f"{e.get('speaker') or ''} → {e.get('listener') or ''}" if e.get("speaker") else ""
            f.write("| " + " | ".join(str(x).replace("|", "/") for x in (
                f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}", e["type"], who, e["key"], e["tr"])) + " |\n")
    return path


def main():
    ap = argparse.ArgumentParser(prog="python -m tools.video_to_db")
    ap.add_argument("cmd", choices=["run", "eye", "ocr", "translate", "write"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--video", help="OCR için indirilmiş video parçası (yalnız görüntü yeterli)")
    ap.add_argument("--start", type=float, required=True, help="parçanın tam videodaki başlangıç saniyesi")
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--part", default="part1")
    ap.add_argument("--work", required=True, help="ara JSON dosyaları için klasör (gitignore'lı/scratch)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--fps", type=float, default=3.0)
    ap.add_argument("--device", default="gpu")
    ap.add_argument("--chunk", type=int, default=120)
    ap.add_argument("--eye-model", default="gemini-3.8-flash")
    ap.add_argument("--tr-model", default="gemini-3.8-flash")
    ap.add_argument("--review-model", default="gemini-3.8-flash")
    ap.add_argument("--tr-models", default="gemini-3.8-flash,gemini-4-hydrogen",
                    help="virgülle ayrılmış çevirmen modelleri (her biri bir aday üretir)")
    ap.add_argument("--judge-model", default="gemini-4-neon", help="adaylar arasında seçen / düzelten hakem")
    ap.add_argument("--video-offset", type=float, default=None,
                    help="--video dosyasının tam videodaki başlangıç saniyesi (tam video için 0; varsayılan --start)")
    ap.add_argument("--batch", action="store_true", help="Gemini Batch API (yarı fiyat, asenkron) kullan")
    ap.add_argument("--key-file", help="Gemini API anahtarının bulunduğu metin dosyası (yazdırılmaz)")
    ap.add_argument("--ocr-mode", choices=["full", "eye"], default="full",
                    help="eye: OCR yalnız Gemini'nin yazı gördüğü anların ±8 sn'sini tarar (uzun videolar için)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="DB'ye yazma, sadece raporla")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    from . import gemini_client
    from .gemini_client import set_key_file
    set_key_file(a.key_file)
    gemini_client.BATCH_STATE_DIR = _p(a.work, "batches")
    timing = {}

    t = time.time(); eye = step_eye(a); timing["eye"] = round(time.time() - t, 1)
    if a.cmd == "eye":
        return
    t = time.time(); ocr = step_ocr(a); timing["ocr"] = round(time.time() - t, 1)
    if a.cmd == "ocr":
        return
    aligned = step_align(a, eye, ocr)
    log(f"[Eşleme] ofset {aligned['offset']} sn, {len(aligned['entries'])} OCR satırı, "
        f"Gemini {aligned['events_total']} olay, OCR'ın kaçırdığı {len(aligned['missed_by_ocr'])}")
    t = time.time(); tr = step_translate(a, aligned); timing["translate"] = round(time.time() - t, 1)
    _merge_learned(tr)
    review_path = write_review(a, tr, aligned)
    table_path = write_table(a, tr)
    log(f"[Rapor] {review_path} ve {table_path} yazıldı")
    if a.cmd == "translate":
        return
    from .db_writer import write_db
    stats = write_db(a.db, tr["entries"], video_id(a.url), a.part, tr["model"],
                     backup_dir=os.path.join(GTA6_DIR, "backups"), dry_run=a.dry_run)
    report = {"timing_s": timing, "eye_usage": eye.get("usage"), "translate_usage": tr["usage_translate"],
              "review_usage": tr.get("usage_review"), "picks": tr.get("picks"), "translate_timing": tr.get("timing"), "judge_usage": tr.get("usage_judge"), "ocr_ms_avg": ocr.get("ocr_ms_avg"), "db": stats,
              "review_file": review_path}
    _save(_p(a.work, "report.json"), report)
    log(json.dumps({k: v for k, v in report.items() if k != "db"}, ensure_ascii=False))
    log(f"[DB] eklenen {stats['inserted']}, güncellenen {stats['updated']}, atlanan {stats['skipped']}, "
        f"çakışma {len(stats['conflict_existing'])}, toplam {stats.get('total_rows')}")


if __name__ == "__main__":
    main()
