"""
EVREN AI (SSYZ) — İstemci ve Yardımcı Araçlar
Base URL: https://evren-llmapi.ssyz.org.tr/v1
OpenAI SDK uyumlu çağrılar, şart onayı ve model listeleme.
"""
import requests
from openai import OpenAI

BASE_URL = "https://evren-llmapi.ssyz.org.tr/v1"


class EvrenClient:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        self.openai_client = OpenAI(
            base_url=BASE_URL,
            api_key=self.api_key,
            default_headers={"X-API-Key": self.api_key}
        )

    def check_and_accept_terms(self) -> dict:
        """
        EVREN AI kullanım şartlarını sorgular ve onaylanmamışsa onaylar.
        (403 terms_not_accepted hatasını önler)
        """
        try:
            status_res = requests.get(f"{BASE_URL}/terms/status", headers=self.headers, timeout=10)
            if status_res.status_code == 200:
                data = status_res.json()
                version = data.get("current_version") or data.get("version")
                accepted = data.get("accepted", False)
                if not accepted and version:
                    accept_res = requests.post(
                        f"{BASE_URL}/terms/accept",
                        headers=self.headers,
                        json={"version": version},
                        timeout=10
                    )
                    return {"success": True, "action": "accepted", "version": version, "response": accept_res.text}
                return {"success": True, "action": "already_accepted", "version": version}
            return {"success": False, "status_code": status_res.status_code, "text": status_res.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_models(self) -> list:
        """Kullanılabilir EVREN AI modellerini listeler."""
        try:
            res = requests.get(f"{BASE_URL}/models", headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return [m.get("id") or m.get("name") for m in data.get("data", [])]
            return []
        except Exception:
            return ["deepseek-v4.1-flash", "deepseek-v4.1", "glm-4.5", "zai/glm-4.5-fp8"]

    def chat_stream(self, prompt: str, model: str = "deepseek-v4.1-flash",
                    system_prompt: str = "Sen yardımsever ve uzman bir yapay zeka asistanısın."):
        """
        SSE akışı ile modelden yanıt alır (generator).
        Reasoning modellerinde (DeepSeek/Qwen) düşünme ve nihai yanıtı ayrıştırır.
        """
        stream = self.openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4096,
            stream=True
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # Düşünme içeriği (varsa)
            reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ("reasoning", reasoning)
            # Normal yanıt içeriği
            if delta.content:
                yield ("content", delta.content)


if __name__ == "__main__":
    import sys
    print("EVREN AI Yardımcı Modülü Hazır.")
    print(f"Hedef API: {BASE_URL}")

