"""
Gerçek GTA 6 kareleri üzerinde uçtan uca OCR + temizleme/etiketleme/kırpma testi.
Gerçek OCREngine (PP-OCRv6 / small / cpu) kullanılır; kareler hem yerel (1024x576)
hem de 1920x1080'e büyütülmüş hâlde denenir.

Kareler repoda tutulmaz. Klasör NEXUS_TEST_FRAMES ortam değişkeniyle verilir
(gta6_1.png, gta6_2.png, gta6_3.png); bulunamazsa veya PaddleOCR yoksa test atlanır.

Çalıştırma: python tests/test_real_frames.py   veya   pytest tests/test_real_frames.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DEFAULT_FRAMES = (
    r"C:/Users/musta/AppData/Local/Temp/claude/97e48e3a03c492d8/"
    r"9598abab-4d2b-43e6-a80e-57d2097a8da7/scratchpad/frames"
)
FRAMES_DIR = os.environ.get("NEXUS_TEST_FRAMES", _DEFAULT_FRAMES)
SCALES = {"native": None, "1080p": (1920, 1080)}

_ENGINE = None


class _Skip(Exception):
    pass


def _skip(msg):
    try:
        import pytest
        pytest.skip(msg)
    except ImportError:
        raise _Skip(msg)


def _engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from core.ocr_engine import OCREngine
        except Exception as e:  # paddle yok
            _skip(f"OCREngine yüklenemedi: {e}")
        _ENGINE = OCREngine(version="PP-OCRv6", model_size="small", device="cpu")
    return _ENGINE


def _load(n: int, scale: str):
    import cv2
    path = os.path.join(FRAMES_DIR, f"gta6_{n}.png")
    if not os.path.isfile(path):
        _skip(f"kare yok: {path}")
    img = cv2.imread(path)
    size = SCALES[scale]
    if size is not None:
        img = cv2.resize(img, size, interpolation=cv2.INTER_CUBIC)
    return img


def _run_pipeline(img):
    """core/pipeline.py dünya geçişindeki filtre -> temizle -> birleştir -> kırp sırasının aynısı."""
    from core.ocr_engine import merge_nearby_boxes
    from core.text_filter import (clean_ocr_game_text, is_translatable_game_text,
                                  trim_button_icons_from_boxes)
    raw = _engine().read_boxes(img)
    filtered = []
    for b in raw:
        if not is_translatable_game_text(b["text"], b["score"], b["bbox"]):
            continue
        item = dict(b)
        cleaned = clean_ocr_game_text(item["text"])
        if cleaned:
            item["text"] = cleaned
        filtered.append(item)
    merged = [b for b in merge_nearby_boxes(filtered)
              if is_translatable_game_text(b["text"], b["score"], b["bbox"])]
    kept = trim_button_icons_from_boxes(raw, merged, frame_bgr=img)
    return raw, kept


def _find(kept, needle):
    return [b for b in kept if needle.lower() in b["text"].lower()]


def _sx(img):
    return img.shape[1] / 1024.0


def _check_frame1(img):
    raw, kept = _run_pipeline(img)
    texts = [b["text"] for b in kept]
    # R1 rozeti, $407, filigran çevrilmez
    assert not any(t.strip("[]") == "R1" for t in texts), texts
    assert not _find(kept, "SHIRRAK"), texts
    assert not _find(kept, "$407"), texts
    assert _find(kept, "WEAPONS") and _find(kept, "ITEMS"), texts
    assert _find(kept, "UNARMED"), texts
    hits = _find(kept, "binoculars")
    assert hits, texts
    t = hits[0]["text"]
    # OCR R dairesini okuduysa '[R]' etiketlenir; okuyamadıysa (1080p) çıplak 'R' kalmamalı
    if "R" in [w["text"] for b in raw for w in b.get("words", [])] or " R " in t:
        assert "Use [R] to select your binoculars" in t, t
    assert " R " not in t, t
    return texts


def _check_frame2(img):
    raw, kept = _run_pipeline(img)
    texts = [b["text"] for b in kept]
    s = _sx(img)
    badge_right = 44 * s  # R2/L2 rozetlerinin sağ kenarı (1024 ölçeğinde x≈27..44)
    acc = _find(kept, "Accelerate")
    assert acc, texts
    a = acc[0]
    assert a["text"] in ("Accelerate", "[R2] Accelerate"), a["text"]
    if a["text"] == "Accelerate":
        assert a["bbox"][0] >= badge_right - 2 * s, (a["bbox"], badge_right)
    brake = _find(kept, "Brake and reverse")
    assert brake, texts
    b = brake[0]
    assert b["text"].endswith("Brake and reverse"), b["text"]
    if not b["text"].startswith("[L2]"):
        assert b["bbox"][0] >= badge_right - 2 * s, (b["bbox"], badge_right)
    # Rozet kutuları ('R2', 'L2', yanlış okunan '12') tek başına çevrilmez
    assert not any(t in ("R2", "L2", "12", "[R2]", "[L2]") for t in texts), texts
    assert _find(kept, "Collect the package"), texts
    assert not _find(kept, "SHIRRAK"), texts
    return texts


def _check_frame3(img):
    raw, kept = _run_pipeline(img)
    texts = [b["text"] for b in kept]
    s = _sx(img)
    icon_right = 389 * s  # X dairesinin sağ kenarı (1024 ölçeğinde x≈368..389)
    gu = _find(kept, "GET UP")
    assert gu, texts
    g = gu[0]
    assert g["text"] in ("GET UP", "[X] GET UP"), g["text"]
    if g["text"] == "GET UP":
        # Yama X dairesini örtmemeli (en fazla ~2 px sınır taşması)
        assert g["bbox"][0] >= icon_right - 2 * s, (g["bbox"], icon_right)
    assert not _find(kept, "SHIRRAK"), texts
    assert not any("★" in t for t in texts), texts
    return texts


def test_frame1_weapon_wheel():
    for sc in SCALES:
        _check_frame1(_load(1, sc))


def test_frame2_hint_panel():
    for sc in SCALES:
        _check_frame2(_load(2, sc))


def test_frame3_get_up():
    for sc in SCALES:
        _check_frame3(_load(3, sc))


if __name__ == "__main__":
    fails = 0
    for n, fn in ((1, _check_frame1), (2, _check_frame2), (3, _check_frame3)):
        for sc in SCALES:
            try:
                img = _load(n, sc)
                raw, kept = _run_pipeline(img)
                print(f"=== gta6_{n} {sc}")
                for b in raw:
                    print(f"  RAW  {b['text']!r} {b['score']:.3f} {b['bbox']}")
                for b in kept:
                    print(f"  KEPT {b['text']!r} {b['bbox']}")
                fn(img)
                print(f"OK   gta6_{n} {sc}")
            except _Skip as e:
                print(f"SKIP gta6_{n} {sc}: {e}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL gta6_{n} {sc}: {e!r}")
    print("Tümü geçti." if not fails else f"{fails} test başarısız.")
    sys.exit(1 if fails else 0)
