"""
NEXUS AI v2 — OCR Hız Ölçüm Aracı (CPU / GPU + model boyutları)

Kullanım:
    python tools/bench_ocr.py                 # CPU, tüm model boyutları
    python tools/bench_ocr.py --device gpu    # GPU (paddlepaddle-gpu kurulu olmalı)
    python tools/bench_ocr.py --runs 5        # tekrar sayısı

Not: MKLDNN (oneDNN) açıkken Paddle 3.3.x'te
"ConvertPirAttribute2RuntimeAttribute not support" hatası alınıyorsa
çözüm: pip install paddlepaddle==3.2.2  (veya GPU paketi)
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core.ocr_engine import _enable_nvidia_dlls

# paddleocr, paddle'dan ÖNCE import edilmeli: ters sırada bu ortamda
# torch/modelscope DLL çakışması (WinError 127 shm.dll) oluşabiliyor.
from paddleocr import PaddleOCR  # noqa: E402
import paddle  # noqa: E402

SIZES = ["tiny", "small", "medium"]


def make_subtitle_image(w=960, h=120):
    """Oyun altyazısı benzeri sentetik görüntü (siyah zeminde beyaz yazı)."""
    import cv2
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.putText(img, "We ride at dawn, Arthur. Dutch is waiting.", (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return img


def bench(size, mkldnn, device, runs):
    img = make_subtitle_image()
    params = dict(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        lang="en",
        enable_mkldnn=mkldnn,
        device=device,
    )
    if size:
        params["text_detection_model_name"] = f"PP-OCRv6_{size}_det"
        params["text_recognition_model_name"] = f"PP-OCRv6_{size}_rec"

    t0 = time.time()
    try:
        ocr = PaddleOCR(**params)
        init = time.time() - t0
        t1 = time.time()
        ocr.predict(img)                       # ilk tahmin (grafik derleme dahil)
        first = time.time() - t1
        times = []
        for _ in range(runs):
            t = time.time()
            ocr.predict(img)
            times.append((time.time() - t) * 1000)
    except Exception as e:
        return f"{size or 'varsayılan':<8} mkldnn={str(mkldnn):<5} {device:<4} HATA: {str(e)[:60]}"

    avg_ms = sum(times) / len(times)
    best = min(times)
    return (f"{size or 'varsayılan':<8} mkldnn={str(mkldnn):<5} {device:<4} "
            f"init={init:5.2f}s  ilk={first:5.2f}s  ort={avg_ms:7.1f}ms  en_iyi={best:7.1f}ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cpu", choices=["cpu", "gpu"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--sizes", default=",".join(SIZES))
    args = ap.parse_args()

    if args.device == "gpu":
        _enable_nvidia_dlls()  # pip ile kurulan cuDNN/cuBLAS DLL'lerini PATH'e ekle

    import paddle
    print(f"paddle {paddle.__version__} • cuda_derlenmiş={paddle.device.is_compiled_with_cuda()} • "
          f"device={args.device}", flush=True)
    print("-" * 78)

    for size in [s.strip() for s in args.sizes.split(",") if s.strip()]:
        for mkldnn in ([True, False] if args.device == "cpu" else [False]):
            print(bench(size, mkldnn, args.device, args.runs), flush=True)

    if args.device == "gpu":
        try:
            print(f"\nkullanılan GPU: {paddle.device.get_device()}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
