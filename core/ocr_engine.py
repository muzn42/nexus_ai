"""
NEXUS AI v2 — OCR Motor Modülü
PaddleOCR 3.7+ wrapper ile temiz metin çıkarma.

PP-OCRv6 için üç model boyutu desteklenir:
  tiny   → en hızlı (1.5M), temiz/düz ekran altyazıları için
  small  → hız / doğruluk dengesi (varsayılan)
  medium → en doğru, ağır (CPU'da yavaş)

ÖNEMLİ (Paddle 3.3.x regresyonu):
  paddlepaddle 3.3.0/3.3.1 sürümlerinde oneDNN (MKLDNN) + yeni PIR yürütücüsü
  "ConvertPirAttribute2RuntimeAttribute not support" hatası veriyor
  (GitHub: PaddlePaddle/Paddle#77340, #79749). Bu durumda OCR 3-10 kat yavaşlar.
  Motor bunu ilk açılışta bir ön-ısınma (warmup) tahminiyle tespit eder, otomatik
  olarak CPU moduna geçer ve sonucu diske yazar; böylece her açılışta 10 sn'lik
  boşa deneme yapılmaz.
  Kalıcı çözüm:  pip install paddlepaddle==3.2.2
"""
import json
import os
import threading
import time

_INIT_LOCK = threading.Lock()

os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
os.environ.setdefault("GLOG_minloglevel", "2")

# PP-OCRv6 alt model boyutları → (det modeli, rec modeli)
MODEL_SIZE_PRESETS = {
    "tiny": ("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec"),
    "small": ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"),
    "medium": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
}
DEFAULT_MODEL_SIZE = "small"

# MKLDNN'in bu Paddle sürümünde çalışıp çalışmadığını hatırlamak için küçük durum dosyası
_STATE_FILE = os.path.join(os.path.expanduser("~"), ".nexus_ai", "ocr_state.json")


def _paddle_version() -> str:
    """
    Paddle sürümü — modülü import ETMEDEN okunur.
    (paddle'ı paddleocr'dan önce import etmek bu ortamda torch/modelscope
    DLL çakışmasına yol açabiliyor; bu yüzden metadata kullanılır.)
    """
    try:
        from importlib.metadata import version
        return version("paddlepaddle")
    except Exception:
        return "?"


def _load_state() -> dict:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def _dummy_image():
    """Ön-ısınma için boş bir görüntü (altyazı şeridine yakın boyut)."""
    import numpy as np
    return np.full((112, 640, 3), 255, dtype=np.uint8)


def _enable_nvidia_dlls() -> bool:
    """
    pip ile kurulan nvidia-* paketlerinin (cuDNN / cuBLAS) DLL klasörlerini PATH'e ekler.
    paddlepaddle-gpu, cuDNN'i sistemde aramak yerine bu klasörlerden de bulabilir.
    """
    import glob
    import sysconfig
    try:
        site_packages = sysconfig.get_paths()["purelib"]
    except Exception:
        return False
    found = False
    for dll_dir in glob.glob(os.path.join(site_packages, "nvidia", "*", "bin")):
        if dll_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(dll_dir)
            except Exception:
                pass
            found = True
    return found


class OCREngine:
    """
    PaddleOCR'ı saran temiz bir arayüz.
    Lazy-init: İlk kullanımda başlatılır.
    MKLDNN CPU hızlandırmasını varsayılan olarak dener, hata verirse otomatik fallback yapar.
    """

    def __init__(self, version: str = "PP-OCRv6", use_mkldnn: bool = True,
                 model_size: str = DEFAULT_MODEL_SIZE, device: str = "gpu"):
        self.version = version
        self.use_mkldnn = use_mkldnn
        self.model_size = model_size if model_size in MODEL_SIZE_PRESETS else DEFAULT_MODEL_SIZE
        self.device = device if device in ("cpu", "gpu") else "gpu"
        self._ocr = None
        self._mkldnn_known_bad = False
        self._predict_lock = threading.Lock()
        self.last_init_seconds = 0.0
        self.last_infer_seconds = 0.0
        self._restore_mkldnn_state()

    # ----- MKLDNN durumu (Paddle sürümüne bağlı, kalıcı) -----
    def _restore_mkldnn_state(self):
        # GPU'da MKLDNN kullanılmaz — durum sadece CPU modu için geçerli
        if self.device != "cpu":
            return
        state = _load_state()
        if state.get("paddle") == _paddle_version() and state.get("mkldnn_ok") is False:
            self._mkldnn_known_bad = True
            if self.use_mkldnn:
                print("[OCR] Bilinen MKLDNN/PIR uyumsuzluğu (Paddle 3.3.x) — CPU modu kullanılacak.")
                print("[OCR] Kalıcı çözüm: pip install paddlepaddle==3.2.2")

    def _remember_mkldnn(self, ok: bool):
        _save_state({"paddle": _paddle_version(), "mkldnn_ok": bool(ok)})

    # ----- Başlatma -----
    def _build_params(self, enable_mkldnn: bool) -> dict:
        params = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "lang": "en",
            "device": self.device,
            # MKLDNN yalnızca CPU'da anlamlı (GPU'da oneDNN kullanılmaz)
            "enable_mkldnn": bool(enable_mkldnn and self.device == "cpu"),
            # Kısa kenar 736px altına indiğinde PaddleX'in şeridi 4-6 kat büyütmesini önler (~35x hız artışı)
            "text_det_limit_type": "max",
            "text_det_limit_side_len": 960,
        }
        if self.version == "PP-OCRv6":
            det, rec = MODEL_SIZE_PRESETS[self.model_size]
            params["text_detection_model_name"] = det
            params["text_recognition_model_name"] = rec
        elif self.version in ("PP-OCRv4", "PP-OCRv5"):
            params["ocr_version"] = self.version
        return params

    def _ensure_initialized(self, force_cpu: bool = False):
        """PaddleOCR'ı ilk ihtiyaç anında başlat (lazy init)."""
        if self._ocr is not None:
            return

        enable_mkldnn = self.use_mkldnn and not force_cpu and not self._mkldnn_known_bad
        effective_mkldnn = bool(enable_mkldnn and self.device == "cpu")
        if self.device == "gpu":
            _enable_nvidia_dlls()
        t0 = time.time()
        print(f"[OCR] PaddleOCR başlatılıyor ({self.version}/{self.model_size}, "
              f"device={self.device}, mkldnn={effective_mkldnn})...")
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(**self._build_params(enable_mkldnn))
        except Exception as e:
            print(f"[OCR] Init hatası: {e}")
            self._ocr = None
            if self.device == "gpu":
                print("[OCR] GPU başlatılamadı (paddlepaddle-gpu + CUDA gerekli) — CPU'ya dönülüyor.")
                self.device = "cpu"
                return self._ensure_initialized(force_cpu=True)
            if enable_mkldnn:
                return self._ensure_initialized(force_cpu=True)
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(use_angle_cls=False, lang="en", enable_mkldnn=False)
            except Exception as e2:
                print(f"[OCR] Fallback init hatası: {e2}")
                self._ocr = None
                return

        # ÖN-ISINMA: oneDNN/PIR hatası ilk predict'te ortaya çıkar.
        # Oyun ortasında 10 sn'lik yeniden kurulum yerine burada yakalayıp CPU'ya düş.
        try:
            self._ocr.predict(_dummy_image())
            if effective_mkldnn:
                self._remember_mkldnn(True)
        except Exception as e:
            if self.device == "gpu":
                print(f"[OCR] GPU çalıştırma hatası ({str(e)[:110]}) — CPU'ya dönülüyor.")
                print("[OCR] GPU için cuDNN 9 gerekli: pip install nvidia-cudnn-cu12")
                self.device = "cpu"
                self._ocr = None
                return self._ensure_initialized(force_cpu=True)
            if enable_mkldnn:
                print(f"[OCR] MKLDNN hatası ({str(e)[:110]}), CPU moduna geçiliyor...")
                print("[OCR] Kalıcı çözüm: pip install paddlepaddle==3.2.2")
                self._remember_mkldnn(False)
                self._mkldnn_known_bad = True
                self._ocr = None
                return self._ensure_initialized(force_cpu=True)
            print(f"[OCR] Isınma hatası: {e}")

        self.last_init_seconds = time.time() - t0
        print(f"[OCR] PaddleOCR hazır ({self.last_init_seconds:.1f} sn, "
              f"device={self.device}, mkldnn={effective_mkldnn}).")

    def reset(self, version: str = None, use_mkldnn: bool = None, model_size: str = None,
              device: str = None):
        """Motor parametreleri değiştiğinde yeniden başlatmak için."""
        with self._predict_lock:
            if version is not None:
                self.version = version
            if use_mkldnn is not None:
                self.use_mkldnn = use_mkldnn
            if model_size is not None and model_size in MODEL_SIZE_PRESETS:
                self.model_size = model_size
            if device is not None and device in ("cpu", "gpu"):
                self.device = device
            self._ocr = None  # Sonraki kullanımda lazy-init olacak

    def _run_predict(self, image):
        """Ortak predict() çalıştırıcısı: iş parçacığı güvenli + GPU/MKLDNN fallback."""
        if image is None or not hasattr(image, "shape") or image.size == 0:
            return None

        with self._predict_lock:
            with _INIT_LOCK:
                self._ensure_initialized()
            if self._ocr is None:
                return None

            try:
                t0 = time.time()
                result = self._ocr.predict(image)
                self.last_infer_seconds = time.time() - t0
                return result
            except Exception as e:
                if self.device == "gpu":
                    print(f"[OCR] GPU okuma hatası ({str(e)[:110]}) — CPU'ya dönülüyor.")
                    self.device = "cpu"
                    self._ocr = None
                elif self.use_mkldnn and not self._mkldnn_known_bad:
                    print(f"[OCR] MKLDNN hatası ({str(e)[:110]}), standart CPU moduna geçiliyor...")
                    self._remember_mkldnn(False)
                    self._mkldnn_known_bad = True
                    self._ocr = None
                else:
                    print(f"[OCR] Okuma hatası: {e}")
                    return None

                with _INIT_LOCK:
                    self._ensure_initialized(force_cpu=True)
                if self._ocr is None:
                    return None
                try:
                    t0 = time.time()
                    result = self._ocr.predict(image)
                    self.last_infer_seconds = time.time() - t0
                    return result
                except Exception as e2:
                    print(f"[OCR] Yeniden deneme hatası: {e2}")
                    return None

    @staticmethod
    def _poly_to_bbox(poly) -> tuple:
        """Poligon noktalarından (x, y, w, h) dikdörtgeni hesaplar."""
        try:
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            return (x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1))
        except Exception:
            return (0.0, 0.0, 0.0, 0.0)

    @staticmethod
    def _box_to_xywh(box) -> tuple:
        """[x1, y1, x2, y2] veya 4 noktalı kutuyu (x, y, w, h) yapar."""
        try:
            if hasattr(box, "tolist"):
                box = box.tolist()
            if len(box) == 4 and not isinstance(box[0], (list, tuple)):
                x1, y1, x2, y2 = [float(v) for v in box]
                return (x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1))
            return OCREngine._poly_to_bbox(box)
        except Exception:
            return (0.0, 0.0, 0.0, 0.0)

    @classmethod
    def _extract_items(cls, item) -> list:
        """Tek bir PaddleOCR çıktı öğesinden ham (text, score, xywh, poly) listesi çıkarır."""
        extracted = []

        # Format 1 & 2: dict veya .json sarmalayıcısı
        data = None
        if isinstance(item, dict):
            data = item.get("res") if ("res" in item and isinstance(item["res"], dict) and "rec_texts" not in item) else item
        elif hasattr(item, "json") and isinstance(item.json, dict):
            j = item.json
            data = j.get("res") if ("res" in j and isinstance(j["res"], dict) and "rec_texts" not in j) else j

        if isinstance(data, dict):
            texts = data.get("rec_texts") or []
            scores = data.get("rec_scores") or []
            rec_boxes = data.get("rec_boxes")
            polys = data.get("rec_polys")
            if polys is None or (hasattr(polys, "__len__") and len(polys) == 0):
                polys = data.get("dt_polys")

            for i, raw_txt in enumerate(texts):
                txt = str(raw_txt).strip() if raw_txt is not None else ""
                if not txt:
                    continue
                score = float(scores[i]) if i < len(scores) else 1.0
                poly = []
                if polys is not None and i < len(polys):
                    p = polys[i]
                    poly = p.tolist() if hasattr(p, "tolist") else list(p)
                if rec_boxes is not None and i < len(rec_boxes):
                    xywh = cls._box_to_xywh(rec_boxes[i])
                elif poly:
                    xywh = cls._poly_to_bbox(poly)
                else:
                    xywh = (0.0, 0.0, 0.0, 0.0)
                extracted.append((txt, score, xywh, poly))
            return extracted

        # Format 3: klasik liste formatı [[poly, (text, score)], ...]
        if isinstance(item, (list, tuple)):
            for line in item:
                if not isinstance(line, (list, tuple)) or len(line) != 2:
                    continue
                raw_box, text_part = line
                if isinstance(text_part, (tuple, list)) and len(text_part) >= 1:
                    txt = str(text_part[0]).strip()
                    score = float(text_part[1]) if len(text_part) >= 2 else 1.0
                elif isinstance(text_part, str):
                    txt = text_part.strip()
                    score = 1.0
                else:
                    continue
                if not txt:
                    continue
                poly = raw_box.tolist() if hasattr(raw_box, "tolist") else (list(raw_box) if isinstance(raw_box, (list, tuple)) else [])
                xywh = cls._poly_to_bbox(poly) if poly else (0.0, 0.0, 0.0, 0.0)
                extracted.append((txt, score, xywh, poly))
        return extracted

    def read_boxes(self, image, offset_x: int = 0, offset_y: int = 0,
                   scale_x: float = 1.0, scale_y: float = 1.0,
                   min_score: float = 0.55) -> list[dict]:
        """
        Görüntüden konumlu metin kutularını okur.
        scale_x / scale_y: küçültülmüş OCR karesini orijinal koordinata çevirme çarpanı.
        Döner: [{"text": str, "score": float, "bbox": (x, y, w, h), "poly": list, "line_count": 1}, ...]
        """
        result = self._run_predict(image)
        if not result:
            return []

        boxes = []
        for item in result:
            for txt, score, (bx, by, bw, bh), poly in self._extract_items(item):
                if score < min_score or bw <= 0 or bh <= 0:
                    continue
                rx = int(round(offset_x + bx * scale_x))
                ry = int(round(offset_y + by * scale_y))
                rw = max(1, int(round(bw * scale_x)))
                rh = max(1, int(round(bh * scale_y)))
                scaled_poly = [
                    [int(round(offset_x + p[0] * scale_x)), int(round(offset_y + p[1] * scale_y))]
                    for p in poly if isinstance(p, (list, tuple)) and len(p) >= 2
                ]
                boxes.append({
                    "text": txt,
                    "score": score,
                    "bbox": (rx, ry, rw, rh),
                    "poly": scaled_poly,
                    "line_count": 1,
                })
        return boxes

    def read_text(self, image) -> str:
        """
        Görüntüden metin oku. Temiz bir string döndürür.
        PaddleOCR 3.7+ predict çıktısı (dict listesi) ve eski sürümleri destekler.
        """
        result = self._run_predict(image)
        if not result:
            return ""

        texts = []
        for item in result:
            for txt, _score, _xywh, _poly in self._extract_items(item):
                texts.append(txt)
        return " ".join(texts).strip()

    def status(self) -> str:
        """HUD / log için kısa durum bilgisi."""
        if self.device == "gpu":
            mode = "GPU"
        else:
            mode = "CPU" if (self._mkldnn_known_bad or not self.use_mkldnn) else "CPU+MKLDNN"
        return (f"{self.version}/{self.model_size} • {mode} • "
                f"init {self.last_init_seconds:.1f}s • son OCR {self.last_infer_seconds * 1000:.0f}ms")


def merge_nearby_boxes(boxes: list[dict], max_y_gap_ratio: float = 0.55,
                       max_x_gap_ratio: float = 2.5) -> list[dict]:
    """
    Aynı satırda veya alt alta yer alan bitişik cümle/paragraf kutularını birleştirir.
    Farklı sütunlardaki menü öğelerini veya uzak HUD elemanlarını birleştirmez.
    """
    if not boxes:
        return []

    def _copy_box(b):
        return {
            "text": b["text"],
            "score": float(b.get("score", 1.0)),
            "bbox": tuple(b["bbox"]),
            "poly": list(b.get("poly", [])),
            "line_count": int(b.get("line_count", 1)),
        }

    # 1) Aynı satırdaki yakın yatay parçaları birleştir (soldan sağa)
    items = sorted((_copy_box(b) for b in boxes), key=lambda b: (b["bbox"][1], b["bbox"][0]))
    line_merged = []
    for cur in items:
        cx, cy, cw, ch = cur["bbox"]
        cy_mid = cy + ch * 0.5
        merged = False
        for prev in line_merged:
            px, py, pw, ph = prev["bbox"]
            py_mid = py + ph * 0.5
            min_h = min(ch, ph)
            max_h = max(ch, ph)
            if max_h / max(1, min_h) > 1.7:
                continue
            # Dikey merkezler aynı satırda mı?
            if abs(cy_mid - py_mid) > min_h * 0.35:
                continue
            x_gap = cx - (px + pw)
            prev_text = prev["text"].strip()
            cur_text = cur["text"].lstrip()
            cur_starts_lower = bool(cur_text and cur_text[0].islower())
            if not cur_starts_lower:
                if x_gap > min_h * 0.45:
                    continue
                if prev_text.isupper() and cur_text.isupper() and x_gap > min_h * 0.25:
                    continue
            # Geniş boşluk (>1.35*h, örn. [R] tuş ikonu boşluğu) yalnızca cümle bitmemişse ve satır hizası tam ise birleştirilir
            if x_gap > min_h * 1.35:
                if abs(cy_mid - py_mid) > min_h * 0.28 or prev_text.endswith((".", "!", "?")):
                    continue
            if -min_h * 0.4 <= x_gap <= min_h * max_x_gap_ratio:
                nx = min(px, cx)
                ny = min(py, cy)
                nx2 = max(px + pw, cx + cw)
                ny2 = max(py + ph, cy + ch)
                prev["bbox"] = (nx, ny, nx2 - nx, ny2 - ny)
                prev["text"] = f"{prev['text']} {cur['text']}".strip()
                prev["score"] = min(prev["score"], cur["score"])
                merged = True
                break
        if not merged:
            line_merged.append(cur)

    # 2) Alt alta bitişik satırları (çok satırlı altyazı / ipucu / mesaj) birleştir
    line_merged.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    para_merged = []
    for cur in line_merged:
        cx, cy, cw, ch = cur["bbox"]
        c_center = cx + cw * 0.5
        merged = False
        for prev in reversed(para_merged):
            px, py, pw, ph = prev["bbox"]
            line_h = ph / max(1, prev["line_count"])
            min_h = min(ch, line_h)
            max_h = max(ch, line_h)
            if max_h / max(1, min_h) > 1.6:
                continue
            y_gap = cy - (py + ph)
            if y_gap < -min_h * 0.25 or y_gap > min_h * max_y_gap_ratio:
                continue
            # Dikey menü/liste, üst üste buton ipuçları ve cümle sonrası görev satırlarını ayır
            prev_t = prev["text"].strip()
            cur_t = cur["text"].strip()
            prev_words = prev_t.split()
            cur_words = cur_t.split()
            if len(prev_words) <= 2 and len(cur_words) <= 2:
                continue
            if len(prev_words) <= 2 and cur_t and cur_t[0].isupper() and not prev_t.endswith((",", "-")):
                continue
            if prev_t.endswith((".", "!", "?")) and cur_t and cur_t[0].isupper() and y_gap > min_h * 0.35:
                continue
            # Yatay örtüşme veya merkez/sol hizalama kontrolü
            overlap_x = min(px + pw, cx + cw) - max(px, cx)
            p_center = px + pw * 0.5
            same_left = abs(cx - px) <= max(28, min_h * 1.5)
            same_center = abs(c_center - p_center) <= max(40, min_h * 2.0)
            if overlap_x > 0 or same_left or same_center:
                nx = min(px, cx)
                ny = min(py, cy)
                nx2 = max(px + pw, cx + cw)
                ny2 = max(py + ph, cy + ch)
                prev["bbox"] = (nx, ny, nx2 - nx, ny2 - ny)
                prev["text"] = f"{prev['text']} {cur['text']}".strip()
                prev["score"] = min(prev["score"], cur["score"])
                prev["line_count"] += cur["line_count"]
                merged = True
                break
        if not merged:
            para_merged.append(cur)

    return para_merged
