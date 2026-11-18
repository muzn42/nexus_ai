"""
NEXUS AI — Görüntü Yakalama Katmanı

İki kaynak: PC ekranı ve kamera / capture card.

ÖNEMLİ HIZ NOTU:
  Eski kod her turda TÜM ekranı yakalayıp sonra kırpıyordu (1080p'de ~15-25 ms).
  Burada yalnızca seçilen alan (ROI) yakalanıyor → aynı iş ~1-3 ms.
  Bu tek değişiklik algılama döngüsünü belirgin biçimde hızlandırır.
"""
import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import numpy as np


def _pil_available() -> bool:
    try:
        from PIL import ImageGrab  # noqa: F401
        return True
    except Exception:
        return False


class ScreenSource:
    """PC ekranından (veya seçili bölgeden) görüntü yakalar."""

    name = "screen"

    def __init__(self):
        self._warned = False

    def grab(self, roi=None):
        """
        roi: (x, y, w, h) veya None (tüm ekran)
        Döner: BGR numpy dizisi ya da None
        """
        try:
            from PIL import ImageGrab
            if roi:
                x, y, w, h = [int(v) for v in roi]
                if w <= 0 or h <= 0:
                    return None
                box = (x, y, x + w, y + h)
                img = ImageGrab.grab(bbox=box, all_screens=True)
            else:
                img = ImageGrab.grab(all_screens=True)
            # RGB → BGR (OpenCV/PaddleOCR uyumu)
            arr = np.asarray(img, dtype=np.uint8)
            if arr.ndim == 3 and arr.shape[2] >= 3:
                return arr[:, :, ::-1].copy()
            return arr
        except Exception as e:
            if not self._warned:
                print(f"[CAPTURE] Ekran yakalama hatası: {e}")
                self._warned = True
            return None

    def release(self):
        pass


class CameraSource:
    """Kamera veya HDMI capture card'dan görüntü yakalar."""

    name = "camera"

    def __init__(self, index: int = 0, width: int = 1920, height: int = 1080):
        self.index = index
        self.width = width
        self.height = height
        self._cap = None
        self._warned = False

    def _open(self):
        import cv2
        cap = cv2.VideoCapture(self.index)
        if cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # gecikmeyi azalt
            except Exception:
                pass
        self._cap = cap
        return cap

    def grab(self, roi=None):
        try:
            if self._cap is None or not self._cap.isOpened():
                self._open()
            if self._cap is None or not self._cap.isOpened():
                if not self._warned:
                    print(f"[CAPTURE] Kamera açılamadı (port {self.index})")
                    self._warned = True
                return None
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return None
            if roi:
                x, y, w, h = [int(v) for v in roi]
                fh, fw = frame.shape[:2]
                x, y = max(0, x), max(0, y)
                w, h = min(w, fw - x), min(h, fh - y)
                if w <= 0 or h <= 0:
                    return None
                return frame[y:y + h, x:x + w]
            return frame
        except Exception as e:
            if not self._warned:
                print(f"[CAPTURE] Kamera hatası: {e}")
                self._warned = True
            return None

    def release(self):
        try:
            if self._cap is not None:
                self._cap.release()
        finally:
            self._cap = None


def list_cameras(max_check: int = 3) -> list:
    """
    Kullanılabilir kamera / capture card portlarını listeler.
    İlk açılmayan indekste durur (Windows'ta her başarısız deneme 8-20 sn sürebilir).
    """
    import cv2
    ports = []
    for i in range(max_check):
        cap = cv2.VideoCapture(i)
        try:
            if not cap.isOpened():
                break
            ret, _ = cap.read()
            if ret:
                ports.append(i)
        except Exception:
            break
        finally:
            cap.release()
    return ports


def make_source(source_type: str, camera_index: int = 0, window_handle: int = 0,
                window_title: str = ""):
    """'screen' / 'camera' / 'window' → uygun kaynak nesnesi."""
    if source_type == "camera":
        return CameraSource(camera_index)
    if source_type == "window" and (window_handle or window_title):
        return WindowSource(window_handle, window_title=window_title)
    return ScreenSource()


class WindowSource(ScreenSource):
    """
    Belirli bir pencereyi yakalar.

    Yöntem: pencere istemci alanının EKRAN koordinatları her karede yeniden
    okunur ve o bölge ekrandan yakalanır. Avantajı:
      - Pencere taşınsa / yeniden boyutlansa bile takip eder
      - Donanım hızlandırmalı içerik (video oynatıcı, oyun, Remote Play)
        PrintWindow'da siyah çıkar; bu yöntemde sorunsuz çalışır
    Sınır: pencere başka bir pencerenin altında kalırsa o görüntü yakalanır.
    """

    name = "window"

    def __init__(self, hwnd: int, inset: int = 0, window_title: str = ""):
        super().__init__()
        self.hwnd = int(hwnd or 0)
        self.inset = int(inset)
        self.expected_title = (window_title or "").strip()
        self._last_warn = 0.0
        self._last_resolve = 0.0

    def _resolve_by_title(self):
        """Eski pencere tanıtıcısı geçersizse başlığa göre pencereyi yeniden bul."""
        if not self.expected_title:
            return False
        from core.windows import list_windows
        wins = list_windows(include_own=False)
        target = self.expected_title.lower()
        for w in wins:
            if w["title"].strip().lower() == target:
                self.hwnd = int(w["hwnd"])
                return True
        if "potplayer" in target:
            for w in wins:
                if "potplayer" in w["title"].lower():
                    self.hwnd = int(w["hwnd"])
                    return True
        return False

    def window_title(self) -> str:
        from core.windows import list_windows
        for w in list_windows(include_own=True):
            if w["hwnd"] == self.hwnd:
                return w["title"]
        return self.expected_title or f"Pencere #{self.hwnd}"

    def grab(self, roi=None):
        """
        roi verilirse pencerenin içinde göreli kırpma uygulanır
        (x, y, w, h pencere istemci alanına göredir).
        """
        import time
        from core.windows import is_minimized, window_client_rect

        rect = window_client_rect(self.hwnd) if self.hwnd else None
        if not rect and self.expected_title:
            now = time.time()
            if now - self._last_resolve > 1.0:
                self._last_resolve = now
                if self._resolve_by_title():
                    rect = window_client_rect(self.hwnd)
        if not rect:
            return None

        if is_minimized(self.hwnd):
            if time.time() - self._last_warn > 5:
                print("[CAPTURE] Seçili pencere küçültülmüş.")
                self._last_warn = time.time()
            return None

        wx, wy, ww, wh = rect

        if roi:
            rx, ry, rw, rh = [int(v) for v in roi]
            x, y = wx + rx, wy + ry
            w, h = min(rw, ww - rx), min(rh, wh - ry)
        else:
            x, y, w, h = wx, wy, ww, wh

        if self.inset:
            x += self.inset
            y += self.inset
            w -= self.inset * 2
            h -= self.inset * 2
        if w <= 0 or h <= 0:
            return None
        return super().grab((x, y, w, h))
