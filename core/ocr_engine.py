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
import time

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
    """Ön-ısınma için boş bir görüntü (numpy tembel import)."""
    import numpy as np
    return np.full((64, 320, 3), 255, dtype=np.uint8)


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

    def __init__(self, version: str = "PP-OCRv5", use_mkldnn: bool = True,
                 model_size: str = DEFAULT_MODEL_SIZE, device: str = "cpu"):
        self.version = version
        self.use_mkldnn = use_mkldnn
        self.model_size = model_size if model_size in MODEL_SIZE_PRESETS else DEFAULT_MODEL_SIZE
        self.device = device if device in ("cpu", "gpu") else "cpu"
        self._ocr = None
        self._mkldnn_known_bad = False
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
        if self.device == "gpu":
            _enable_nvidia_dlls()
        t0 = time.time()
        print(f"[OCR] PaddleOCR başlatılıyor ({self.version}/{self.model_size}, "
              f"mkldnn={enable_mkldnn})...")
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
            if enable_mkldnn:
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
              f"mkldnn={enable_mkldnn}).")

    def reset(self, version: str = None, use_mkldnn: bool = None, model_size: str = None,
              device: str = None):
        """Motor parametreleri değiştiğinde yeniden başlatmak için."""
        if version is not None:
            self.version = version
        if use_mkldnn is not None:
            self.use_mkldnn = use_mkldnn
        if model_size is not None and model_size in MODEL_SIZE_PRESETS:
            self.model_size = model_size
        if device is not None and device in ("cpu", "gpu"):
            self.device = device
        self._ocr = None  # Sonraki kullanımda lazy-init olacak

    def read_text(self, image) -> str:
        """
        Görüntüden metin oku. Temiz bir string döndürür.
        PaddleOCR 3.7+ predict çıktısı (dict listesi) ve eski sürümleri destekler.
        """
        if image is None or not hasattr(image, "shape") or image.size == 0:
            return ""

        self._ensure_initialized()
        if self._ocr is None:
            return ""

        try:
            t0 = time.time()
            result = self._ocr.predict(image)
            self.last_infer_seconds = time.time() - t0
        except Exception as e:
            # GPU veya MKLDNN kaynaklı çalışma hatası: CPU'ya düşüp bir kez yeniden dene
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
                return ""
            self._ensure_initialized(force_cpu=True)
            if self._ocr is None:
                return ""
            try:
                t0 = time.time()
                result = self._ocr.predict(image)
                self.last_infer_seconds = time.time() - t0
            except Exception as e2:
                print(f"[OCR] Yeniden deneme hatası: {e2}")
                return ""

        if not result:
            return ""

        texts = []

        for item in result:
            # Format 1: PaddleOCR 3.7+ güncel format (dict içinde 'rec_texts')
            if isinstance(item, dict):
                rec = item.get("rec_texts")
                if rec and isinstance(rec, (list, tuple)):
                    texts.extend(str(t) for t in rec if t)
                elif "res" in item and isinstance(item["res"], dict):
                    sub_rec = item["res"].get("rec_texts")
                    if sub_rec and isinstance(sub_rec, (list, tuple)):
                        texts.extend(str(t) for t in sub_rec if t)
                continue

            # Format 2: hasattr(item, 'json') — PaddleOCR v3 nesne formatı
            if hasattr(item, "json"):
                json_data = item.json
                if isinstance(json_data, dict):
                    if "rec_texts" in json_data and isinstance(json_data["rec_texts"], (list, tuple)):
                        texts.extend(str(t) for t in json_data["rec_texts"] if t)
                    elif "res" in json_data and isinstance(json_data["res"], dict):
                        sub_rec = json_data["res"].get("rec_texts")
                        if sub_rec and isinstance(sub_rec, (list, tuple)):
                            texts.extend(str(t) for t in sub_rec if t)
                continue

            # Format 3: list of [bbox, (text, confidence)] — Eski v2 formatı
            if isinstance(item, (list, tuple)):
                for line in item:
                    if isinstance(line, (list, tuple)) and len(line) == 2:
                        text_part = line[1]
                        if isinstance(text_part, (tuple, list)) and len(text_part) >= 1:
                            texts.append(str(text_part[0]))
                        elif isinstance(text_part, str):
                            texts.append(text_part)

        return " ".join(texts).strip()

    def status(self) -> str:
        """HUD / log için kısa durum bilgisi."""
        if self.device == "gpu":
            mode = "GPU"
        else:
            mode = "CPU" if (self._mkldnn_known_bad or not self.use_mkldnn) else "CPU+MKLDNN"
        return (f"{self.version}/{self.model_size} • {mode} • "
                f"init {self.last_init_seconds:.1f}s • son OCR {self.last_infer_seconds * 1000:.0f}ms")
