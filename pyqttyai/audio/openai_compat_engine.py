"""🌐 Unified engine for OpenAI-compatible cloud Whisper providers."""

import os
import time
import json
import base64
from pathlib import Path

from pyqttyai.core.whisper_config import WhisperConfig


# 🏷️ One source of truth — easy to extend with new providers
PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "whisper-1",
        "env_var": "OPENAI_API_KEY",
        "supports_language": True,
        "supports_prompt": True,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "whisper-large-v3-turbo",
        "env_var": "GROQ_API_KEY",
        "supports_language": True,
        "supports_prompt": True,
    },
    "fireworks": {
        "base_url": "https://audio-turbo.api.fireworks.ai/v1",
        "default_model": "whisper-v3-turbo",
        "env_var": "FIREWORKS_API_KEY",
        "supports_language": True,
        "supports_prompt": False,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        #"default_model": "gemini-3.1-flash-lite-preview",
        "default_model": "gemini-2.5-flash",
        "env_var": "GOOGLE_API_KEY",
        "supports_language": True,
        "supports_prompt": True,
        "complement_prompt": (
            "Transcribe this audio ignoring the noise."
            "Give me with a complete JSON, like Whisper verbose_json,"
            "with every possible the fields."
        ),
    },
}

# ── Shape adapters (mirror faster-whisper) ──────────────────

class _Segment:
    __slots__ = ("text", "start", "end")
    def __init__(self, text, start=0.0, end=0.0):
        self.text = text
        self.start = start
        self.end = end


class _Info:
    __slots__ = ("language", "language_probability",
                 "all_language_probs", "duration")
    def __init__(self, language, duration):
        self.language = language or "en"
        self.language_probability = 1.0
        self.all_language_probs = None
        self.duration = duration or 0.0


# ── The engine ──────────────────────────────────────────────

class OpenAICompatibleEngine:
    """🌐 OpenAI-compatible Whisper client (Groq, OpenAI, Fireworks, …)."""

    def __init__(self, config: WhisperConfig, provider: str | None = None):
        self.config = config
        # 🎯 Provider may come from config.backend or be passed explicitly
        provider = provider or getattr(config, "backend", None) or "groq"
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown OpenAI-compatible provider: {provider!r}. "
                f"Available: {list(PROVIDERS)}"
            )
        self._provider = provider
        self._spec = PROVIDERS[provider]
        self._client = None
        self._model_id = self._spec["default_model"] or config.model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def env_var(self) -> str:
        return self._spec["env_var"]

    def load(self) -> float:
        from openai import OpenAI, AuthenticationError, APIError

        api_key = os.environ.get(self._spec["env_var"]) or \
                  getattr(self.config, "api_key", "") or ""
        if not api_key:
            raise RuntimeError(
                f"Missing {self._spec['env_var']} for provider {self._provider!r}"
            )

        t0 = time.time()
        self._client = OpenAI(
            api_key=api_key,
            base_url=self._spec["base_url"],
            timeout=30,
        )
        # 🩺 Optional liveness check — comment out if you want lazy connection
        try:
            _ = self._client.models.list()
        except AuthenticationError as e:
            raise RuntimeError(f"Invalid {self._provider} API key: {e}") from e
        except APIError as e:
            print(RuntimeError(f"{self._provider} API error: {e}"))
        return time.time() - t0

    def gtranscribe(self, params: dict) -> dict:
        """Returns Whisper JSON as a converted dict from Gemini responsse."""
        audio_b64 = base64.b64encode(params["file"][1]).decode('utf-8')
        response = self._client.chat.completions.create(
            model="gemini-3.1-flash-lite-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": params["prompt"]},
                        {"type": "input_audio", "input_audio": {
                            "data": audio_b64,
                            "format": "wav"
                        }}
                    ]
                }
            ]
        )
        print(response)
        content = response.choices[0].message.content
        try:
            return json.loads(
                content[content.index('{'):content.rindex('}') + 1])
        except Exception as e:
            print(e, response)
            return {'text': response.choices[0].message.content}

    def transcribe(self, wav_path: str, **kwargs):
        """Returns (segments, info) — same shape as faster-whisper."""
        params = {
            "model": self._model_id,
            "response_format": "verbose_json",
        }

        language = kwargs.get("language")
        prompt = kwargs.get("initial_prompt") or kwargs.get("prompt")
        temperature = kwargs.get("temperature")

        if language and self._spec.get("supports_language", True):
            params["language"] = language
        if prompt and self._spec.get("supports_prompt", True):
            params["prompt"] = (
                self._spec.get("complement_prompt", ""))+ prompt
        if temperature is not None:
            params["temperature"] = temperature

        with open(wav_path, "rb") as f:
            params["file"] = (Path(wav_path).name, f.read())

        print(self.provider, params)
        if self._provider == "gemini":
            resp = self.gtranscribe(params)
            text = resp.get("text", "").strip()
            duration = resp.get("duration", 0.0)
            lang = resp.get("language", language) or "en"
        else:
            resp = self._client.audio.transcriptions.create(**params)
            text = (getattr(resp, "text", "") or "").strip()
            duration = getattr(resp, "duration", 0.0) or 0.0
            lang = getattr(resp, "language", language) or language or "en"

        segments = (_Segment(text, 0.0, duration),)
        info = _Info(lang, duration)
        print(segments, info)
        return segments, info

    def unload(self) -> None:
        self._client = None
