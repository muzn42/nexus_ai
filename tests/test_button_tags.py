"""
Tuş etiketi (R2, L1, X ...) ve ikon kırpma testleri.
Çalıştırma: python tests/test_button_tags.py   veya   pytest tests/test_button_tags.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core.text_filter import (  # noqa: E402
    BUTTON_TOKENS,
    button_token,
    clean_ocr_game_text,
    is_translatable_game_text,
    tag_button_tokens,
    trim_button_icons_from_boxes,
)


def test_button_tokens_set():
    for t in ("R1", "R2", "R3", "L1", "L2", "L3", "X", "O", "TRIANGLE", "SQUARE",
              "OPTIONS", "TOUCHPAD", "LB", "RB", "LT", "RT", "A", "B", "Y", "DPAD"):
        assert t in BUTTON_TOKENS, t


def test_button_token():
    assert button_token("R2") == "R2"
    assert button_token("r2") == "R2"
    assert button_token("(R2)") == "R2"
    assert button_token("[L1]") == "L1"
    assert button_token("R2.") == "R2"
    assert button_token("D-PAD") == "DPAD"
    assert button_token("△") == "TRIANGLE"
    assert button_token("X") == "X"
    assert button_token("(X)") == "X"
    assert button_token("A") == "A"  # bağlamdan bağımsız; çağıran karar verir
    assert button_token("Press") is None
    assert button_token("fire") is None
    assert button_token("") is None
    assert button_token("[E]") is None


def test_tag_button_tokens():
    assert tag_button_tokens("Press R2 to fire") == "Press [R2] to fire"
    assert tag_button_tokens("Hold (L2) to aim") == "Hold [L2] to aim"
    assert tag_button_tokens("Use R to select") == "Use [R] to select"
    assert tag_button_tokens("Press [R2] to fire") == "Press [R2] to fire"
    assert tag_button_tokens("Press R2.") == "Press [R2]."
    assert tag_button_tokens("Press X or O to cancel") == "Press [X] or [O] to cancel"
    assert tag_button_tokens("Press L1/R1 to switch") == "Press [L1]/[R1] to switch"
    assert tag_button_tokens("Press TRIANGLE to enter") == "Press [TRIANGLE] to enter"
    # İngilizce artikel / normal kelimeler etiketlenmez
    assert tag_button_tokens("Use a car to escape") == "Use a car to escape"
    assert tag_button_tokens("A car is waiting") == "A car is waiting"
    assert tag_button_tokens("Steal a car and drive") == "Steal a car and drive"
    assert tag_button_tokens("O Lord") == "O Lord"
    assert tag_button_tokens("Options") == "Options"
    assert tag_button_tokens("Create a new outfit") == "Create a new outfit"
    assert tag_button_tokens("Cross the bridge") == "Cross the bridge"


def test_clean_ocr_game_text():
    assert clean_ocr_game_text("Press R2 to fire") == "Press [R2] to fire"
    assert clean_ocr_game_text("Holdto (L2) aim") == "Hold to [L2] aim"
    assert clean_ocr_game_text("Use R to select") == "Use [R] to select"
    assert clean_ocr_game_text("SELECT X") == "SELECT"
    assert clean_ocr_game_text("BACK O") == "BACK"
    assert clean_ocr_game_text("SELECTX") == "SELECT"
    assert clean_ocr_game_text("SELECT (X)") == "SELECT"
    assert clean_ocr_game_text("PHOTO STUDIO") == "PHOTO STUDIO"
    # Gerçek OCR tuhaflıkları (GTA 6 kareleri)
    assert clean_ocr_game_text("R2Accelerate") == "[R2] Accelerate"
    assert clean_ocr_game_text("L2Brake and reverse") == "[L2] Brake and reverse"
    assert clean_ocr_game_text("12Brake and reverse") == "Brake and reverse"
    assert clean_ocr_game_text("@GET UP") == "GET UP"
    assert clean_ocr_game_text("Use R") == "Use [R]"
    assert clean_ocr_game_text("PRESS X") == "PRESS [X]"
    assert clean_ocr_game_text("Use ® to select your binoculars") == "Use [R] to select your binoculars"
    assert clean_ocr_game_text("Use R to select your binoculars") == "Use [R] to select your binoculars"
    assert clean_ocr_game_text("IN HAND") == "IN HAND"
    assert clean_ocr_game_text("3D Printer") == "3D Printer"


def test_is_translatable_button_only():
    for t in ("R2", "[R2]", "(X)", "X", "(R2)", "[TRIANGLE]", "L1 R1", "L1/R1", "[L2] [R2]"):
        assert not is_translatable_game_text(t, 0.99, (100, 100, 40, 30)), t
    assert is_translatable_game_text("Press R2 to fire", 0.99, (100, 100, 300, 40))
    assert is_translatable_game_text("Hold L2 to aim", 0.99, (100, 100, 300, 40))
    assert is_translatable_game_text("Options", 0.99, (100, 100, 120, 40))
    assert is_translatable_game_text("Collect the package", 0.99, (100, 100, 300, 40))


def _make_hud_frame():
    """1080p kare: koyu zemin, 50 px yüksek beyaz 'yazı' blokları + sağ uçta kare ikon."""
    fh, fw = 1080, 1920
    frame = np.full((fh, fw, 3), 20, dtype=np.uint8)
    y, h = 900, 50
    x = 1400
    # 'Sprint' benzeri metin: 6 harf, harf genişliği ~22 px, harf arası 6 px
    cx = x + 4
    for _ in range(6):
        frame[y + 10:y + 40, cx:cx + 22] = 235
        cx += 28
    text_end = cx - 6  # son harfin sağ kenarı
    # İkon: metinden 30 px sonra 44x44 açık kare
    icon_x = text_end + 30
    frame[y + 3:y + 47, icon_x:icon_x + 44] = 220
    box_w = (icon_x + 44 + 4) - x
    return frame, (x, y, box_w, h), text_end, icon_x


def test_trim_icon_1080p():
    frame, bbox, text_end, icon_x = _make_hud_frame()
    x, y, w, h = bbox
    words = [
        {"text": "Sprint", "bbox": (x + 4, y + 10, text_end - x - 4, 30)},
        {"text": "X", "bbox": (icon_x, y + 3, 44, 44)},
    ]
    box = {"text": "Sprint", "score": 0.98, "bbox": bbox, "words": words}
    out = trim_button_icons_from_boxes([], [box], frame)
    nx, ny, nw, nh = out[0]["bbox"]
    assert nx == x, (nx, x)
    assert nx + nw <= icon_x, (nx + nw, icon_x)       # ikon kutu dışında kaldı
    assert nx + nw >= text_end - 2, (nx + nw, text_end)  # metin kırpılmadı
    texts = [wd["text"] for wd in out[0]["words"]]
    assert texts == ["Sprint"], texts


def test_trim_keeps_inline_token_words():
    frame = np.full((1080, 1920, 3), 20, dtype=np.uint8)
    x, y, w, h = 500, 900, 400, 50
    words = [
        {"text": "Press", "bbox": (500, 905, 100, 40)},
        {"text": "R2", "bbox": (610, 905, 44, 40)},
        {"text": "to", "bbox": (665, 905, 40, 40)},
        {"text": "fire", "bbox": (715, 905, 80, 40)},
    ]
    # Sağ uçta OCR'ın ayrı kutu olarak bulduğu '(X)' ikonu (path A)
    raw = [{"text": "(X)", "score": 0.95, "bbox": (860, 905, 40, 40)}]
    box = {"text": "Press R2 to fire", "score": 0.98, "bbox": (x, y, w, h), "words": words}
    out = trim_button_icons_from_boxes(raw, [box], frame)
    nx, ny, nw, nh = out[0]["bbox"]
    assert nx + nw <= 860, out[0]["bbox"]
    assert out[0]["text"] == "Press [R2] to fire"
    assert [wd["text"] for wd in out[0]["words"]] == ["Press", "R2", "to", "fire"]


def test_imports():
    import core.llm_chain as lc
    import core.translation_engine as te
    assert "[R2]" in lc.SYSTEM_PROMPT and "[R2]" in lc.BATCH_SYSTEM_PROMPT
    lc.SYSTEM_PROMPT.format(lang="Türkçe")
    lc.BATCH_SYSTEM_PROMPT.format(lang="Türkçe")
    assert te._bare_button_tags("Press [R2] to fire") == "Press R2 to fire"
    assert te._bare_button_tags("[1] Press [E]") == "[1] Press [E]"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e!r}")
    print("Tümü geçti." if not fails else f"{fails} test başarısız.")
    sys.exit(1 if fails else 0)
