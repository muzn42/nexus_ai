# PyInstaller runtime hook — NEXUS AI paketli sürümü için çalışma ortamı hazırlığı.
# main.py'den ÖNCE çalışır; uygulama kodunu değiştirmeden:
#   1) Penceresiz exe'de (console=False) stdout/stderr None olur → logs/nexus.log'a yönlendirilir.
#   2) PaddleX'in açılıştaki model sunucusu bağlantı kontrolünü kapatır (modeller pakette).
#   3) Paket içindeki nvidia/*/bin ve paddle/libs DLL klasörlerini arama yoluna ekler
#      (paddlepaddle-gpu cuDNN/cuBLAS'ı LoadLibrary ile PATH üzerinden arar).
import os
import sys

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _add_dll_dirs():
    import glob
    root = getattr(sys, "_MEIPASS", "")
    if not root:
        return
    dirs = glob.glob(os.path.join(root, "nvidia", "*", "bin"))
    dirs.append(os.path.join(root, "paddle", "libs"))
    path = os.environ.get("PATH", "")
    for d in dirs:
        if not os.path.isdir(d):
            continue
        if d not in path:
            path = d + os.pathsep + path
        try:
            os.add_dll_directory(d)
        except Exception:
            pass
    os.environ["PATH"] = path


def _redirect_output():
    try:
        from core.config_manager import LOG_DIR
    except Exception:
        LOG_DIR = os.path.join(os.path.dirname(sys.executable), "logs")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, "nexus.log")
        if os.path.exists(log_path):
            prev = log_path + ".1"
            try:
                if os.path.exists(prev):
                    os.remove(prev)
                os.replace(log_path, prev)
            except OSError:
                pass
        stream = open(log_path, "a", encoding="utf-8", buffering=1, errors="replace")
    except Exception:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    # Konsollu exe'de (veya boruya yönlendirildiğinde) stdio yerel kod sayfasıyla (cp125x) açılır;
    # Türkçe karakterli print() UnicodeEncodeError fırlatıp OCR başlatmayı yarıda kesebiliyor.
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass


_add_dll_dirs()
_redirect_output()
