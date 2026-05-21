import base64
import json
import os
import time
from openai import OpenAI


class OpenAICompatibleEngine:
    """🌐 Works with OpenAI, Groq, and any OpenAI-compatible Whisper endpoint."""

    # Preset configurations for known providers
    PROVIDERS = {
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "default_model": "whisper-1",
            "env_var": "OPENAI_API_KEY",
        },
        "groq": {
            "base_url": "https://api.groq.com/openai/v1",
            "default_model": "whisper-large-v3-turbo",
            "env_var": "GROQ_API_KEY",
        },
        "fireworks": {
            "base_url": "https://audio-turbo.api.fireworks.ai/v1",
            "default_model": "whisper-v3-turbo",
            "env_var": "FIREWORKS_API_KEY",
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "default_model": "gemini-3.1-flash-lite-preview",
            "env_var": "GOOGLE_API_KEY",
        },
    }

    def __init__(self, config):
        self.config = config
        provider = self.PROVIDERS.get(config.backend)
        if provider is None:
            raise ValueError(f"Unknown OpenAI-compatible provider: {config.backend}")

        self.api_key = os.getenv(provider["env_var"])
        self.base_url = provider["base_url"]
        self.model = config.model or provider["default_model"]

    def load(self) -> None:
        if not self.api_key:
            raise RuntimeError(f"Missing API key for {self.config.backend}")
        # 🩺 Optional: ping the endpoint to verify creds upfront
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30)

    def transcribe(self, wav_path: str) -> dict:
        try:
            with open(wav_path, "rb") as f:
                r = self._client.audio.transcriptions.create(
                    model=self.model,
                    file=f,
                    response_format="verbose_json",
                    language="pt",
                )
            # Both Groq and OpenAI return the same shape
            return {
                "text": (r.text or "").strip(),
                "language": getattr(r, "language", "?"),
                "language_probability": 1.0,
                "duration": getattr(r, "duration", 0.0),
            }
        except Exception as e:
            return {'error': str(e)}

    def gtranscribe(self, wav_path: str) -> str:
        with open(wav_path, 'rb') as fd:
            audio_b64 = base64.b64encode(fd.read()).decode('utf-8')
        response = self._client.chat.completions.create(
            model="gemini-3.1-flash-lite-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcreva este áudio ignorando ruídos. Me entregue um JSON completo tal como o Whisper com todos os campos."},
                        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}}
                    ]
                }
            ]
        )
        #print('_' * 100)
        #print(response)
        #print('‾' * 100)
        content = response.choices[0].message.content
        try:
            return json.loads(content[content.index('{'):content.rindex('}') + 1])
        except Exception:
            return {'content': response.choices[0].message.content}

    def unload(self) -> None:
        self._client = None

if __name__ == "__main__":
    with open('../../.env', encoding="utf-8") as fd:
        for line in fd:
            var, value = line.split('=')
            os.environ[var.strip()] = value.strip()
    #main()

    file_path = '/tmp/audio_com_ruído.wav'

    class groq_config:
        backend = "groq"
        model = ""

    class openai_config:
        backend = "openai"
        model = ""

    class fireworks_config:
        backend = "fireworks"
        model = ""

    class gemini_config:
        backend = "gemini"
        model = ""

    for i in range(5):
        print(f"________  Loop {i+1} __________")

        groq_engine = OpenAICompatibleEngine(groq_config)
        t0 = time.time()
        groq_engine.load()
        t1 = time.time()
        info = groq_engine.transcribe(file_path)
        t2 = time.time()
        print(f"Groq: {t1 - t0}s/{t2 - t1}s", info)
        groq_engine.unload()

        print('-' * 100)

        openai_engine = OpenAICompatibleEngine(openai_config)
        t0 = time.time()
        openai_engine.load()
        t1 = time.time()
        info = openai_engine.transcribe(file_path)
        t2 = time.time()
        print(f"OpenAI: {t1 - t0}s/{t2 - t1}s", info)
        openai_engine.unload()

        print('-' * 100)

        fireworks_engine = OpenAICompatibleEngine(fireworks_config)
        t0 = time.time()
        fireworks_engine.load()
        t1 = time.time()
        info = fireworks_engine.transcribe(file_path)
        t2 = time.time()
        print(f"Fireworks: {t1 - t0}s/{t2 - t1}s", info)
        fireworks_engine.unload()

        print('-' * 100)

        gemini_engine = OpenAICompatibleEngine(gemini_config)
        t0 = time.time()
        gemini_engine.load()
        t1 = time.time()
        info = gemini_engine.gtranscribe(file_path)
        t2 = time.time()
        print(f"Gemini: {t1 - t0}s/{t2 - t1}s", info)
        gemini_engine.unload()
