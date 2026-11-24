# -*- mode: python ; coding: utf-8 -*-
# NEXUS AI — PyInstaller one-folder spec.  Doğrudan değil, packaging/build.ps1 üzerinden çalıştırın.
#
# Neden one-folder (one-file değil)?
#   * Paket ~3 GB (paddlepaddle-gpu + CUDA/cuDNN DLL'leri). One-file her açılışta bunu
#     %TEMP%'e açar: 30-60 sn bekleme + her çalıştırmada 3 GB disk yazımı.
#   * One-folder anında açılır, antivirüs tarafından daha az şüpheli görülür ve
#     yazılabilir config/ + data/ klasörleri exe'nin yanında durabilir.
import glob
import importlib.metadata as md
import os
import re
import sys

from PyInstaller.utils.hooks import (collect_data_files, collect_dynamic_libs,
                                     collect_submodules, copy_metadata)

REPO = os.path.abspath(os.path.join(SPECPATH, ".."))
SITE = next(p for p in sys.path if p.lower().endswith("site-packages") and
            os.path.isdir(os.path.join(p, "paddle")))
MODELS_SRC = os.environ.get("NEXUS_MODELS_SRC",
                            os.path.join(os.path.expanduser("~"), ".paddlex", "official_models"))
BUNDLED_MODELS = [f"PP-OCRv6_{size}_{kind}" for size in ("tiny", "small", "medium")
                  for kind in ("det", "rec")]

# Paketlenmeyecek ağır/kullanılmayan paketler.
#  * torch: paddle ile aynı süreçte WinError 127 (shm.dll) çakışmasının kaynağı; modelscope onu
#    yalnızca find_spec('torch') bulursa yüklüyor → dışarıda bırakmak çakışmayı tamamen kaldırır.
#  * argostranslate (+stanza/spacy/ctranslate2/torch): çevrimdışı Argos motoru; >2 GB.
#    Paketli sürümde Argos seçilirse uygulama "[Hata] argostranslate paketi yüklü değil" der.
#  * rapidocr/onnxruntime: projede kullanılmıyor (AGENTS.md TODO).
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "transformers", "sentence_transformers",
    "argostranslate", "argos_translate_files", "stanza", "spacy", "thinc", "ctranslate2",
    "rapidocr", "rapidocr_onnxruntime", "onnxruntime", "tensorflow", "keras",
    "IPython", "jupyter", "notebook", "matplotlib", "tkinter", "customtkinter",
    "pytest", "sphinx",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
]
_EXCLUDED_DISTS = {"torch", "torchvision", "torchaudio", "transformers", "sentence-transformers",
                   "argostranslate", "stanza", "spacy", "ctranslate2", "onnxruntime",
                   "onnxruntime-gpu", "rapidocr", "tensorflow", "matplotlib"}


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _installed(dist):
    try:
        md.version(dist)
        return True
    except md.PackageNotFoundError:
        return False


# --- Paket meta verisi: PaddleX bağımlılık kontrolü (paddlex/utils/deps.py) ve
#     ocr_engine._paddle_has_cuda() importlib.metadata kullanır.
meta_dists = {"paddlex", "paddleocr", "paddlepaddle-gpu", "paddlepaddle"}
for parent in ("paddlex", "paddleocr"):
    for spec in md.requires(parent) or []:
        m = re.match(r"\s*([A-Za-z0-9_.\-]+)", spec)
        if m:
            meta_dists.add(m.group(1))
datas = []
for dist in sorted(meta_dists, key=_norm):
    if _norm(dist) in _EXCLUDED_DISTS or not _installed(dist):
        continue
    try:
        datas += copy_metadata(dist)
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] metadata atlandı: {dist} ({exc})")

# --- Paket veri dosyaları (pipeline YAML'ları, model config'leri)
datas += collect_data_files("paddlex")
datas += collect_data_files("paddleocr")
datas += collect_data_files("paddle", excludes=["**/tests/**", "**/*.h", "**/include/**"])

# --- Hazır OCR modelleri → <_internal>/models/<ad>   (ocr_engine._bundled_model_dir)
for name in BUNDLED_MODELS:
    src = os.path.join(MODELS_SRC, name)
    if not os.path.isfile(os.path.join(src, "inference.yml")):
        raise SystemExit(f"[spec] Model eksik: {src}  (önce python main.py ile bir kez indirin)")
    for fn in os.listdir(src):
        if os.path.isfile(os.path.join(src, fn)):
            datas.append((os.path.join(src, fn), f"models/{name}"))

# --- CUDA / cuDNN DLL'leri (pip nvidia-*-cu12) → <_internal>/nvidia/<pkg>/bin
binaries = collect_dynamic_libs("paddle")
for dll in glob.glob(os.path.join(SITE, "nvidia", "*", "bin", "*.dll")):
    pkg = os.path.basename(os.path.dirname(os.path.dirname(dll)))
    binaries.append((dll, f"nvidia/{pkg}/bin"))

hiddenimports = []
hiddenimports += collect_submodules("paddleocr")
hiddenimports += collect_submodules(
    "paddlex", filter=lambda n: not n.startswith(("paddlex.repo_manager", "paddlex.repo_apis",
                                                  "paddlex.modules")))
hiddenimports += collect_submodules("paddle", filter=lambda n: ".tests" not in n)
hiddenimports += [
    "ui.qt.app", "core.button_icons",
    "keyboard", "openai", "deep_translator", "google.generativeai", "requests", "PIL.ImageGrab",
    "cv2", "numpy", "pyclipper", "shapely", "sqlite3",
]

a = Analysis(
    [os.path.join(REPO, "main.py")],
    pathex=[REPO],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[os.path.join(SPECPATH, "rthook_nexus.py")],
    excludes=EXCLUDES,
    noarchive=False,
)
# Bazı hook'lar dışlanan paketlerin meta verisini (ör. torch-*.dist-info) yine ekliyor; bu,
# PaddleX'in is_dep_available('torch') kontrolünü yanıltır → temizle.
_bad_meta = tuple(f"{d.replace('-', '_')}-" for d in _EXCLUDED_DISTS)
a.datas = [d for d in a.datas
           if not (d[0].split("/")[0].split("\\")[0].lower().startswith(_bad_meta)
                   and ".dist-info" in d[0])]
pyz = PYZ(a.pure)

ICON = os.path.join(REPO, "assets", "logo.ico")
common = dict(debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
              icon=ICON if os.path.isfile(ICON) else None)

exe_gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NEXUS AI",
              console=False, **common)
# Sorun giderme için aynı _internal'ı paylaşan konsollu ikinci exe (çıktıyı doğrudan gösterir).
exe_dbg = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NEXUS AI (Konsol)",
              console=True, **common)

coll = COLLECT(exe_gui, exe_dbg, a.binaries, a.datas, strip=False, upx=False, name="NEXUS AI")
