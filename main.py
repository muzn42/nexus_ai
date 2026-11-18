"""
NEXUS AI v2 — Giriş Noktası

Uygulamayı başlatır. Arayüz PySide6 (Qt) tabanlıdır.
Eski Tkinter sürümü için: ui/hud.py (yedek olarak duruyor).
"""
import sys


def main():
    from ui.qt.app import main as qt_main
    return qt_main()


if __name__ == "__main__":
    sys.exit(main())

