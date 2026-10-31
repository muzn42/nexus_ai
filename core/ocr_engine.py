"""
NEXUS AI v2 — OCR Motor Modülü
PaddleOCR wrapper ile temiz metin çıkarma.
"""
import os

os.environ["OPENCV_LOG_LEVEL"] = "SILENT"


class OCREngine:
    """
    PaddleOCR'ı saran temiz bir arayüz.
    Lazy-init: İlk kullanımda başlatılır.
    """

    def __init__(self, version: str = "PP-OCRv5", use_mkldnn: bool = True):
        self.version = version
        self.use_mkldnn = use_mkldnn
        self._ocr = None

    def _ensure_initialized(self):
        """PaddleOCR'ı ilk ihtiyaç anında başlat (lazy init)."""
        if self._ocr is not None:
            return

        print(f"[OCR] PaddleOCR başlatılıyor ({self.version})...")
        try:
            from paddleocr import PaddleOCR

            params = {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "lang": "en",
                "enable_mkldnn": self.use_mkldnn,
            }
            if self.version == "PP-OCRv4":
                params["ocr_version"] = "PP-OCRv4"

            self._ocr = PaddleOCR(**params)
            print("[OCR] PaddleOCR hazır.")
        except Exception as e:
            print(f"[OCR] Init hatası: {e}")
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(use_angle_cls=False, lang="en")
            except Exception as e2:
                print(f"[OCR] Fallback init hatası: {e2}")
                self._ocr = None

    def reset(self, version: str = None, use_mkldnn: bool = None):
        """Motor parametreleri değiştiğinde yeniden başlatmak için."""
        if version is not None:
            self.version = version
        if use_mkldnn is not None:
            self.use_mkldnn = use_mkldnn
        self._ocr = None  # Sonraki kullanımda lazy-init olacak

    def read_text(self, image) -> str:
        """
        Görüntüden metin oku. Temiz bir string döndürür.
        PaddleOCR'ın karmaşık çıktı formatlarını tek bir noktada çözümler.
        """
        self._ensure_initialized()
        if self._ocr is None:
            return ""

        try:
            result = self._ocr.predict(image)
            if not result:
                return ""

            texts = []

            for item in result:
                # Format 1: hasattr(item, 'json') — PaddleOCR v3+ nesne formatı
                if hasattr(item, 'json'):
                    json_data = item.json
                    if 'res' in json_data and 'rec_texts' in json_data['res']:
                        rec_texts = json_data['res']['rec_texts']
                        if rec_texts:
                            texts.extend(rec_texts)
                    continue

                # Format 2: list of [bbox, (text, confidence)] — Eski format
                if isinstance(item, list):
                    for line in item:
                        if isinstance(line, (list, tuple)) and len(line) == 2:
                            text_part = line[1]
                            if isinstance(text_part, tuple) and len(text_part) >= 1:
                                texts.append(str(text_part[0]))

            return " ".join(texts).strip()

        except Exception as e:
            print(f"[OCR] Okuma hatası: {e}")
            return ""
