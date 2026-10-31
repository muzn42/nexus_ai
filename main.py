"""
NEXUS AI v2 — Giriş Noktası
Uygulamayı başlatır. Geri dönmek için main_v1.py'yi çalıştırabilirsiniz.
"""
from ui.hud import TranslationApp


def main():
    app = TranslationApp()
    app.start()


if __name__ == "__main__":
    main()
