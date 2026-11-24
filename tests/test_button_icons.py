"""
Satır içi tuş ikonları testleri: core/button_icons.attach_button_icons,
merge_nearby_boxes kelime koruma, TrackedBox ikon aktarımı ve PatchOverlayWindow
üzerinde ikonun satır içi çizimi (offscreen Qt).

Çalıştırma: python tests/test_button_icons.py   veya   pytest tests/test_button_icons.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core.box_tracker import BoxTracker, TrackedBox  # noqa: E402
from core.button_icons import GLYPH_TOKEN, attach_button_icons  # noqa: E402
from core.ocr_engine import OCREngine, merge_nearby_boxes  # noqa: E402


# ---------------------------------------------------------------- sentetik kare
def _frame_with_badge():
    """Koyu zemin; x=100..130 arası beyaz yuvarlak rozet içinde koyu 'R2', ardından 'to fire'."""
    img = np.full((120, 480, 3), 35, np.uint8)
    cv2.rectangle(img, (104, 40), (126, 70), (255, 255, 255), -1)
    cv2.rectangle(img, (100, 44), (130, 66), (255, 255, 255), -1)
    for cx, cy in ((104, 44), (126, 44), (104, 66), (126, 66)):
        cv2.circle(img, (cx, cy), 4, (255, 255, 255), -1)
    cv2.putText(img, "R2", (103, 63), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 2)
    cv2.putText(img, "Press", (20, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, "to fire", (142, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


def _frame_with_circle():
    """'Use (O) to select': iki kelime arasında OCR'ın okumadığı beyaz daire ikonu."""
    img = np.full((120, 480, 3), 35, np.uint8)
    cv2.putText(img, "Use", (20, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.circle(img, (95, 55), 12, (255, 255, 255), -1)
    cv2.putText(img, "R", (89, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 2)
    cv2.putText(img, "to select", (120, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


def test_attach_badge_icon():
    img = _frame_with_badge()
    box = {
        "text": "Press [R2] to fire",
        "bbox": (18, 40, 260, 30),
        "line_count": 1,
        "words": [
            {"text": "Press", "bbox": (18, 45, 75, 22)},
            {"text": "R2", "bbox": (104, 45, 20, 22)},   # OCR kelime kutusu rozetten dar
            {"text": "to", "bbox": (142, 45, 30, 22)},
            {"text": "fire", "bbox": (180, 45, 55, 22)},
        ],
    }
    attach_button_icons(box, img)
    icons = box.get("icons") or []
    assert len(icons) == 1, icons
    ic = icons[0]
    assert ic["token"] == "R2"
    x, y, w, h = ic["bbox"]
    # Rozeti (100..130 x 40..70) kapsamalı, komşu "to"/"Press" metnine taşmamalı
    assert x <= 101 and x + w >= 129, ic["bbox"]
    assert x >= 93 and x + w <= 140, ic["bbox"]
    assert y <= 41 and y + h >= 69, ic["bbox"]
    rgb = ic["rgb"]
    assert rgb.dtype == np.uint8 and rgb.flags["C_CONTIGUOUS"] and rgb.shape == (h, w, 3)
    assert box["text"] == "Press [R2] to fire"


def test_attach_unread_gap_icon_inserts_btn():
    img = _frame_with_circle()
    box = {
        "text": "Use to select",
        "bbox": (18, 42, 230, 28),
        "line_count": 1,
        "words": [
            {"text": "Use", "bbox": (18, 45, 56, 22)},
            {"text": "to", "bbox": (120, 47, 30, 20)},
            {"text": "select", "bbox": (160, 45, 90, 22)},
        ],
    }
    attach_button_icons(box, img)
    assert box["text"] == f"Use [{GLYPH_TOKEN}] to select", box["text"]
    icons = box.get("icons") or []
    assert [i["token"] for i in icons] == [GLYPH_TOKEN]
    x, y, w, h = icons[0]["bbox"]
    assert 80 <= x <= 84 and 106 <= x + w <= 110, icons[0]["bbox"]


def test_leading_icon_outside_box_expands_bbox():
    """GTA '(X) GET UP': OCR daireyi okumaz, satır kutusu dairenin sağından başlar."""
    img = np.full((100, 300, 3), 60, np.uint8)
    cv2.circle(img, (60, 50), 13, (255, 255, 255), 2)
    cv2.line(img, (53, 43), (67, 57), (255, 255, 255), 2)
    cv2.line(img, (67, 43), (53, 57), (255, 255, 255), 2)
    cv2.putText(img, "GET UP", (80, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    box = {"text": "GET UP", "bbox": (78, 38, 90, 24), "line_count": 1,
           "words": [{"text": "GET", "bbox": (80, 38, 45, 24)},
                     {"text": "UP", "bbox": (130, 38, 35, 24)}]}
    attach_button_icons(box, img)
    assert box["text"] == f"[{GLYPH_TOKEN}] GET UP", box["text"]
    ix, iy, iw, ih = box["icons"][0]["bbox"]
    assert 44 <= ix <= 48 and 72 <= ix + iw <= 76, box["icons"][0]["bbox"]
    assert box["bbox"][0] == ix and box["bbox"][0] + box["bbox"][2] == 168


def test_wide_gap_icon_detected_without_verb():
    # Geniş boşluktaki (>= 0.9 × satır) ikon lekesi fiil/to olmadan da yakalanır:
    # kullanıcı tüm PS5 simgelerinin korunmasını istiyor.
    img = _frame_with_circle()
    box = {
        "text": "Collect the package",
        "bbox": (18, 42, 230, 28),
        "line_count": 1,
        "words": [
            {"text": "Collect", "bbox": (18, 45, 56, 22)},
            {"text": "the", "bbox": (120, 47, 30, 20)},
            {"text": "package", "bbox": (160, 45, 90, 22)},
        ],
    }
    attach_button_icons(box, img)
    assert box["text"] == "Collect [BTN] the package", box["text"]
    assert len(box["icons"]) == 1


def test_single_letter_without_blob_is_ignored():
    img = np.full((80, 400, 3), 35, np.uint8)
    cv2.putText(img, "Get in a car", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    box = {
        "text": "Get in a car",
        "bbox": (18, 30, 200, 28),
        "words": [
            {"text": "Get", "bbox": (18, 32, 50, 24)},
            {"text": "in", "bbox": (75, 32, 25, 24)},
            {"text": "a", "bbox": (108, 38, 15, 18)},
            {"text": "car", "bbox": (130, 38, 50, 18)},
        ],
    }
    attach_button_icons(box, img)
    assert "icons" not in box and box["text"] == "Get in a car"


def test_attach_never_raises_and_is_fast():
    attach_button_icons({"words": [{"text": "R2", "bbox": None}]}, np.zeros((10, 10, 3), np.uint8))
    attach_button_icons({"words": [{"text": "R2", "bbox": (5000, 5000, 10, 10)}]},
                        np.zeros((10, 10, 3), np.uint8))
    attach_button_icons({"words": "garbage"}, None)
    attach_button_icons({}, np.zeros((0, 0, 3), np.uint8))

    img = _frame_with_badge()
    words = [{"text": "Press", "bbox": (18, 45, 75, 22)}, {"text": "R2", "bbox": (104, 45, 20, 22)},
             {"text": "to", "bbox": (142, 45, 30, 22)}, {"text": "fire", "bbox": (180, 45, 55, 22)}]
    n = 200
    t0 = time.perf_counter()
    for _ in range(n):
        attach_button_icons({"text": "Press [R2] to fire", "bbox": (18, 40, 260, 30),
                             "words": [dict(w) for w in words]}, img)
    per_ms = (time.perf_counter() - t0) * 1000 / n
    print(f"attach_button_icons: {per_ms:.3f} ms/kutu")
    assert per_ms < 1.0, per_ms


# ---------------------------------------------------------------- OCR yardımcıları
def test_group_words_from_paddle_tokens():
    tokens = ["Press", " ", "R2", " ", "to", ",", "fire"]
    boxes = [[0, 0, 50, 20], [50, 0, 55, 20], [55, 0, 75, 20], [75, 0, 80, 20],
             [80, 0, 100, 20], [100, 0, 104, 20], [104, 0, 140, 20]]
    words = OCREngine._group_words(tokens, np.array(boxes))
    assert [w[0] for w in words] == ["Press", "R2", "to,fire"]
    assert words[1][1] == (55.0, 0.0, 20.0, 20.0)
    assert OCREngine._group_words(["a", "b"], [[0, 0, 1, 1]]) == []   # uyumsuz uzunluk


def test_merge_nearby_boxes_preserves_words():
    a = {"text": "Press", "score": 0.9, "bbox": (100, 500, 80, 30), "poly": [],
         "words": [{"text": "Press", "bbox": (100, 500, 80, 30)}]}
    b = {"text": "[R2] to fire", "score": 0.9, "bbox": (190, 500, 150, 30), "poly": [],
         "words": [{"text": "R2", "bbox": (190, 500, 30, 30)},
                   {"text": "to", "bbox": (230, 500, 30, 30)},
                   {"text": "fire", "bbox": (270, 500, 70, 30)}]}
    c = {"text": "and keep shooting at the target", "score": 0.9, "bbox": (100, 534, 300, 30),
         "poly": []}  # kelime verisi olmayan kutu da birleşebilmeli
    merged = merge_nearby_boxes([a, b, c])
    assert len(merged) == 1, merged
    m = merged[0]
    assert m["text"] == "Press [R2] to fire and keep shooting at the target"
    assert [w["text"] for w in m["words"]] == ["Press", "R2", "to", "fire"]
    # Girdi sözlükleri değiştirilmemeli
    assert len(a["words"]) == 1
    # Kelimesiz kutular "words" anahtarı almaz
    assert "words" not in merge_nearby_boxes([c])[0]


# ---------------------------------------------------------------- BoxTracker
def test_tracked_box_icons_propagation():
    frame = _frame_with_badge()
    icon = {"token": "R2", "bbox": (100, 40, 31, 31), "rgb": np.zeros((31, 31, 3), np.uint8)}
    tr = BoxTracker()
    det = {"text": "Press [R2] to fire", "bbox": (18, 40, 260, 30), "icons": [icon]}
    tr.update([det], frame, stabilization_frames=1)
    boxes = tr.active_boxes()
    assert len(boxes) == 1 and boxes[0].icons and boxes[0].icons[0]["token"] == "R2"

    # İkonsuz güncelleme mevcut ikonları silmemeli
    tr.update([{"text": "Press [R2] to fire", "bbox": (18, 40, 260, 30)}], frame,
              stabilization_frames=1)
    assert tr.active_boxes()[0].icons[0]["token"] == "R2"

    # Yeni ikonlu güncelleme tazelemeli
    icon2 = dict(icon, token="L2")
    tr.update([{"text": "Press [R2] to fire", "bbox": (18, 40, 260, 30), "icons": [icon2]}],
              frame, stabilization_frames=1)
    assert tr.active_boxes()[0].icons[0]["token"] == "L2"
    assert TrackedBox(id=1, original_text="x", bbox=(0, 0, 1, 1), smoothed_bbox=(0, 0, 1, 1)).icons == []


# ---------------------------------------------------------------- Yama katmanı
def test_patch_overlay_draws_inline_icon():
    from PySide6.QtWidgets import QApplication
    from ui.qt.patch_overlay import PatchOverlayWindow

    app = QApplication.instance() or QApplication([])
    w = PatchOverlayWindow()
    w._topmost_timer.stop()
    w.setGeometry(0, 0, 640, 200)

    red = np.zeros((30, 30, 3), np.uint8)
    red[:, :, 0] = 255  # RGB: saf kırmızı → ekranda kolayca bulunur

    class _Box:
        pass

    def _mk(text, icons, speaker="", y=40):
        b = _Box()
        b.translated_text = text
        b.smoothed_bbox = (20, y, 560, 40)
        b.is_subtitle = True
        b.is_proper_noun = False
        b.line_count = 1
        b.speaker = speaker
        b.style = {"bg_color": (20, 20, 20), "fg_color": (255, 255, 255), "align": "center"}
        b.icons = icons
        return b

    boxes = [
        _mk("Ateş etmek için [R2] tuşuna bas", [{"token": "r2", "rgb": red, "bbox": (0, 0, 30, 30)}]),
        # İkonsuz etiket → hap; konuşmacı öneki korunmalı
        _mk("[L2] ile fren yap", [], speaker="Lucia", y=110),
    ]
    w._boxes = boxes  # set_boxes geometriyi frame_size'a göre değiştirmesin
    w.resize(640, 200)
    img = w.grab().toImage()
    assert not img.isNull()

    found_red = 0
    for yy in range(40, 80, 2):
        for xx in range(20, 600, 2):
            c = img.pixelColor(xx, yy)
            if c.red() > 200 and c.green() < 60 and c.blue() < 60:
                found_red += 1
    assert found_red > 10, f"satır içi ikon çizilmedi ({found_red})"

    # Ölçüm: etiketli satır, ikon atomu sayesinde ham "[R2]" metninden farklı genişlikte ölçülür
    from PySide6.QtGui import QFont, QFontMetricsF
    f = QFont("Segoe UI")
    f.setPixelSize(20)
    m = QFontMetricsF(f)
    imap = {"R2": [{"token": "R2", "rgb": red}]}
    wi = PatchOverlayWindow._measure("için [R2] tuşuna", m, imap, f)
    assert abs(wi - (m.horizontalAdvance("için ") + m.height() + 2.0 + m.horizontalAdvance(" tuşuna"))) < 0.5
    w.close()


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
