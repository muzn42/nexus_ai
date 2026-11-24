"""
NEXUS AI v3 — Kutu Takipçisi ve Kararlılık Motoru (BoxTracker)

Görevi:
  1. Ekranda tespit edilen metin kutularını kareler arasında IoU + metin
     benzerliği ile eşleştirmek (sabit duran kutular yeniden çevrilmez).
  2. Koordinat titremesini (flicker) önlemek için yumuşatma (exponential smoothing)
     uygulamak.
  3. Kararlılık filtresi (Stabilization): Altyazılar anında (1. karede),
     hızla kayan dünya/sokak tabelaları ise ancak ekranda sabitlenince çevrilir.
  4. Ekrandan kaybolan metinlerin yamasını piksel kontrolü ile anında kaldırmak.
"""
import difflib
import time
from dataclasses import dataclass, field
import numpy as np


def _box_iou(b1: tuple, b2: tuple) -> float:
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    ix1 = max(x1, x2)
    iy1 = max(y1, y2)
    ix2 = min(x1 + w1, x2 + w2)
    iy2 = min(y1 + h1, y2 + h2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = w1 * h1 + w2 * h2 - inter
    return inter / float(max(1, union))


def _center_dist(b1: tuple, b2: tuple) -> float:
    cx1, cy1 = b1[0] + b1[2] * 0.5, b1[1] + b1[3] * 0.5
    cx2, cy2 = b2[0] + b2[2] * 0.5, b2[1] + b2[3] * 0.5
    return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5


def _text_sim(t1: str, t2: str) -> float:
    if not t1 or not t2:
        return 0.0
    a, b = t1.strip().lower(), t2.strip().lower()
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _grab_thumb(frame_bgr, bbox: tuple):
    """Kutu bölgesinin piksel değişim kontrolü için küçük özet karesini alır."""
    if frame_bgr is None or not hasattr(frame_bgr, "shape") or frame_bgr.size == 0:
        return None
    try:
        import cv2
        fh, fw = frame_bgr.shape[:2]
        x, y, w, h = [int(v) for v in bbox]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(fw, x + max(1, w)), min(fh, y + max(1, h))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame_bgr[y1:y2, x1:x2]
        return cv2.resize(crop, (32, 16), interpolation=cv2.INTER_AREA)
    except Exception:
        return None


@dataclass
class TrackedBox:
    id: int
    original_text: str
    bbox: tuple
    smoothed_bbox: tuple
    is_subtitle: bool = False
    line_count: int = 1
    translated_text: str = ""
    speaker: str = ""
    source: str = ""
    style: dict = field(default_factory=dict)
    seen_frames: int = 1
    missed_frames: int = 0
    last_seen: float = field(default_factory=time.time)
    is_proper_noun: bool = False
    translation_requested: bool = False
    # Satır içi tuş ikonları: [{"token": "R2", "bbox": (x, y, w, h), "rgb": ndarray}]
    # (core/button_icons.attach_button_icons üretir, patch_overlay çizer)
    icons: list = field(default_factory=list)
    _thumb: object = field(default=None, repr=False)

    def check_still_present(self, frame_bgr, diff_threshold: float = 0.22) -> bool:
        """
        Orijinal karedeki kutu bölgesinin piksel içeriği hâlâ duruyor mu?
        Metin ekrandan silindiğinde anında False döner.
        """
        if self._thumb is None or frame_bgr is None:
            return True
        cur = _grab_thumb(frame_bgr, self.bbox)
        if cur is None or cur.shape != self._thumb.shape:
            return False
        diff = np.abs(cur.astype(np.int16) - self._thumb.astype(np.int16))
        # Ortalama kanal farkı 22/255'i aşan piksel oranı
        changed_ratio = float(np.mean(np.max(diff, axis=2) > 22))
        return changed_ratio <= diff_threshold


class BoxTracker:
    """Kareler arası metin kutusu eşleştirme, kararlılık ve temizleme motoru."""

    def __init__(self):
        self._boxes: dict[int, TrackedBox] = {}
        self._next_id = 1

    def clear(self):
        self._boxes.clear()

    def active_boxes(self) -> list[TrackedBox]:
        return list(self._boxes.values())

    def check_disappearances(self, frame_bgr) -> bool:
        """
        Tam OCR çalıştırmadan mevcut kutuların ekranda hâlâ durup durmadığını
        hızlıca kontrol eder. Herhangi bir kutu silindiyse True döner.
        """
        to_remove = []
        for bid, box in self._boxes.items():
            if not box.check_still_present(frame_bgr):
                to_remove.append(bid)
        for bid in to_remove:
            del self._boxes[bid]
        return bool(to_remove)

    def promote_pending(self, frame_bgr, stabilization_frames: int = 2) -> list[TrackedBox]:
        """
        Ekran değişmediğinde (dirty_rect=None) kararlılık bekleyen kutuların
        yerinde sabit kaldığını piksel kontrolüyle doğrular, seen_frames'i artırır
        ve eşiğe ulaşanları çeviriye hazır olarak döndürür (0 ms OCR).
        """
        req_frames = max(1, int(stabilization_frames))
        need_tr = []
        to_remove = []
        for bid, box in self._boxes.items():
            if box.translated_text or box.translation_requested or box.is_proper_noun:
                continue
            if box.check_still_present(frame_bgr):
                box.seen_frames += 1
                if box.seen_frames >= req_frames:
                    need_tr.append(box)
            else:
                to_remove.append(bid)
        for bid in to_remove:
            del self._boxes[bid]
        return need_tr

    def update(self, detected_boxes: list[dict], frame_bgr,
               is_freeze_mode: bool = False,
               stabilization_frames: int = 2,
               scanned_region: tuple = None,
               style_sampler=None) -> tuple[list[TrackedBox], list[TrackedBox]]:
        """
        Yeni tespit edilen kutularla takip listesini günceller.
        Döner:
          - visible_boxes: ekranda çizilmeye hazır çevrilmiş kutular
          - need_translation: kararlılığa ulaşmış, henüz çevrilmemiş kutular
        """
        now = time.time()
        matched_ids = set()
        used_det = set()

        # 1. Mevcut kutularla eşleştir
        for idx, det in enumerate(detected_boxes):
            d_text = det["text"]
            d_bbox = tuple(det["bbox"])
            d_sub = bool(det.get("is_subtitle", False))
            d_lines = int(det.get("line_count", 1))

            best_id = None
            best_score = 0.0
            for bid, box in self._boxes.items():
                if bid in matched_ids:
                    continue
                sim = _text_sim(box.original_text, d_text)
                if sim < 0.82:
                    continue
                iou = _box_iou(box.bbox, d_bbox)
                dist = _center_dist(box.bbox, d_bbox)
                max_jump = max(48.0, d_bbox[3] * 1.6)
                if iou > 0.20 or dist <= max_jump:
                    score = sim + iou
                    if score > best_score:
                        best_score = score
                        best_id = bid

            if best_id is not None:
                matched_ids.add(best_id)
                used_det.add(idx)
                box = self._boxes[best_id]

                # Kutu hızlı kayıyorsa kararlılığı sıfırla (hareketli tabela filtresi)
                jump = _center_dist(box.bbox, d_bbox)
                stable_limit = max(22.0, d_bbox[3] * 0.75)
                if not d_sub and not is_freeze_mode and jump > stable_limit and not box.translated_text:
                    box.seen_frames = 1
                else:
                    box.seen_frames += 1

                box.missed_frames = 0
                box.last_seen = now
                box.is_subtitle = d_sub
                box.line_count = d_lines
                box.bbox = d_bbox
                # İkonları yalnızca aday yeni ikon taşıyorsa tazele (OCR'ın kaçırdığı karede kaybolmasın)
                if det.get("icons"):
                    box.icons = list(det["icons"])

                # Yumuşatılmış koordinat (flicker önleme)
                ox, oy, ow, oh = box.smoothed_bbox
                nx, ny, nw, nh = d_bbox
                if jump <= max(6.0, d_bbox[3] * 0.15):
                    # Çok küçük OCR kutu titremesini sönümle
                    pass
                else:
                    box.smoothed_bbox = (
                        int(round(0.65 * ox + 0.35 * nx)),
                        int(round(0.65 * oy + 0.35 * ny)),
                        int(round(0.65 * ow + 0.35 * nw)),
                        int(round(0.65 * oh + 0.35 * nh)),
                    )

                if style_sampler and (not box.style or box.seen_frames <= 2):
                    box.style = style_sampler(frame_bgr, box.smoothed_bbox)
                box._thumb = _grab_thumb(frame_bgr, box.bbox)

        # 2. Eşleşmeyen yeni kutuları ekle
        for idx, det in enumerate(detected_boxes):
            if idx in used_det:
                continue
            d_bbox = tuple(det["bbox"])
            d_sub = bool(det.get("is_subtitle", False))
            style = style_sampler(frame_bgr, d_bbox) if style_sampler else {}
            bid = self._next_id
            self._next_id += 1
            self._boxes[bid] = TrackedBox(
                id=bid,
                original_text=det["text"],
                bbox=d_bbox,
                smoothed_bbox=d_bbox,
                is_subtitle=d_sub,
                line_count=int(det.get("line_count", 1)),
                style=style,
                seen_frames=1,
                missed_frames=0,
                last_seen=now,
                _thumb=_grab_thumb(frame_bgr, d_bbox),
                icons=list(det.get("icons") or []),
            )
            matched_ids.add(bid)

        # 3. Görünmeyen kutuları kontrol et ve temizle
        to_delete = []
        for bid, box in self._boxes.items():
            if bid in matched_ids:
                continue
            # Eğer tarama bölgesi verildiyse ve kutu bu bölgenin dışındaysa,
            # piksel kontrolüyle hala duruyorsa koru
            in_scanned = True
            if scanned_region and len(scanned_region) == 4:
                sx, sy, sw, sh = scanned_region
                cx = box.bbox[0] + box.bbox[2] * 0.5
                cy = box.bbox[1] + box.bbox[3] * 0.5
                in_scanned = (sx <= cx <= sx + sw and sy <= cy <= sy + sh)

            if not in_scanned:
                if box.check_still_present(frame_bgr):
                    continue
                to_delete.append(bid)
                continue

            # Tarama bölgesindeydi ama artık OCR bulamadı → piksel değişmişse anında sil
            if not box.check_still_present(frame_bgr):
                to_delete.append(bid)
                continue

            box.missed_frames += 1
            max_miss = 1 if box.is_subtitle else 2
            if box.missed_frames >= max_miss:
                to_delete.append(bid)

        for bid in to_delete:
            del self._boxes[bid]

        # 4. Görünür ve çevrilmesi gereken kutuları ayır
        visible = []
        need_translation = []
        req_frames = max(1, int(stabilization_frames))

        for box in self._boxes.values():
            ready = box.is_subtitle or is_freeze_mode or (box.seen_frames >= req_frames)
            if not ready:
                continue
            if not box.translated_text and not box.translation_requested and not box.is_proper_noun:
                need_translation.append(box)
            elif box.translated_text and not box.is_proper_noun:
                visible.append(box)

        return visible, need_translation
