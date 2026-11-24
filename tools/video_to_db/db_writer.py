"""
Sonuçları data/gta6_ceviri.db'ye yazar.

- DBManager yalnız `translations(source_text PRIMARY KEY, target_text)` tablosunu okur; şema değişmez.
- Ek bilgi (tür, konuşan, dinleyen, ton, sahne, video/zaman, kontrol durumu) ayrı
  `video_entries` tablosunda tutulur; oyun içi arama hızını etkilemez.
- Mevcut kayıtlar bozulmaz: bu aracın yazmadığı (video_entries'te kaydı olmayan) bir anahtar
  zaten varsa ÜZERİNE YAZILMAZ, çakışma olarak raporlanır. Aracın kendi önceki kayıtları
  (ör. aynı part'ı yeniden işlerken) güncellenir. Part 2, 3... aynı DB'ye eklenir.
- Yazmadan önce DB'nin zaman damgalı yedeği alınır.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time

META_SQL = """
CREATE TABLE IF NOT EXISTS video_entries (
    source_text TEXT PRIMARY KEY,
    target_text TEXT,
    category TEXT,          -- subtitle / objective / hint / menu / hud
    speaker TEXT,
    listener TEXT,
    tone TEXT,
    scene TEXT,
    video_id TEXT,
    part TEXT,
    t_seconds REAL,
    review TEXT,            -- ok / minor / major / ''
    flags TEXT,
    model TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def write_db(db_path: str, entries: list[dict], video_id: str, part: str, model: str,
             backup_dir: str | None = None, dry_run: bool = False) -> dict:
    stats = {"inserted": 0, "updated": 0, "conflict_existing": [], "skipped": 0, "dup_in_run": 0}
    if os.path.exists(db_path) and not dry_run:
        bdir = backup_dir or os.path.dirname(db_path)
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, os.path.basename(db_path) + time.strftime(".%Y%m%d-%H%M%S.bak"))
        shutil.copy2(db_path, bpath)
        stats["backup"] = bpath
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS translations (source_text TEXT PRIMARY KEY, target_text TEXT)")
        conn.execute(META_SQL)
        have = {r[1] for r in conn.execute("PRAGMA table_info(video_entries)")}
        for col in ("highlights", "zone", "bbox", "pick", "candidates"):
            if col not in have:
                conn.execute(f"ALTER TABLE video_entries ADD COLUMN {col} TEXT")
        seen = set()
        for e in entries:
            src, tr = (e.get("key") or "").strip(), (e.get("tr") or "").strip()
            if e.get("skip") or not src or not tr or e.get("exclude"):
                stats["skipped"] += 1
                continue
            low = src.lower()
            if tr.lower() == low:      # özel ad: DBManager zaten yüklemez
                stats["skipped"] += 1
                continue
            if low in seen:
                stats["dup_in_run"] += 1
                continue
            seen.add(low)
            row = conn.execute("SELECT target_text FROM translations WHERE lower(source_text)=?", (low,)).fetchone()
            ours = conn.execute("SELECT video_id FROM video_entries WHERE lower(source_text)=?", (low,)).fetchone()
            if row and ours and ours[0] != video_id:
                # başka videodan (ör. Part 1) gelen, oyunda denenmiş satır: üzerine yazma
                stats["kept_other_video"] = stats.get("kept_other_video", 0) + 1
                continue
            if row and not ours:
                stats["conflict_existing"].append({"key": src, "existing": row[0], "new": tr})
                continue
            if row:
                conn.execute("DELETE FROM translations WHERE lower(source_text)=?", (low,))
                conn.execute("DELETE FROM video_entries WHERE lower(source_text)=?", (low,))
                stats["updated"] += 1
            else:
                stats["inserted"] += 1
            conn.execute("INSERT INTO translations (source_text, target_text) VALUES (?, ?)", (src, tr))
            conn.execute(
                "INSERT INTO video_entries (source_text, target_text, category, speaker, listener, tone, scene,"
                " video_id, part, t_seconds, review, flags, model, highlights, zone, bbox, pick, candidates)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (src, tr, e.get("type", ""), e.get("speaker", ""), e.get("listener", ""), e.get("tone", ""),
                 e.get("scene", ""), video_id, part, e.get("t"), e.get("review", ""),
                 " | ".join(e.get("flags") or []), model,
                 json.dumps(e.get("highlights_tr") or [], ensure_ascii=False), e.get("zone", ""),
                 json.dumps(e.get("bbox") or []), e.get("pick", ""),
                 json.dumps(e.get("candidates") or {}, ensure_ascii=False)))
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        stats["total_rows"] = conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
    finally:
        conn.close()
    return stats
