"""
NEXUS AI v3 — Satır İçi Tuş İkonları (Button Icons)

Tam yama modunda buzlu cam yaması "Press R2 to fire" gibi ipuçlarındaki
PlayStation/Xbox tuş ikonlarını da örter. Bu modül OCR kelime kutularından
(OCREngine.read_boxes → box["words"]) tuş kelimelerini bulur, ikonun gerçek
piksel bölgesini kare üzerinden hassaslaştırır ve orijinal pikselleri saklar:

    box["icons"] = [{"token": "R2", "bbox": (x, y, w, h), "rgb": ndarray(h, w, 3) uint8}]

Yama katmanı (ui/qt/patch_overlay.py) Türkçe çevirideki "[R2]" etiketinin yerine
bu pikselleri satır içi çizer: "Ateş etmek için [R2 ikonu] tuşuna bas".

Kurallar:
  - Hızlı (< 1 ms / kutu): yalnızca kelime çevresindeki küçük şerit işlenir.
  - Asla hata fırlatmaz (pipeline'ı durdurmamalı).
  - OCR'ın hiç görmediği ikonları bulmak kapsam dışıdır.
"""
import re

import numpy as np

try:  # text_filter paralel düzenleniyor → içe aktarma başarısız olursa yerel yedek
    from core.text_filter import button_token as _tf_button_token
except Exception:  # pragma: no cover - yalnızca yedek yol
    _tf_button_token = None

# Yedek: kod-benzeri tuşlar (bağlamsız güvenle tanınabilenler)
_FALLBACK_RE = re.compile(
    r"^[\(\[\{<]*(R[123]|L[123]|LB|RB|LT|RT|LS|RS|X|O|A|B|Y|R|L)[\)\]\}>]*[.,:;!?]*$",
    re.IGNORECASE,
)
# Metindeki etiketler: "[R2]", "[TRIANGLE]"
_TAG_RE = re.compile(r"\[([A-Za-z0-9\-_]{1,10})\]")
# Bağlamsız güvenilir (rakam/çift harf) kod tuşları
_CODE_RE = re.compile(r"^(R[123]|L[123]|LB|RB|LT|RT|LS|RS)$")

_ICON_V_PAD = 0.15     # İkon rozeti metinden ~%15 daha uzun olabilir
_MAX_W_RATIO = 1.6     # İkon genişliği ≤ 1.6 × ikon yüksekliği
_INK_DIFF = 38         # Arka plandan bu kadar (gri seviye) farklı piksel = mürekkep


def button_token(word: str):
    """Kelimeyi kanonik tuş adına çevirir ('(r2)' -> 'R2'); tuş değilse None."""
    if _tf_button_token is not None:
        try:
            return _tf_button_token(word)
        except Exception:
            pass
    m = _FALLBACK_RE.match(str(word or "").strip())
    return m.group(1).upper() if m else None


def _box_tags(text: str) -> set:
    """Temizlenmiş kutu metnindeki [TOKEN] etiketleri (büyük harf)."""
    return {m.group(1).upper() for m in _TAG_RE.finditer(text or "")}


def _split_word(word: dict) -> list:
    """'L1/R1' gibi eğik çizgili kelimeyi karakter oranına göre alt kutulara böler."""
    text = str(word.get("text", ""))
    bbox = word.get("bbox")
    if not bbox or len(bbox) != 4:
        return []
    if "/" not in text:
        return [(text, tuple(int(v) for v in bbox))]
    x, y, w, h = [int(v) for v in bbox]
    total = max(1, len(text))
    out, pos = [], 0
    for part in text.split("/"):
        if part:
            px = x + int(round(w * pos / total))
            pw = max(1, int(round(w * len(part) / total)))
            out.append((part, (px, y, pw, h)))
        pos += len(part) + 1
    return out


def _to_bgr(frame):
    if frame.ndim == 2:
        return np.repeat(frame[:, :, None], 3, axis=2)
    if frame.shape[2] >= 3:
        return frame[:, :, :3]
    return None


def _row_run(row_has_ink, center: int):
    """Merkez satırı içeren kesintisiz mürekkep satır dizisi (alt/üst komşu ikonu dışlar)."""
    n = len(row_has_ink)
    if n == 0:
        return None
    c = max(0, min(n - 1, int(center)))
    if not row_has_ink[c]:
        idx = np.nonzero(row_has_ink)[0]
        if idx.size == 0:
            return None
        c = int(idx[np.argmin(np.abs(idx - c))])
    a = c
    while a - 1 >= 0 and row_has_ink[a - 1]:
        a -= 1
    b = c
    while b + 1 < n and row_has_ink[b + 1]:
        b += 1
    return a, b


def refine_icon_bbox(frame_bgr, word_bbox: tuple, line_h: float = None) -> tuple:
    """
    Kelime kutusundan başlayıp gerçek ikon bölgesini bulur:
      - Dikey: kelime merkezine göre satır yüksekliği ±%15.
      - Yatay: kelime merkezini içeren, kesintisiz yüksek kontrastlı sütun dizisine
        yaslanır; genişlik ≤ 1.6 × ikon yüksekliği.
    Döner: (x, y, w, h) tam kare koordinatı.
    """
    fh, fw = frame_bgr.shape[:2]
    wx, wy, ww, wh = [int(v) for v in word_bbox]
    # Kelime yüksekliği esas alınır (çok satırlı kutuda satır yüksekliği komşu satıra taşar)
    base_h = float(wh)
    if line_h and line_h > 0:
        base_h = max(float(wh), min(float(line_h), wh * 1.15))
    icon_h = base_h * (1.0 + 2 * _ICON_V_PAD)
    cy = wy + wh * 0.5
    y1 = max(0, int(round(cy - icon_h * 0.5)))
    y2 = min(fh, int(round(cy + icon_h * 0.5)))
    if y2 - y1 < 2:
        return (wx, wy, ww, wh)
    icon_h = y2 - y1
    max_w = int(round(icon_h * _MAX_W_RATIO))
    cx = wx + ww * 0.5

    # Arama şeridi: kelimenin iki yanında ikon yüksekliği kadar pay
    sx1 = max(0, int(round(cx - max_w)))
    sx2 = min(fw, int(round(cx + max_w)))
    if sx2 - sx1 < 2:
        return (wx, y1, ww, icon_h)
    strip = _to_bgr(frame_bgr[y1:y2, sx1:sx2])
    if strip is None:
        return (wx, y1, ww, icon_h)
    gray = strip.astype(np.int16).sum(axis=2) // 3
    # Arka plan: şeridin kenar satırlarının medyanı (rozet genelde ortada durur)
    edge = np.concatenate([gray[0], gray[-1]])
    bg = int(np.median(edge))
    ink = np.abs(gray - bg) > _INK_DIFF
    col_ink = ink.mean(axis=0) > 0.08   # sütunun en az %8'i mürekkep

    c = int(round(cx)) - sx1
    c = max(0, min(len(col_ink) - 1, c))
    # Merkezde mürekkep yoksa en yakın mürekkepli sütuna kay (kelime kutusu içinde)
    if not col_ink[c]:
        lo_w = max(0, wx - sx1)
        hi_w = min(len(col_ink) - 1, wx + ww - sx1)
        idx = np.nonzero(col_ink[lo_w:hi_w + 1])[0]
        if idx.size == 0:
            return (wx, y1, ww, icon_h)
        c = lo_w + int(idx[np.argmin(np.abs(idx + lo_w - c))])

    # Kesintisiz dizi (boşluk toleransı yok: ikon ile bitişik harf arasındaki 1 px'lik
    # boşluk bile ayırıcıdır — örn. GTA '(X)GET UP')
    left = c
    while left - 1 >= 0 and col_ink[left - 1]:
        left -= 1
    right = c
    n = len(col_ink)
    while right + 1 < n and col_ink[right + 1]:
        right += 1
    # Dikey: dizideki mürekkep satırlarına yaslan (alt/üst satırdaki ikonla çakışmasın)
    rr = _row_run(ink[:, left:right + 1].any(axis=1), cy - y1)
    if rr is not None and (rr[1] - rr[0] + 1) >= wh * 0.6:
        ny1 = max(0, y1 + rr[0] - 1)
        ny2 = min(fh, y1 + rr[1] + 2)
        y1, icon_h = ny1, ny2 - ny1

    rx1, rx2 = sx1 + left, sx1 + right + 1
    # Kelime kutusunu en az kapsasın
    rx1 = min(rx1, wx)
    rx2 = max(rx2, wx + ww)
    if rx2 - rx1 > max_w:
        # Komşu metne taştı → kelime merkezine göre sınırla
        half = max_w * 0.5
        rx1 = int(round(max(rx1, cx - half)))
        rx2 = int(round(min(rx2, cx + half)))
    rx1 = max(0, rx1)
    rx2 = min(fw, rx2)
    return (rx1, y1, max(1, rx2 - rx1), icon_h)




# OCR'ın hiç okuyamadığı ikonlar (beyaz daire içinde X / O / R / □ / △) için sentetik
# etiket: BTN, BTN2, BTN3... Kırpılan gerçek pikseller çizildiği için tuş görsel olarak korunur.
GLYPH_TOKEN = "BTN"
# Ara boşluk ikonu yalnızca bu fiillerden sonra veya ardından "to" geliyorsa kabul edilir
_PRESS_VERBS = {"use", "press", "hold", "tap", "push", "release", "click", "mash", "spam"}


def _crop_rgb(frame_bgr, x: int, y: int, w: int, h: int):
    crop = frame_bgr[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    if crop.ndim == 2:
        rgb = np.repeat(crop[:, :, None], 3, axis=2)
    else:
        rgb = crop[:, :, 2::-1]  # BGR(A) → RGB
    return np.ascontiguousarray(rgb, dtype=np.uint8).copy()


def find_icon_blob(frame_bgr, x1: float, x2: float, yc: float, h: float,
                   prefer: str = "center"):
    """
    [x1, x2) yatay aralığında, satır yüksekliğine uygun, iki yanı boş, parlak ve
    kompakt bir ikon lekesi (daire/rozet) arar. Bulamazsa None.
    prefer: "right" (kelimenin solundaki ikon), "left" veya "center".
    Döner: (x, y, w, h) tam kare koordinatı.
    """
    fh, fw = frame_bgr.shape[:2]
    h = float(h)
    if h < 4:
        return None
    y1 = max(0, int(round(yc - h * 0.75)))
    y2 = min(fh, int(round(yc + h * 0.75)))
    x1 = max(0, int(round(x1)))
    x2 = min(fw, int(round(x2)))
    if x2 - x1 < int(h * 0.55) + 2 or y2 - y1 < 4:
        return None
    reg = _to_bgr(frame_bgr[y1:y2, x1:x2])
    if reg is None:
        return None
    gray = reg.astype(np.int16).sum(axis=2) // 3
    bg = int(np.median(gray))
    ink = np.abs(gray - bg) > 45
    rows = ink.shape[0]
    col = ink.sum(axis=0) >= max(2, int(rows * 0.12))

    # Mürekkepli sütun dizileri (kesintisiz; ikon ile bitişik harf arası 1 px de ayırır)
    runs, n, j = [], len(col), 0
    while j < n:
        if not col[j]:
            j += 1
            continue
        k = j
        while k + 1 < n and col[k + 1]:
            k += 1
        runs.append((j, k))
        j = k + 1

    # Parçalı ikonlar (D-pad artısı: kollar arası boşluklu) için yakın dizileri birleştiren
    # ek adaylar. Ham diziler önce denenir; birleşik aday yalnızca ham adayla çakışmıyorsa eklenir.
    merge_gap = max(2, int(round(h * 0.15)))
    merged_runs = []
    for a, b in runs:
        if merged_runs and a - merged_runs[-1][1] - 1 <= merge_gap:
            merged_runs[-1] = (merged_runs[-1][0], b, merged_runs[-1][2] + 1)
        else:
            merged_runs.append((a, b, 1))
    extra = [(a, b) for a, b, cnt in merged_runs if cnt >= 2]

    cands = []
    for a, b in runs + extra:
        if any(not (b < ca or a > cb) for ca, cb, _r0, _r1 in cands):
            continue
        rw = b - a + 1
        if rw < h * 0.55 or rw > h * 1.7:
            continue
        if a == 0 or b >= n - 1:      # iki yanı boş olmalı (komşu metin/HUD değil)
            continue
        sub = ink[:, a:b + 1]
        is_frag = (a, b) in extra
        row_ink = sub.any(axis=1)
        if is_frag:
            # Parçalı ikonda satırlar arasında da küçük boşluklar olur → boşlukları doldur
            filled = row_ink.copy()
            idx = np.nonzero(row_ink)[0]
            for p0, p1 in zip(idx[:-1], idx[1:]):
                if 1 < p1 - p0 <= merge_gap + 1:
                    filled[p0:p1] = True
            row_ink = filled
        rr = _row_run(row_ink, yc - y1)
        if rr is None:
            continue
        rh = int(rr[1] - rr[0] + 1)
        # İkon rozeti satır boyu kadardır; küçük harf/rakam ('a', 'o') x-yüksekliğinde kalır
        if rh < h * 0.8 or rh > h * 1.4:
            continue
        if float(sub[rr[0]:rr[1] + 1].mean()) < (0.12 if is_frag else 0.18):
            continue
        if int(gray[rr[0]:rr[1] + 1, a:b + 1].max()) < 160:   # GTA ikonları beyaz/parlak
            continue
        cands.append((a, b, int(rr[0]), int(rr[1])))
    if not cands:
        return None
    if prefer == "right":
        a, b, r0, r1 = cands[-1]
    elif prefer == "left":
        a, b, r0, r1 = cands[0]
    else:
        mid = n * 0.5
        a, b, r0, r1 = min(cands, key=lambda c: abs((c[0] + c[1]) * 0.5 - mid))
    ix1 = max(0, x1 + a - 1)
    iy1 = max(0, y1 + r0 - 1)
    ix2 = min(fw, x1 + b + 2)
    iy2 = min(fh, y1 + r1 + 2)
    return (ix1, iy1, ix2 - ix1, iy2 - iy1)


def _norm(t: str) -> str:
    return "".join(ch for ch in str(t).lower() if ch.isalnum())


def _align_words(text_tokens: list, words: list) -> list:
    """OCR kelime indeksi → temiz metin token indeksi (eşleşmeyen: None)."""
    res = [None] * len(words)
    p = 0
    for j, w in enumerate(words):
        nw = _norm(w.get("text", ""))
        if not nw:
            continue
        for q in range(p, min(len(text_tokens), p + 4)):
            nt = _norm(text_tokens[q])
            if not nt:
                continue
            if nt == nw or (min(len(nt), len(nw)) >= 3 and (nt.startswith(nw) or nw.startswith(nt))):
                res[j] = q
                p = q + 1
                break
    return res


def _iou(b1: tuple, b2: tuple) -> float:
    ix = min(b1[0] + b1[2], b2[0] + b2[2]) - max(b1[0], b2[0])
    iy = min(b1[1] + b1[3], b2[1] + b2[3]) - max(b1[1], b2[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    return inter / float(max(1, b1[2] * b1[3] + b2[2] * b2[3] - inter))


def attach_button_icons(box: dict, frame_bgr, strict: bool = False) -> None:
    """
    box["words"] içindeki tuş ikonlarının orijinal piksellerini box["icons"] listesine
    (okuma sırasıyla) yazar. Asla hata fırlatmaz; ikon yoksa anahtar eklenmez.

    Üç kaynak:
      1. OCR'ın okuduğu tuş kelimeleri (R2, (L1), [X]).
      2. OCR'ın okuyamadığı ikonlar: satır başındaki kelimenin solunda veya iki kelime
         arasındaki geniş boşlukta duran parlak kompakt leke
         (GTA 6: "(X) GET UP", "Use (R) to select").
      3. Metinde etiketsiz kalan tek harfli tuş kelimesi yalnızca piksel lekesiyle
         doğrulanırsa kabul edilir.
    2 ve 3'te metinde karşılık gelen etiket yoksa box["text"] içine "[TOKEN]" eklenir
    (LLM etiketi korur, yama katmanı ikonu satır içi çizer).

    strict=True (altyazı bandı): diyalogda ikon nadirdir; yalnızca OCR'ın okuduğu tuşlar,
    fiil/'to' komşuluklu boşluk ikonları ve kısa satır başı ikonları kabul edilir.
    """
    try:
        words = box.get("words") or []
        if not words or frame_bgr is None or not hasattr(frame_bgr, "shape") or frame_bgr.size == 0:
            return
        fh, fw = frame_bgr.shape[:2]
        text = str(box.get("text", "") or "")
        tags = _box_tags(text)
        line_count = max(1, int(box.get("line_count", 1) or 1))
        bbox = box.get("bbox") or (0, 0, 0, 0)
        line_h = float(bbox[3]) / line_count if bbox[3] else None

        text_tokens = text.split()
        align = _align_words(text_tokens, words)
        # (sıra anahtarı, ikon sözlüğü, metin düzenlemesi: (token_idx, "before"/"replace") veya None)
        found = []

        def _add(order, tok, ib, edit):
            x, y, w, h = [int(v) for v in ib]
            x, y = max(0, x), max(0, y)
            w, h = min(fw - x, w), min(fh - y, h)
            if w <= 1 or h <= 1:
                return
            for _o, ic, _e in found:
                if _iou(ic["bbox"], (x, y, w, h)) > 0.3:
                    return
            rgb = _crop_rgb(frame_bgr, x, y, w, h)
            if rgb is None:
                return
            found.append((order, {"token": tok, "bbox": (x, y, int(rgb.shape[1]), int(rgb.shape[0])),
                                  "rgb": rgb}, edit))

        def _text_idx_from(j):
            """j. kelimeden itibaren metinde eşleşen ilk token indeksi."""
            for k in range(j, len(words)):
                if align[k] is not None:
                    return align[k]
            return None

        # 1 + 3) OCR'ın okuduğu tuş kelimeleri
        for j, word in enumerate(words):
            for part_text, wb in _split_word(word):
                tok = button_token(part_text)
                if not tok:
                    continue
                wx, wy, ww, wh = wb
                if ww <= 0 or wh <= 0 or wx >= fw or wy >= fh:
                    continue
                if tok in tags:
                    _add(j, tok, refine_icon_bbox(frame_bgr, wb, line_h), None)
                    continue
                is_code = bool(_CODE_RE.match(tok)) or part_text.strip()[:1] in "([{<"
                if tags or not is_code:
                    # Etiketlenmemiş tek harf ('a car' / düşürülmüş 'R') → ancak ikon lekesi varsa
                    lh = max(float(wh), min(float(line_h or wh), wh * 1.6))
                    ib = find_icon_blob(frame_bgr, wx - lh * 1.2, wx + ww + lh * 1.2,
                                        wy + wh * 0.5, lh, prefer="center")
                    if ib is None:
                        continue
                else:
                    ib = refine_icon_bbox(frame_bgr, wb, line_h)
                # Metinde bu kelime hâlâ duruyorsa etiketle değiştir, yoksa sonraki kelimeden önce ekle
                if align[j] is not None:
                    edit = (align[j], "replace")
                else:
                    nxt = _text_idx_from(j + 1)
                    edit = (nxt, "before") if nxt is not None else (len(text_tokens), "before")
                _add(j, tok, ib, edit)

        # 2) OCR'ın göremediği ikonlar: satır başı solu + geniş kelime arası boşluklar
        # Satır başı kelime indeksi → o satırdaki kelime sayısı
        line_len, start, last = {}, 0, None
        for j, word in enumerate(words):
            wb = word.get("bbox") or (0, 0, 0, 0)
            if last is not None and (wb[0] < last[0] or abs((last[1] + last[3] * 0.5)
                                                            - (wb[1] + wb[3] * 0.5)) > wb[3] * 0.6):
                start = j
            line_len[start] = line_len.get(start, 0) + 1
            last = wb
        prev = None
        for j, word in enumerate(words):
            wb = word.get("bbox")
            if not wb or len(wb) != 4:
                prev = None
                continue
            wx, wy, ww, wh = [int(v) for v in wb]
            if wh < 6:
                prev = word
                continue
            yc = wy + wh * 0.5
            new_line = (prev is None or wx < prev["bbox"][0]
                        or abs((prev["bbox"][1] + prev["bbox"][3] * 0.5) - yc) > wh * 0.6)
            ib = None
            if button_token(word.get("text", "")) is None:
                if new_line:
                    # Satır başı ikonu ('(X) GET UP', '[R2] Accelerate'): yalnızca kısa ipucu
                    # satırlarında (≤ 4 kelime) — uzun altyazılarda tetiklenmez
                    if line_len.get(j, 99) <= (4 if strict else 8):
                        ib = find_icon_blob(frame_bgr, wx - wh * 2.0, wx + 1, yc, wh, prefer="right")
                else:
                    px, _py, pw, _ph = [int(v) for v in prev["bbox"]]
                    prev_low = _norm(prev.get("text", ""))
                    cur_low = _norm(word.get("text", ""))
                    gap = wx - (px + pw)
                    if (button_token(prev.get("text", "")) is None
                            and gap >= wh * 0.6
                            and (prev_low in _PRESS_VERBS or cur_low == "to"
                                 or (not strict and gap >= wh * 0.9))):
                        ib = find_icon_blob(frame_bgr, px + pw, wx + 1, yc, wh, prefer="center")
            if ib is not None and align[j] is not None:
                # Metinde ikon yerinde zaten etiket varsa ('[R] to') yeniden ekleme
                before = text_tokens[align[j] - 1] if align[j] > 0 else ""
                if not _TAG_RE.fullmatch(before.strip(".,:;!?")):
                    _add(j - 0.5, GLYPH_TOKEN, ib, (align[j], "before"))
            prev = word

        # 4) Kelimenin İÇİNE gömülmüş ikon: OCR ikonu yok sayıp iki kelimeyi yapıştırır
        #    ('Press [D-pad] to' → 'Pressto'). Satırın harf başına genişliğine göre beklenenden
        #    belirgin geniş kelimelerin içinde ikon lekesi aranır.
        #    + satır sonu ikonu ('Aim [L2]') kısa satırlarda son kelimenin sağında aranır.
        lines, cur = [], []
        for j, word in enumerate(words):
            wb = word.get("bbox")
            if not wb or len(wb) != 4:
                continue
            if cur:
                pb = words[cur[-1]]["bbox"]
                if wb[0] < pb[0] or abs((pb[1] + pb[3] * 0.5) - (wb[1] + wb[3] * 0.5)) > wb[3] * 0.6:
                    lines.append(cur)
                    cur = []
            cur.append(j)
        if cur:
            lines.append(cur)
        for ln in lines:
            ratios = []
            for j in ln:
                t = _norm(words[j].get("text", ""))
                if len(t) >= 2:
                    ratios.append(words[j]["bbox"][2] / float(len(t)))
            pxc = float(np.median(ratios)) if len(ratios) >= 2 else None
            for j in ln:
                word = words[j]
                t = _norm(word.get("text", ""))
                wx, wy, ww, wh = [int(v) for v in word["bbox"]]
                if not pxc or len(t) < 2 or wh < 6 or button_token(word.get("text", "")):
                    continue
                if ww < len(t) * pxc + wh * 0.6:
                    continue
                ib = find_icon_blob(frame_bgr, wx + 1, wx + ww - 1, wy + wh * 0.5, wh, prefer="center")
                if ib is None:
                    continue
                # İkondan önceki karakter sayısı → temiz metindeki en yakın kelime sınırı
                n_before = max(0.0, (ib[0] - wx) / pxc)
                # Yapışık kelimede ikon yalnızca tuş fiilinin hemen ardındaysa ('Pressto' →
                # 'Press [ikon] to') veya 'to'dan hemen önceyse kabul edilir. Aksi hâlde
                # boşluksuz okunan diyalogdaki harfler ('won't.So,don't' → 'So') ikon sanılır.
                nb = int(round(n_before))
                verb_ok = any(t.startswith(v) and abs(len(v) - n_before) <= 2.0 for v in _PRESS_VERBS)
                to_ok = any(t[k:].startswith("to") for k in range(max(0, nb - 1), min(len(t), nb + 3)))
                if not (verb_ok or to_ok):
                    continue
                ti = align[j]
                if ti is None:
                    ti = _text_idx_from(j + 1)
                    edit = (ti if ti is not None else len(text_tokens), "before")
                else:
                    acc, k = 0.0, ti
                    while k < len(text_tokens) and acc + len(_norm(text_tokens[k])) * 0.5 < n_before:
                        acc += len(_norm(text_tokens[k]))
                        k += 1
                    edit = (k, "before")
                if edit[0] > 0 and edit[0] - 1 < len(text_tokens) and                         _TAG_RE.fullmatch(text_tokens[edit[0] - 1].strip(".,:;!?")):
                    continue
                _add(j + 0.5, GLYPH_TOKEN, ib, edit)
            # Satır sonu ikonu
            last_j = ln[-1]
            lw = words[last_j]
            if not strict and len(ln) <= 8 and not button_token(lw.get("text", "")):
                wx, wy, ww, wh = [int(v) for v in lw["bbox"]]
                if wh >= 6:
                    ib = find_icon_blob(frame_bgr, wx + ww - 1, wx + ww + wh * 2.0,
                                        wy + wh * 0.5, wh, prefer="left")
                    if ib is not None:
                        nxt = align[last_j]
                        pos = (nxt + 1) if nxt is not None else len(text_tokens)
                        _add(last_j + 0.6, GLYPH_TOKEN, ib, (pos, "before"))

        if not found:
            return
        found.sort(key=lambda f: f[0])
        n_btn = 0
        for _o, ic, _e in found:
            if ic["token"] == GLYPH_TOKEN:
                n_btn += 1
                if n_btn > 1:
                    ic["token"] = f"{GLYPH_TOKEN}{n_btn}"

        # Metne eksik etiketleri ekle (sondan başa, indeksler kaymasın)
        edits = sorted((f for f in found if f[2] is not None),
                       key=lambda f: (f[2][0], f[0]), reverse=True)
        if edits:
            toks = list(text_tokens)
            for _o, ic, (ti, mode) in edits:
                tag = f"[{ic['token']}]"
                if mode == "replace" and 0 <= ti < len(toks):
                    m = re.match(r"^(.*?)([.,:;!?]*)$", toks[ti])
                    toks[ti] = tag + (m.group(2) if m else "")
                else:
                    toks.insert(max(0, min(len(toks), ti)), tag)
            box["text"] = " ".join(toks)

        box["icons"] = [ic for _o, ic, _e in found]

        # Kutu sınırı dışında kalan ikonlar (örn. '(X) GET UP' satır başı dairesi) yamaya dahil
        # edilir; aksi hâlde orijinal ikon yamanın yanında görünür, satır içi kopyası da
        # çevirinin içinde çizilir (çift ikon).
        bx, by, bw, bh = [int(v) for v in bbox]
        if bw > 0 and bh > 0:
            x1, y1, x2, y2 = bx, by, bx + bw, by + bh
            for ic in box["icons"]:
                ix, iy, iw, ih = ic["bbox"]
                x1, y1 = min(x1, ix), min(y1, iy)
                x2, y2 = max(x2, ix + iw), max(y2, iy + ih)
            if (x1, y1, x2, y2) != (bx, by, bx + bw, by + bh):
                box["bbox"] = (x1, y1, x2 - x1, y2 - y1)
    except Exception:
        return
