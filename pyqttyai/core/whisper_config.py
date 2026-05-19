"""Whisper configuration: dataclass, persistence, and constants."""

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import ClassVar

from pyqttyai.core.paths import config_dir
from pyqttyai.core.whisper_languages import (
    WHISPER_LANGUAGES, AUTO_DETECT,
)

# ═══════════════════════════════════════════════════════════
#  Available options (single source of truth)
# ═══════════════════════════════════════════════════════════

WHISPER_MODELS: list[str] = [
    "tiny.en", "tiny", "base.en", "base",
    "small.en", "small", "medium.en", "medium",
    "large-v1", "large-v2", "large-v3", "large",
    "distil-large-v2", "distil-medium.en", "distil-small.en",
    "distil-large-v3", "distil-large-v3.5",
    "large-v3-turbo", "turbo",
]

# 🆕 Six device options — first 3 = faster-whisper, last 3 = OpenVINO
WHISPER_DEVICES: list[str] = [
    "auto (faster)",   # 🎯 default
    "cpu (faster)",
    "cuda (faster)",
    "auto (OpenVINO)",
    "cpu (OpenVINO)",
    "gpu (OpenVINO)",   # 🎮 Intel iGPU
    "auto (OpenVINO-GenAI)",
    "cpu (OpenVINO-GenAI)",
    "gpu (OpenVINO-GenAI)",   # 🎮 Intel iGPU
]

WHISPER_COMPUTE_TYPES: list[str] = [
    "int8", "int8_float32", "int8_float16",   # 🎯 default
    "int8_bfloat16", "int16", "float16",
    "bfloat16", "float32",
    # 🆕 OpenVINO-specific
    "FP32", "FP16", "INT8", "INT4"
]

# 🧠 Compatibility hints: which compute types are sensible per device
COMPUTE_TYPE_HINTS: dict[str, set[str]] = {
    "cpu (faster)": {"int8", "int8_float32", "int16", "float32"},
    "cuda (faster)": {
        "int8", "int8_float16", "int8_bfloat16",
        "float16", "bfloat16", "float32",
    },
    "auto (faster)": {
        "int8", "int8_float32", "int8_float16", "int8_bfloat16",
        "int16", "float16", "bfloat16", "float32",
    },
    "cpu (OpenVINO)": {"FP32", "FP16", "INT8"},
    "gpu (OpenVINO)": {"FP32", "FP16", "INT8"},
    "auto (OpenVINO)": {"FP32", "FP16", "INT8"},
    "cpu (OpenVINO-GenAI)": {"FP16", "INT8", "INT4"},
    "gpu (OpenVINO-GenAI)": {"FP16", "INT8", "INT4"},
    "auto (OpenVINO-GenAI)": {"FP16", "INT8", "INT4"},
}

# 🆕 Which compute types are valid for OpenVINO backend
OPENVINO_COMPUTE_TYPES: set[str] = {"FP32", "FP16", "INT8", "INT4"}
FASTER_WHISPER_COMPUTE_TYPES: set[str] = (
    set(WHISPER_COMPUTE_TYPES) - OPENVINO_COMPUTE_TYPES
)

# 🧵 CPU threads
CPU_THREADS_AUTO: int = 0
CPU_THREADS_MAX: int = 64

# 🎯 Beam size limits
BEAM_SIZE_MIN: int = 1
BEAM_SIZE_MAX: int = 10
BEAM_SIZE_DEFAULT: int = 5

# 🌐 Groq cloud backend
GROQ_DEVICES = ["groq (cloud)"]
GROQ_COMPUTE_TYPES = ["Groq API"]

# 🏷️ Map canonical model names → Groq API model IDs
# (mirrors _HF_MODEL_MAP for OpenVINO)
_GROQ_MODEL_MAP: dict[str, str] = {
    "large-v3":          "whisper-large-v3",
    "large-v3-turbo":    "whisper-large-v3-turbo",
    "turbo":             "whisper-large-v3-turbo",
    "distil-large-v3":   "distil-whisper-large-v3-en",
    "distil-large-v3.5": "distil-whisper-large-v3-en",
}

# Extend master lists (NO model pollution!)
WHISPER_DEVICES = [*WHISPER_DEVICES, *GROQ_DEVICES]
WHISPER_COMPUTE_TYPES = [*WHISPER_COMPUTE_TYPES, *GROQ_COMPUTE_TYPES]

# Cloud OpenAI compat
OPENAI_API_DEVICES = [
    "openai (cloud)",
    "↳ groq (cloud)",
    "↳ fireworks (cloud)",
    "↳ gemini (cloud)"
]
OPENAI_API_COMPUTE_TYPES = ["OpenAI API"]

# Extend master lists (NO model pollution!)
WHISPER_DEVICES = [*WHISPER_DEVICES, *OPENAI_API_DEVICES]
WHISPER_COMPUTE_TYPES = [*WHISPER_COMPUTE_TYPES, *OPENAI_API_COMPUTE_TYPES]

# ═══════════════════════════════════════════════════════════
#  OpenVINO-GenAI pre-converted repos (single source of truth)
# ═══════════════════════════════════════════════════════════

# 🏷️ Models with official pre-converted IR on HuggingFace OpenVINO/*
_OV_GENAI_DIRECT: set[str] = {
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v3", "large-v3-turbo",
    "distil-large-v2", "distil-large-v3",
}

# 🔁 Aliases that resolve to a pre-converted model (with a warning)
_OV_GENAI_ALIASES: dict[str, str] = {
    "large":             "large-v3",
    "large-v2":          "large-v3",
    "turbo":             "large-v3-turbo",
    "distil":            "distil-large-v3",
    "distil-large-v3.5": "distil-large-v3",
}


def has_openvino_genai_equivalent(model_name: str) -> bool:
    """✅ True if the model is available (direct or via fallback) on
    OpenVINO HuggingFace pre-converted repos."""
    return (model_name in _OV_GENAI_DIRECT
            or model_name in _OV_GENAI_ALIASES)


def openvino_genai_resolved_name(model_name: str) -> tuple[str, str | None]:
    """Return (resolved_model, warning_or_None).

    If the model has a direct OV repo, returns (model, None).
    If it falls back to another model, returns (substitute, warning_msg).
    Returns (model, None) for unknown — caller should check
    has_openvino_genai_equivalent() first.
    """
    if model_name in _OV_GENAI_DIRECT:
        return model_name, None
    if model_name in _OV_GENAI_ALIASES:
        sub = _OV_GENAI_ALIASES[model_name]
        if model_name in ("turbo", "large-v3-turbo"):
            return sub, (f"⚠ {model_name!r} not pre-converted on OpenVINO; "
                         f"will use {sub} (6× faster, near-v3 quality)")
        return sub, f"ℹ {model_name!r} → {sub} on OpenVINO"
    return model_name, None


# ═══════════════════════════════════════════════════════════
#  Backend & device helpers
# ═══════════════════════════════════════════════════════════

def is_openvino_genai_device(device: str) -> bool:
    """True if the device string represents an OpenVINO GenAI selection."""
    return "(OpenVINO-GenAI)" in device

def is_openvino_device(device: str) -> bool:
    """True if the device string represents an OpenVINO selection."""
    return "(OpenVINO)" in device


def is_groq_device(device: str) -> bool:
    """🌐 True if the selected device runs in Groq cloud."""
    return "groq" in (device or "").lower()[:4]


def is_openai_device(device: str) -> bool:
    """🌐 True if the selected device runs in Groq cloud."""
    return (
        "openai" in (device or "").lower()
        or "↳" in (device or "").lower()
    )


def has_groq_equivalent(model: str) -> bool:
    """✅ True if the canonical model has a Groq API equivalent."""
    return model in _GROQ_MODEL_MAP


def model_name_to_groq_id(model_name: str) -> str | None:
    """🏷️ Map canonical model name to Groq API ID. None if unsupported."""
    return _GROQ_MODEL_MAP.get(model_name)


def backend_of(device: str) -> str:
    """Return 'openvino' or 'faster-whisper' for a given device string."""
    if is_openvino_device(device):
        return "openvino"
    if is_groq_device(device):
        return "groq api"
    if is_openai_device(device):
        return device.lstrip('↳').strip().split()[0]
    return "faster-whisper"


def parse_device(device: str) -> tuple[str, str]:
    """
    Split UI device string into (backend, raw_device).

    Examples:
        "cuda (faster)"   → ("faster-whisper", "cuda")
        "gpu (OpenVINO)"   → ("openvino", "GPU")
        "auto (OpenVINO)"  → ("openvino", "AUTO")
    """
    if is_openvino_genai_device(device):
        raw = device.split(" (")[0].upper()  # gpu → GPU, auto → AUTO
        return ("openvino_genai", raw)
    if is_openvino_device(device):
        raw = device.split(" (")[0].upper()  # gpu → GPU, auto → AUTO
        return ("openvino", raw)
    backend = backend_of(device)
    raw = device.split(" (")[0]              # cuda, cpu, auto
    return (backend, raw)


# ═══════════════════════════════════════════════════════════
#  HuggingFace model ID mapping (for OpenVINO)
# ═══════════════════════════════════════════════════════════

# 🤗 Direct mapping for known models
_HF_MODEL_MAP: dict[str, str] = {
    "tiny":              "openai/whisper-tiny",
    "tiny.en":           "openai/whisper-tiny.en",
    "base":              "openai/whisper-base",
    "base.en":           "openai/whisper-base.en",
    "small":             "openai/whisper-small",
    "small.en":          "openai/whisper-small.en",
    "medium":            "openai/whisper-medium",
    "medium.en":         "openai/whisper-medium.en",
    "large":             "openai/whisper-large-v3",
    "large-v1":          "openai/whisper-large",
    "large-v2":          "openai/whisper-large-v2",
    "large-v3":          "openai/whisper-large-v3",
    "large-v3-turbo":    "openai/whisper-large-v3-turbo",
    "turbo":             "openai/whisper-large-v3-turbo",
    "distil-large-v2":   "distil-whisper/distil-large-v2",
    "distil-large-v3":   "distil-whisper/distil-large-v3",
    "distil-medium.en":  "distil-whisper/distil-medium.en",
    "distil-small.en":   "distil-whisper/distil-small.en",
    # ⚠️ distil-large-v3.5 has no official OpenVINO HF version yet
}


def model_name_to_hf_id(model_name: str) -> str | None:
    """Map faster-whisper model name to HuggingFace ID. None if unknown."""
    return _HF_MODEL_MAP.get(model_name)


def has_openvino_equivalent(model_name: str) -> bool:
    """True if this model has a known HuggingFace OpenVINO equivalent."""
    return model_name in _HF_MODEL_MAP


# ═══════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════

@dataclass
class WhisperConfig:
    """User-configurable Whisper settings."""

    # ── Core ──
    model: str = "large-v3-turbo"
    device: str = "auto (faster)"
    beam_size: int = 5
    compute_type: str = "int8_float16"

    # ── Performance ──
    cpu_threads: int = CPU_THREADS_AUTO
    num_workers: int = 1
    beam_size: int = BEAM_SIZE_DEFAULT

    # ── Storage & Network ──
    download_root: str = ""
    local_files_only: bool = True

    # ── Advanced ──
    device_index: list[int] = field(default_factory=lambda: [0])
    use_auth_token: str = ""

    # ── Language ──
    language: str = ""

    # ── Custom Prompt with initial instructions ──
    initial_prompt: str = (
        "The transcript discusses network engineering, configurations"
        " for equipaments like Cisco, Mikrotik, Linux, etc, topologies,"
        " IPs, devices or regions named 1-3 letters plus 1-4 digits."
    )
    no_speech_text: str = ""
    noise_level: float = .3
    delay_transcription: float = 1

    # ✂️ VAD pre-trim (preprocessing before transcription)
    vad_pretrim: bool = True
    vad_threshold: float = 0.3
    vad_speech_pad_ms: int = 500
    vad_min_silence_ms: int = 500
    vad_keep_temp: bool = False

    CONFIG_FILE: ClassVar[str] = "whisper.json"

    # ── Migration helper ──
    @staticmethod
    def _migrate_device(old: str) -> str:
        """Migrate legacy device strings ('cuda', 'cpu', 'auto') to new format."""
        legacy_map = {
            "auto": "auto (faster)",
            "cpu":  "cpu (faster)",
            "cuda": "cuda (faster)",
        }
        return legacy_map.get(old, old)

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.model not in WHISPER_MODELS:
            errors.append(f"Invalid model: {self.model!r}")

        if self.device not in WHISPER_DEVICES:
            errors.append(f"Invalid device: {self.device!r}")

        if self.compute_type not in WHISPER_COMPUTE_TYPES:
            errors.append(f"Invalid compute_type: {self.compute_type!r}")

        # 🆕 Cross-check: OpenVINO device requires OpenVINO compute_type
        if is_openvino_device(self.device) or is_openvino_genai_device(self.device):
            if self.compute_type not in OPENVINO_COMPUTE_TYPES:
                errors.append(
                    f"OpenVINO device requires one of "
                    f"{sorted(OPENVINO_COMPUTE_TYPES)}, got {self.compute_type!r}"
                )
        else:
            if self.compute_type in OPENVINO_COMPUTE_TYPES:
                errors.append(
                    f"compute_type {self.compute_type!r} only valid for OpenVINO"
                )

        if not (0 <= self.cpu_threads <= CPU_THREADS_MAX):
            errors.append(f"cpu_threads must be 0..{CPU_THREADS_MAX}")

        if not (BEAM_SIZE_MIN <= self.beam_size <= BEAM_SIZE_MAX):
            errors.append(
                f"beam_size must be {BEAM_SIZE_MIN}..{BEAM_SIZE_MAX} "
                f"(got {self.beam_size})"
            )

        if self.num_workers < 1:
            errors.append(f"num_workers must be ≥ 1")

        if self.download_root:
            try:
                Path(self.download_root).expanduser()
            except (TypeError, ValueError):
                errors.append(f"Invalid download_root")

        if not isinstance(self.device_index, list) or not self.device_index:
            errors.append("device_index must be non-empty list")

        if self.language != AUTO_DETECT and self.language not in WHISPER_LANGUAGES:
            errors.append(f"Invalid language: {self.language!r}")

        return errors

    @classmethod
    def _path(cls) -> Path:
        return config_dir() / cls.CONFIG_FILE

    @classmethod
    def load(cls) -> "WhisperConfig":
        path = cls._path()
        if not path.exists():
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 🛡️ Migrate legacy device names
            if "device" in data:
                data["device"] = cls._migrate_device(data["device"])

            # 🛡️ Migrate legacy Groq model names → canonical names
            legacy_groq = {
                "whisper-large-v3-turbo": "large-v3-turbo",
                "whisper-large-v3":       "large-v3",
            }
            if data.get("model") in legacy_groq:
                data["model"] = legacy_groq[data["model"]]

            known_fields = {
                "model", "device", "compute_type",
                "cpu_threads", "num_workers", "beam_size",
                "download_root", "local_files_only",
                "device_index", "use_auth_token", "language",
                "initial_prompt", "no_speech_text",
                "noise_level", "delay_transcription",
                "vad_pretrim", "vad_threshold", "vad_speech_pad_ms",
                "vad_min_silence_ms", "vad_keep_temp",
            }
            filtered = {k: v for k, v in data.items() if k in known_fields}
            cfg = cls(**filtered)

            if cfg.validate():
                print(f"⚠ Invalid Whisper config; using defaults.")
                return cls()
            return cfg

        except (OSError, json.JSONDecodeError, TypeError) as e:
            print(f"⚠ Failed to load config: {e}")
            return cls()

    def save(self) -> bool:
        try:
            path = self._path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            return True
        except OSError as e:
            print(f"⚠ Failed to save config: {e}")
            return False

    # ── Backend dispatcher helpers ──
    @property
    def backend(self) -> str:
        return backend_of(self.device)

    @property
    def is_openvino_genai(self) -> bool:
        return is_openvino_genai_device(self.device)

    @property
    def is_openvino(self) -> bool:
        return is_openvino_device(self.device)

    @property
    def is_groq(self) -> bool:
        """🌐 Cloud-based Groq backend."""
        return is_groq_device(self.device)

    @property
    def is_openai(self) -> bool:
        """🌐 OpenAI API-based backend."""
        return is_openai_device(self.device)

    def parsed_device(self) -> tuple[str, str]:
        return parse_device(self.device)

    # ── faster-whisper kwargs ──
    def to_kwargs(self) -> dict:
        """Build kwargs for faster_whisper.WhisperModel(...). Only valid when
        backend is 'faster-whisper'."""
        _, raw_device = self.parsed_device()

        kwargs: dict = {
            "model_size_or_path": self.model,
            "device": raw_device,
            "compute_type": self.compute_type,
            "num_workers": self.num_workers,
            "local_files_only": self.local_files_only,
        }
        if self.cpu_threads > 0:
            kwargs["cpu_threads"] = self.cpu_threads
        if self.download_root:
            kwargs["download_root"] = str(
                Path(self.download_root).expanduser()
            )
        if len(self.device_index) == 1:
            kwargs["device_index"] = self.device_index[0]
        else:
            kwargs["device_index"] = list(self.device_index)
        if self.use_auth_token:
            kwargs["use_auth_token"] = self.use_auth_token
        return kwargs

    def summary(self) -> str:
        return (
            f"{self.model} · {self.device} · {self.compute_type} "
            f"· beam={self.beam_size}"
            + (f" · {self.cpu_threads}t" if self.cpu_threads > 0 else "")
        )
