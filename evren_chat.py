"""
EVREN AI — Komut Satırı İnteraktif Sohbet (CLI)
Kullanım:
  python evren_chat.py [model_adı]
Örnek:
  python evren_chat.py deepseek-v4.1-flash
  python evren_chat.py glm-4.5
"""
import os
import sys
import json
import time

try:
    from openai import OpenAI
except ImportError:
    print("Lütfen openai kütüphanesini yükleyin: pip install openai")
    sys.exit(1)

SETTINGS_FILE = r"d:\nexus2-anti\config\settings.json"
BASE_URL = "https://evren-llmapi.ssyz.org.tr/v1"


def get_key():
    # 1. Ortam değişkeni
    k = os.environ.get("EVREN_API_KEY", "").strip()
    if k:
        return k
    # 2. settings.json
    if os.path.exists(SETTINGS_FILE):
        try:
            d = json.load(open(SETTINGS_FILE, "r", encoding="utf-8"))
            if d.get("evren_api_key"):
                return d["evren_api_key"]
        except Exception:
            pass
    # 3. Kullanıcıdan iste
    print("=" * 60)
    print("EVREN AI API Anahtarı Bulunamadı!")
    print("Anahtarınızı https://evren.ssyz.org.tr/api-keys sayfasından alabilirsiniz.")
    print("=" * 60)
    val = input("Lütfen EVREN API Anahtarınızı (evren_llm_...) girin: ").strip()
    if val:
        try:
            d = {}
            if os.path.exists(SETTINGS_FILE):
                d = json.load(open(SETTINGS_FILE, "r", encoding="utf-8"))
            d["evren_api_key"] = val
            json.dump(d, open(SETTINGS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            print("[✓] Anahtar config/settings.json dosyasına kaydedildi.\n")
        except Exception as e:
            print(f"[!] Kaydedilemedi: {e}")
        return val
    sys.exit(1)


def main():
    api_key = get_key()
    model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-v4.1-flash"

    # Kullanım şartlarını onayla
    try:
        from core.evren_client import EvrenClient
        client_helper = EvrenClient(api_key)
        terms_res = client_helper.check_and_accept_terms()
        if terms_res.get("success"):
            action = terms_res.get("action")
            if action == "accepted":
                print(f"[✓] EVREN AI kullanım şartları otomatik onaylandı (v{terms_res.get('version')}).")
        else:
            print(f"[!] Şart sorgusu uyarısı: {terms_res}")
    except Exception as e:
        print(f"[!] Şart kontrolü atlandı: {e}")

    client = OpenAI(
        base_url=BASE_URL,
        api_key=api_key,
        default_headers={"X-API-Key": api_key}
    )

    print("=" * 60)
    print(f"🇹🇷 EVREN AI Sohbet Başlatıldı")
    print(f"Model : {model}")
    print(f"Çıkış : 'exit' veya 'q' yazıp Enter'a basın.")
    print("=" * 60 + "\n")

    messages = [
        {"role": "system", "content": "Sen yardımsever, akıllı ve samimi bir yapay zeka asistanısın. Türkçe yanıt ver."}
    ]

    while True:
        try:
            user_msg = input("\nSiz: ").strip()
            if not user_msg:
                continue
            if user_msg.lower() in ("exit", "quit", "q"):
                print("Görüşmek üzere!")
                break

            messages.append({"role": "user", "content": user_msg})
            print(f"\n{model}: ", end="", flush=True)

            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
                stream=True
            )

            full_reply = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # Düşünme içeriği
                reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if reasoning:
                    print(f"\033[90m{reasoning}\033[0m", end="", flush=True)
                if delta.content:
                    print(delta.content, end="", flush=True)
                    full_reply.append(delta.content)

            print()
            messages.append({"role": "assistant", "content": "".join(full_reply)})

        except KeyboardInterrupt:
            print("\nSohbet sonlandırıldı.")
            break
        except Exception as e:
            print(f"\n[Hata]: {e}")


if __name__ == "__main__":
    main()

