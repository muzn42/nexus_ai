"""
NEXUS AI v3 — Oyun Metni Filtresi, Bölge Sınıflandırıcı ve Bukalemun Stil Analizcisi

Görevi:
  1. Mini-harita yön harfleri, tek harfli tuş ikonları ve salt sayı/para gibi
     oyun gürültülerini çevirmeden elemek.
  2. Konuşmacı ön eklerini ('Lucia: ...') ayırmak.
  3. Kutunun otomatik altyazı bölgesinde (veya manuel ROI içinde) olup olmadığını bulmak.
  4. Orijinal oyun karesinden kutunun arka plan (bukalemun) rengini, buzlu cam
     dokusunu, orijinal yazı rengini ve hizalamasını çıkarmak.
"""
import re
import numpy as np

# Mini-harita pusula yönleri ve sık rastlanan tekil oyun tuş ikonları
_NOISE_EXACT = {
    "n", "s", "e", "w", "ne", "nw", "se", "sw",
    "f", "r", "q", "g", "z", "x", "c", "v", "b", "t", "y", "u", "i", "o", "p",
    "m", "k", "l", "j", "h", "a", "d",
    "esc", "tab", "alt", "ctrl", "shift", "space", "enter", "del", "ins",
    "lmb", "rmb", "mmb", "l1", "r1", "l2", "r2", "l3", "r3",
    "lb", "rb", "lt", "rt", "ls", "rs", "wasd", "fps", "ms", "hz", "xp",
}

# Salt sayı / para / saat / mermi / FPS / yüzde / hız desenleri
_NOISE_PATTERNS = [
    re.compile(r"^[\$\€\£\₺\+\-\#\s]*\d[\d,\.\s:/%\-]*$"),
    re.compile(r"^\d+\s*/\s*\d+$"),
    re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\s*(am|pm))?$", re.IGNORECASE),
    re.compile(r"^[\+\-]?\d+([.,]\d+)?\s*(%|fps|ms|xp|hp|ap|km/h|mph|m|km|ft|yd|lbs|kg)\b\.?$", re.IGNORECASE),
    re.compile(r"^[x×]\s*\d+$", re.IGNORECASE),
    re.compile(r"^[\[\(]?\s*(lmb|rmb|mmb|l1|r1|l2|r2|l3|r3|lb|rb|lt|rt|esc|tab|ctrl|alt|shift|space)\s*[\]\)]?$", re.IGNORECASE),
]

_TWO_LETTERS_RE = re.compile(r"[A-Za-zÇĞIİÖŞÜçğıöşü]{2,}")
_TURKISH_CHARS_RE = re.compile(r"[ğüşıöçĞÜŞİÖÇ]")
_KNOWN_WATERMARKS = {
    "yemeksepeti", "shirrako", "shirraks", "gtaseries",
    "mkiceandfire", "theradbrad", "rockstargames",
    "vi", "iv", "ii", "iii",
}
_LEADING_GLYPH_RE = re.compile(r"^[①-⑳ⓐ-ⓩ●○◆◇■□▲△▼▽★☆•·\?\!@#%&]+\s*")
_FUSED_BUTTON_END_RE = re.compile(
    # HOLD/PRESS/USE burada YOK: 'Use R' / 'PRESS X' satır içi ikon olarak '[R]' / '[X]' etiketlenir
    r"^(SELECT|BACK|RESET|EQUIP|DROP|SKIP|CANCEL|CONFIRM|EXIT|"
    r"OPEN|CLOSE|MAP|JUMP|CROUCH|PHOTO STUDIO|PHOTO MODE)"
    # 'SELECT X', 'BACK O', 'SELECTX', 'SELECT [X]', 'BACK (O)', 'MAP R3' -> yalın etiket
    r"(?:\s+[\[\(]?\s*(?:[XOYABERF123]|[RL][123])\s*[\]\)]?|\s*[XOY])$",
    re.IGNORECASE,
)
_INLINE_VERB_JOIN_RE = re.compile(
    r"\b(Hold|Press|Tap|Use|Push)(while|to|for|and|the|when)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Paylaşılan Tuş (Buton) Etiketi API'si
# Diğer modüller (ikon koruma / satır içi ikon çizimi) bu isimleri doğrudan içe aktarır;
# isimleri değiştirmeyin: BUTTON_TOKENS, button_token(), tag_button_tokens().
# ---------------------------------------------------------------------------
BUTTON_TOKENS = frozenset({
    # PlayStation
    "R1", "R2", "R3", "L1", "L2", "L3", "R", "L",
    "X", "O", "TRIANGLE", "SQUARE", "CIRCLE", "CROSS",
    "OPTIONS", "TOUCHPAD", "SHARE", "CREATE", "PS", "DPAD",
    "LS", "RS",
    # Xbox
    "LB", "RB", "LT", "RT", "A", "B", "Y", "MENU", "VIEW",
})

# OCR/glif varyantları -> kanonik etiket
_BUTTON_ALIASES = {
    "D-PAD": "DPAD", "D_PAD": "DPAD", "DPAD": "DPAD",
    "TOUCH-PAD": "TOUCHPAD", "TOUCH PAD": "TOUCHPAD",
    "△": "TRIANGLE", "▲": "TRIANGLE",
    "□": "SQUARE", "■": "SQUARE",
    "○": "O", "◯": "O",
    "×": "X", "✕": "X", "✖": "X", "⊗": "X", "Ⓧ": "X", "ⓧ": "X",
    # Daire içindeki R/L (sağ/sol çubuk) OCR'da sıklıkla '®' okunur ('Use ® to select')
    "®": "R", "Ⓡ": "R", "ⓡ": "R", "Ⓛ": "L", "ⓛ": "L",
}
# Harf/rakam olmayan glif takma adları kesin ikondur; bağlam aramadan etiketlenir
_GLYPH_ICON_ALIASES = frozenset(k for k in _BUTTON_ALIASES if not any(c.isalnum() for c in k))

# OCR'ın rozeti metne yapıştırması: 'R2Accelerate' -> '[R2] Accelerate'
_GLUED_LEAD_BTN_RE = re.compile(r"^[\[\(]?([RL][123])[\]\)]?(?=[A-Z][a-z]{2,})")
# Rozetin rakam sanılması: '12Brake and reverse' (L2) -> 'Brake and reverse'
_GLUED_LEAD_MISREAD_RE = re.compile(r"^[1Il|][123](?=[A-Z][a-z]{2,})")

# İngilizce kelime OLMAYAN kod-benzeri tuşlar: tek başına yazıldıklarında bile etiketlenir.
_CODE_TOKENS = frozenset({
    "R1", "R2", "R3", "L1", "L2", "L3", "LB", "RB", "LT", "RT", "LS", "RS", "DPAD",
})
# Bağlam gerektiren tuşlar (tek harfler ve 'Options', 'Share', 'Cross' gibi gerçek kelimeler)
_PRESS_VERBS = frozenset({"press", "hold", "tap", "use", "push", "release", "mash", "click"})
_BTN_CONNECTORS = frozenset({"to", "while", "for", "and", "or", "button", "then"})
_BTN_STRIP_CHARS = "[](){}<>.,!?:;\"' "
_WORD_PARTS_RE = re.compile(r"^([\[\(\{<]*)(.*?)([\]\)\}>]*)([.,!?:;\"']*)$")


def button_token(word: str):
    """
    Tek bir OCR kelimesini kanonik tuş adına çevirir ('(R2)' -> 'R2', '[l1]' -> 'L1',
    'R2.' -> 'R2', 'D-PAD' -> 'DPAD', '△' -> 'TRIANGLE'); tuş değilse None döner.

    NOT: Bağlamdan bağımsızdır; tek harfler ('A', 'B', 'X', 'O', 'Y', 'R', 'L') ve
    'Options'/'Share'/'Create'/'Cross' gibi gerçek İngilizce kelimeler de token
    olarak döner. İngilizce 'a' artikeli mi yoksa tuş mu olduğuna ÇAĞIRAN karar verir
    (bkz. tag_button_tokens bağlam kuralı).
    """
    if not word:
        return None
    core = str(word).strip(_BTN_STRIP_CHARS)
    if not core:
        return None
    up = core.upper()
    if up in _BUTTON_ALIASES:
        return _BUTTON_ALIASES[up]
    if up in BUTTON_TOKENS:
        return up
    return None


def _is_wrapped(lead: str, close: str) -> bool:
    return bool(lead) and bool(close)


def _is_icon_word(word: str) -> bool:
    """Kelime kesinlikle bir tuş ikonu mu? (köşeli/parantezli token veya kod-benzeri token)"""
    tok = button_token(word)
    if not tok:
        return False
    m = _WORD_PARTS_RE.match(word)
    if m and _is_wrapped(m.group(1), m.group(3)):
        return True
    if m and m.group(2).upper() in _GLYPH_ICON_ALIASES:
        return True
    return tok in _CODE_TOKENS


def tag_button_tokens(text: str) -> str:
    """
    Cümle içindeki tuş adlarını köşeli parantezle etiketler (LLM bunları korur):
      'Press R2 to fire'   -> 'Press [R2] to fire'
      'Hold (L2) to aim'   -> 'Hold [L2] to aim'
      'Use R to select'    -> 'Use [R] to select'
      'Press L1/R1'        -> 'Press [L1]/[R1]'
    Kurallar:
      - Zaten parantezli/köşeli tuşlar ('(L2)', '[X]') her zaman '[L2]' biçimine getirilir.
      - Kod-benzeri tuşlar (R1..R3, L1..L3, LB, RB, LT, RT, LS, RS, DPAD) tek başına
        kelime olduklarında her zaman etiketlenir.
      - Tek harfler (X, O, A, B, Y, R, L) yalnızca BÜYÜK harfle yazılmışsa, önünde
        Press/Hold/Tap/Use/Push gibi bir fiil varsa VE ardından to/while/for/and/or
        gelirse ya da cümle bitiyorsa etiketlenir ('a car' / 'A car' etiketlenmez).
      - Kelime-tuşlar (OPTIONS, TOUCHPAD, TRIANGLE, SQUARE, CIRCLE, CROSS, SHARE,
        CREATE, PS, MENU, VIEW) önünde fiil varsa ya da BÜYÜK harfle yazılıp ardından
        bağlaç geliyorsa etiketlenir; tek başına menü öğesi 'Options' etiketlenmez.
      - 'Press X or O to ...' gibi zincirlerde önceki etiketten sonra gelen
        'or/and/,' bağlacı da fiil yerine geçer.
    """
    words = (text or "").split()
    if not words:
        return ""
    out = []
    prev_ok_ctx = False  # önceki kelime fiil mi / etiket+bağlaç zinciri mi
    last_tagged = False
    for i, w in enumerate(words):
        m = _WORD_PARTS_RE.match(w)
        lead, core, close, punct = m.groups() if m else ("", w, "", "")
        nxt = words[i + 1].strip(_BTN_STRIP_CHARS).lower() if i + 1 < len(words) else ""
        at_end = (i + 1 >= len(words)) or bool(punct)
        low_core = core.lower()

        tagged = None
        # 'L1/R1' gibi eğik çizgili çift tuşlar
        if "/" in core and not lead and not close:
            parts = core.split("/")
            toks = [button_token(p) for p in parts]
            if len(parts) >= 2 and all(t and t in _CODE_TOKENS for t in toks):
                tagged = "/".join(f"[{t}]" for t in toks) + punct

        if tagged is None:
            tok = button_token(core) if core else None
            if tok:
                wrapped = _is_wrapped(lead, close) or core.upper() in _GLYPH_ICON_ALIASES
                ok = False
                if wrapped or tok in _CODE_TOKENS:
                    ok = True
                elif len(core) == 1:
                    ok = core.isupper() and prev_ok_ctx and (nxt in _BTN_CONNECTORS or at_end)
                else:
                    ok = prev_ok_ctx or (core.isupper() and nxt in _BTN_CONNECTORS and i > 0)
                if ok:
                    tagged = f"[{tok}]" + punct

        if tagged is not None:
            out.append(tagged)
            last_tagged = True
            prev_ok_ctx = False
            continue

        out.append(w)
        if low_core in _PRESS_VERBS:
            prev_ok_ctx = True
        elif last_tagged and (low_core in ("or", "and", "then") or w in (",", "/", "+")):
            prev_ok_ctx = True
        else:
            prev_ok_ctx = False
        last_tagged = False
        if punct:
            prev_ok_ctx = prev_ok_ctx and punct == ","
    return " ".join(out)
_SPEAKER_RE = re.compile(r"^([A-Za-zÇĞIİÖŞÜçğıöşü0-9][A-Za-zÇĞIİÖŞÜçğıöşü0-9\s\.\-']{0,24}):\s+(.+)$")
_WATERMARK_RE = re.compile(
    r"^(?:https?://\S+|www\.\S+|@\S+|[A-Za-z0-9\-_]{2,}\.(?:com|net|org|tv|gg|io|co))$",
    re.IGNORECASE,
)


def clean_ocr_game_text(text: str) -> str:
    """OCR'ın tuş/menü ikonlarıyla birleştirdiği fazlalıkları normalleştirir."""
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return ""
    cleaned = _LEADING_GLYPH_RE.sub("", cleaned).strip()  # '@GET UP' (X dairesi) -> 'GET UP'
    cleaned = _GLUED_LEAD_BTN_RE.sub(r"\1 ", cleaned)
    cleaned = _GLUED_LEAD_MISREAD_RE.sub("", cleaned).strip()
    cleaned = _FUSED_BUTTON_END_RE.sub(r"\1", cleaned).strip()
    cleaned = _INLINE_VERB_JOIN_RE.sub(r"\1 \2", cleaned)
    # Satır içi tuş ikonlarını '[R2]' biçiminde etiketle (LLM korur, overlay ikon çizer)
    cleaned = tag_button_tokens(cleaned)
    return " ".join(cleaned.split())


def is_translatable_game_text(text: str, score: float = 1.0, bbox: tuple = None) -> bool:
    """
    OCR'dan gelen kutunun gerçekten çevrilmesi gereken bir oyun metni olup
    olmadığını denetler. Mini-harita yönleri, tuş ikonları ve salt sayıları eler.
    """
    if score is not None and float(score) < 0.60:
        return False

    cleaned = clean_ocr_game_text(text)
    if not cleaned or len(cleaned) < 2:
        return False

    # Halihazırda Türkçe karakter içeren yayın/overlay metinlerini tekrar çevirme
    if _TURKISH_CHARS_RE.search(cleaned):
        return False

    # Çok küçük/bozuk kutu gürültüsü
    if bbox is not None and len(bbox) == 4:
        _, _, bw, bh = bbox
        if bw < 16 or bh < 11:
            return False

    low = cleaned.lower().strip("[](){}<>.,!?-_:;\"' ")
    if not low or low in _NOISE_EXACT:
        return False

    # Yalnızca tuş ikonlarından oluşan kutular ('R2', '[R2]', '(X)', '[L1] [R1]', '[L1]/[R1]')
    icon_words = cleaned.replace("/", " ").split()
    if icon_words and all(_is_icon_word(w) for w in icon_words):
        return False

    compact = re.sub(r"[^a-z0-9]", "", low)
    if compact in _KNOWN_WATERMARKS:
        return False

    if len(cleaned) <= 2 and (score is not None and float(score) < 0.85):
        return False
    if re.fullmatch(r"[a-z]{1,4}\d+", low) and (score is not None and float(score) < 0.90):
        return False

    # Tekil parantezli harf ikonları: [E], (F) vb.
    if re.fullmatch(r"[\[\(\{]\s*[A-Za-z0-9]{1,3}\s*[\]\)\}]", cleaned):
        return False

    # Video kanal filigranları / URL'ler (GTASERIES.COM, www..., @...)
    if _WATERMARK_RE.match(cleaned):
        return False

    for pat in _NOISE_PATTERNS:
        if pat.match(cleaned):
            return False

    # En az 2 ardışık harften oluşan anlamlı bir kelime içermeli
    if not _TWO_LETTERS_RE.search(cleaned):
        return False

    return True


def split_speaker_prefix(text: str) -> tuple[str, str]:
    """
    'Lucia: What are we gonna do?' -> ('Lucia', 'What are we gonna do?')
    Konuşmacı öneki yoksa ('', temiz_metin) döner.
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "", ""

    m = _SPEAKER_RE.match(cleaned)
    if not m:
        return "", cleaned

    speaker = m.group(1).strip()
    body = m.group(2).strip()

    # URL veya saat gibi sahte ':' eşleşmelerini ele
    if speaker.lower() in ("http", "https", "ftp") or speaker.isdigit():
        return "", cleaned
    if len(speaker.split()) > 3:
        return "", cleaned

    return speaker, body


def is_in_auto_subtitle_zone(bbox: tuple, frame_w: int, frame_h: int,
                             custom_roi: tuple = None) -> bool:
    """
    Kutunun altyazı bölgesinde olup olmadığını kontrol eder.
    Manuel ROI varsa onun içine bakar; yoksa alt-orta otomatik altyazı bandını kullanır.
    """
    if not bbox or len(bbox) != 4 or frame_w <= 0 or frame_h <= 0:
        return False

    bx, by, bw, bh = bbox
    cx = bx + bw * 0.5
    cy = by + bh * 0.5

    if custom_roi and len(custom_roi) == 4:
        rx, ry, rw, rh = custom_roi
        if rw > 0 and rh > 0:
            pad_x = max(12, rw * 0.04)
            pad_y = max(10, rh * 0.12)
            return (rx - pad_x <= cx <= rx + rw + pad_x and
                    ry - pad_y <= cy <= ry + rh + pad_y)

    # Otomatik altyazı bandı: yatay %22-%78 (köşe ve sağ alt buton çubuğunu dışlar), dikey %72-%98
    if cy > frame_h * 0.91:
        return (frame_w * 0.28 <= cx <= frame_w * 0.72 and cy <= frame_h * 0.98)
    return (frame_w * 0.22 <= cx <= frame_w * 0.78 and
            frame_h * 0.72 <= cy <= frame_h * 0.98)


def auto_subtitle_roi(frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """Manuel ROI yokken kullanılan varsayılan alt-orta altyazı bandı."""
    x = int(frame_w * 0.16)
    y = int(frame_h * 0.72)
    w = max(1, int(frame_w * 0.68))
    h = max(1, int(frame_h * 0.265))
    return (x, y, w, h)


def has_subtitle_text_changed(prev_mask, cur_crop) -> tuple[bool, bool, object]:
    """
    Altyazı şeridindeki keskin/parlak metin piksellerini 0.3 ms'de analiz eder.
    Arka plandaki hareketli ağaç/çimen/at piksellerini görmezden gelerek yalnız
    yazı değiştiğinde True döner; şeritte hiç metin pikseli yoksa has_any_text=False
    döner ki mevcut altyazı OCR beklemeden silinsin.
    """
    if cur_crop is None or not hasattr(cur_crop, "shape") or cur_crop.size == 0:
        return False, False, prev_mask
    try:
        import cv2
        small = cv2.resize(cur_crop, (160, 44), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (9, 9), 0)
        hp = cv2.subtract(gray, blur)
        # Parlak keskin harfler veya karanlık altyazı bandı üstü metin pikselleri
        mask = ((hp > 22) | ((gray > 185) & (hp > 12))).astype(np.uint8) * 255
        has_any_text = int(np.count_nonzero(mask)) >= 8

        if prev_mask is None or prev_mask.shape != mask.shape:
            return has_any_text, has_any_text, mask

        diff_px = np.count_nonzero(cv2.absdiff(prev_mask, mask))
        changed = (diff_px / float(mask.size)) > 0.012
        return changed, has_any_text, mask
    except Exception:
        return True, True, None


def _contrast_color(rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Yazı rengi ile arka plan arasında yeterli okunabilirlik kontrastı sağlar."""
    r, g, b = rgb
    br, bg, bb = bg_rgb
    lum_fg = 0.299 * r + 0.587 * g + 0.114 * b
    lum_bg = 0.299 * br + 0.587 * bg + 0.114 * bb
    if abs(lum_fg - lum_bg) >= 75:
        return (r, g, b)
    return (255, 255, 255) if lum_bg < 140 else (20, 20, 24)


def sample_box_style(frame_bgr, bbox: tuple, frame_w: int = 0) -> dict:
    """
    Orijinal oyun karesinden kutu bölgesini örnekler:
      - blurred_rgb: alttaki İngilizce yazıyı silen buzlu cam dokusu (RGB uint8)
      - bg_color: kutu kenarlarından örneklenen bukalemun arka plan rengi (r, g, b)
      - fg_color: orijinal metnin algılanan rengi (r, g, b)
      - align: 'center' | 'left'
    """
    default_style = {
        "bg_color": (16, 20, 26),
        "fg_color": (255, 255, 255),
        "blurred_rgb": None,
        "align": "left",
    }
    if frame_bgr is None or not hasattr(frame_bgr, "shape") or frame_bgr.size == 0:
        return default_style
    if not bbox or len(bbox) != 4:
        return default_style

    fh, fw = frame_bgr.shape[:2]
    if not frame_w:
        frame_w = fw
    x, y, w, h = [int(v) for v in bbox]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(fw, x + max(1, w))
    y2 = min(fh, y + max(1, h))
    if x2 <= x1 or y2 <= y1:
        return default_style

    crop = frame_bgr[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]

    # 1. Buzlu Cam (Hızlı Blur: küçült + GaussianBlur + büyüt veya doğrudan GaussianBlur)
    blurred_rgb = None
    try:
        import cv2
        # Küçült-bulanıklaştır-büyüt yöntemi büyük kutularda dahi <0.3 ms sürer ve harfleri tamamen eritir
        small_w = max(8, cw // 4)
        small_h = max(4, ch // 4)
        small = cv2.resize(crop, (small_w, small_h), interpolation=cv2.INTER_AREA)
        k = max(5, (min(small_w, small_h) // 2) | 1)
        k = min(k, 15)
        small_blur = cv2.GaussianBlur(small, (k, k), 0)
        blurred_bgr = cv2.resize(small_blur, (cw, ch), interpolation=cv2.INTER_LINEAR)
        blurred_rgb = np.ascontiguousarray(blurred_bgr[:, :, ::-1])
    except Exception:
        blurred_rgb = None

    # 2. Bukalemun Arka Plan Rengi: kutunun 2-3 px kenar çerçevesinden medyan BGR
    b_px = min(3, max(1, ch // 6), max(1, cw // 6))
    try:
        top = crop[:b_px, :].reshape(-1, 3)
        bot = crop[-b_px:, :].reshape(-1, 3)
        left = crop[:, :b_px].reshape(-1, 3)
        right = crop[:, -b_px:].reshape(-1, 3)
        border_pixels = np.concatenate([top, bot, left, right], axis=0)
        med_bg = np.median(border_pixels, axis=0)
        bg_rgb = (int(med_bg[2]), int(med_bg[1]), int(med_bg[0]))
    except Exception:
        bg_rgb = (16, 20, 26)

    # 3. Orijinal Yazı Rengi: arka plandan en farklı %15 pikselin medyanı
    fg_rgb = (255, 255, 255)
    try:
        flat_bgr = crop.reshape(-1, 3).astype(np.float32)
        bg_bgr_arr = np.array([bg_rgb[2], bg_rgb[1], bg_rgb[0]], dtype=np.float32)
        dist = np.sum(np.abs(flat_bgr - bg_bgr_arr), axis=1)
        thresh = np.percentile(dist, 85)
        fg_pixels = flat_bgr[dist >= thresh]
        if len(fg_pixels) > 0:
            med_fg = np.median(fg_pixels, axis=0)
            fr, fg, fb = int(med_fg[2]), int(med_fg[1]), int(med_fg[0])
            sat = max(fr, fg, fb) - min(fr, fg, fb)
            luma = 0.299 * fr + 0.587 * fg + 0.114 * fb
            if sat >= 38:
                # Doygun renkleri koru (GTA görev sarısı, kırmızı uyarı, yeşil vb.)
                fg_rgb = _contrast_color((fr, fg, fb), bg_rgb)
            elif luma >= 175:
                fg_rgb = (255, 255, 255)
            elif luma <= 75 and (0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]) > 140:
                fg_rgb = (22, 24, 28)
            else:
                fg_rgb = _contrast_color((fr, fg, fb), bg_rgb)
    except Exception:
        fg_rgb = (255, 255, 255)

    # 4. Hizalama: ekran ortasına yakın kutular ortalı, yan kutular sola yaslı
    box_center_x = x1 + cw * 0.5
    near_center = abs(box_center_x - frame_w * 0.5) <= frame_w * 0.12
    align = "center" if (near_center and cw >= 120) else "left"

    return {
        "bg_color": bg_rgb,
        "fg_color": fg_rgb,
        "blurred_rgb": blurred_rgb,
        "align": align,
    }


def _find_col_runs(active_mask: np.ndarray, min_gap: int) -> list[tuple[int, int]]:
    """Sütun bazlı parlak piksel gruplarını min_gap boşluklarıyla döndürür."""
    runs = []
    in_run = False
    start = 0
    for idx, val in enumerate(active_mask):
        if val and not in_run:
            in_run = True
            start = idx
        elif not val and in_run:
            in_run = False
            runs.append((start, idx))
    if in_run:
        runs.append((start, int(len(active_mask))))

    if len(runs) <= 1:
        return runs

    merged = [runs[0]]
    for s, e in runs[1:]:
        ps, pe = merged[-1]
        if (s - pe) < min_gap:
            merged[-1] = (ps, e)
        else:
            merged.append((s, e))
    return merged


def trim_button_icons_from_boxes(raw_boxes: list[dict], kept_boxes: list[dict],
                                 frame_bgr=None) -> list[dict]:
    """
    Metin kutularının sağında/solunda kalan oyun tuş ikonlarını (X, O, E, dokunmatik vb.)
    çeviri yaması altında kalmamaları için kutu sınırından kırpar.
    """
    if not kept_boxes:
        return []

    # OCR'ın elediği tekil tuş kutuları: kısa gürültüler (X, O, R) + açık tuş adları ('(R2)', 'TRIANGLE')
    icon_boxes = []
    for b in (raw_boxes or []):
        rt = (b.get("text") or "").strip()
        if is_translatable_game_text(rt, b.get("score", 1.0), b["bbox"]):
            continue
        if len(rt) <= 3 or button_token(rt):
            icon_boxes.append(b["bbox"])

    fh = fw = 0
    if frame_bgr is not None and hasattr(frame_bgr, "shape") and frame_bgr.size > 0:
        fh, fw = frame_bgr.shape[:2]

    has_cv2 = False
    if fh > 0 and fw > 0:
        try:
            import cv2
            has_cv2 = True
        except Exception:
            has_cv2 = False

    for b in kept_boxes:
        bx, by, bw, bh = [int(v) for v in b["bbox"]]
        text = clean_ocr_game_text(b.get("text") or "")
        b["text"] = text
        words = text.split()
        by_mid = by + bh * 0.5

        # A) OCR tarafından yakalanıp elenen bitişik tekil tuş kutularını (X, O, R vb.) dışla
        if len(words) <= 5:
            for ix, iy, iw, ih in icon_boxes:
                if abs((iy + ih * 0.5) - by_mid) > max(bh, ih) * 0.75:
                    continue
                if ix >= bx + bw * 0.45 and ix < bx + bw + 6 and (ix + iw) >= (bx + bw - 4):
                    new_x2 = min(bx + bw, int(ix) - 3)
                    if new_x2 - bx >= 12:
                        bw = new_x2 - bx
                elif (ix + iw) <= bx + bw * 0.55 and (ix + iw) > bx - 6 and ix <= bx + 4:
                    new_x1 = max(bx, int(ix + iw) + 3)
                    if (bx + bw) - new_x1 >= 12:
                        bw = (bx + bw) - new_x1
                        bx = new_x1

        # B) Kısa HUD etiketlerinin ucuna bitişmiş OCR-dışı ikon bloklarını (açık/koyu zemin) kırp.
        # Eşik çözünürlüğe görelidir: 720p'de 38 px, 1080p'de ~65 px, 4K'da ~130 px HUD yazısı.
        max_hud_h = max(38.0, fh * 0.06)
        if has_cv2 and bh <= max_hud_h and len(words) <= 5 and bw >= 16 and bh >= 8:
            x1 = max(0, bx)
            y1 = max(0, by)
            x2 = min(fw, bx + bw)
            y2 = min(fh, by + bh)
            if x2 - x1 >= 16 and y2 - y1 >= 6:
                crop = frame_bgr[y1:y2, x1:x2]
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                dev = np.abs(gray.astype(np.float32) - float(np.median(gray))).max(axis=0)
                thr = max(25.0, float(np.percentile(dev, 85)) * 0.38)
                active = dev > thr
                min_gap = max(3, int(round(bh * 0.24)))
                runs = _find_col_runs(active, min_gap)
                n_words = max(1, len(words))
                bare_text = re.sub(r"[\[\]\s]", "", text)
                min_text_w = len(bare_text) * bh * 0.22
                max_icon_w = 1.12 * bh
                if len(runs) >= 2:
                    r_start, r_end = runs[-1]
                    run_w = r_end - r_start
                    prev_end = runs[-2][1]
                    prev_w = runs[-2][1] - runs[-2][0]
                    gap_r = r_start - prev_end
                    if (0.45 * bh <= run_w <= max_icon_w and prev_end >= min_text_w
                            and (len(runs) > n_words or gap_r >= max(5, int(round(bh * 0.32))))
                            and (len(runs) > 2 or n_words > 1 or run_w <= prev_w * 0.85)):
                        bw = max(12, int(prev_end + 1))
                        runs = runs[:-1]
                if len(runs) >= 2:
                    l_start, l_end = runs[0]
                    run_w = l_end - l_start
                    next_start = runs[1][0]
                    next_w = runs[1][1] - runs[1][0]
                    gap_l = next_start - l_end
                    if (0.45 * bh <= run_w <= max_icon_w and (bw - next_start) >= min_text_w
                            and (len(runs) > n_words or gap_l >= max(5, int(round(bh * 0.32))))
                            and (len(runs) > 2 or n_words > 1 or run_w <= next_w * 0.85)):
                        shift = max(0, int(next_start - 1))
                        if bw - shift >= 12:
                            bx += shift
                            bw -= shift

        b["bbox"] = (int(bx), int(by), int(max(1, bw)), int(max(1, bh)))

        # Kelime düzeyi kutular (isteğe bağlı 'words'): kırpılan bölgede kalan kelimeleri
        # (uçtaki ikon) at; kutu içindeki satır içi tuş kelimeleri ('R2') korunur.
        wlist = b.get("words")
        if wlist:
            x_lo, x_hi = bx - 1, bx + max(1, bw) + 1
            kept_words = []
            for wd in wlist:
                wb = wd.get("bbox") if isinstance(wd, dict) else None
                if not wb or len(wb) != 4:
                    kept_words.append(wd)
                    continue
                cx = float(wb[0]) + float(wb[2]) * 0.5
                if x_lo <= cx <= x_hi:
                    kept_words.append(wd)
            b["words"] = kept_words

    return kept_boxes
