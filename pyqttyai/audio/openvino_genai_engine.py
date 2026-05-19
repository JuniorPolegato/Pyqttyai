"""🚀 Lightweight OpenVINO Whisper engine using openvino-genai.

Downloads pre-converted OpenVINO IR models from HuggingFace
(OpenVINO/whisper-*-{int4,int8,fp16}-ov repos) and runs them via
the openvino_genai.WhisperPipeline — no torch, no optimum, no conversion.

Mimics the faster-whisper API: `.transcribe(path) -> (segments, info)`.
"""

import time
from pathlib import Path
from typing import Any, Optional

from pyqttyai.core.whisper_config import WhisperConfig


# ════════════════════════════════════════════════════════════════════════
# 🏷️ Canonical model name → OpenVINO HF repo base name
# Only models that ACTUALLY exist as pre-converted IR on HuggingFace.
# Verified via:
#   huggingface_hub.list_models(search='OpenVINO/whisper')
#   huggingface_hub.list_models(search='OpenVINO/distil-whisper')
# ════════════════════════════════════════════════════════════════════════
_OV_REPO_BASE = {
    # Multilingual Whisper
    "tiny":              "whisper-tiny",
    "base":              "whisper-base",
    "small":             "whisper-small",
    "medium":            "whisper-medium",
    "large-v3":          "whisper-large-v3",
    "large-v3-turbo":    "whisper-large-v3-turbo",
    # English-only variants (faster, slightly more accurate for en)
    "tiny.en":           "whisper-tiny.en",
    "base.en":           "whisper-base.en",
    "small.en":          "whisper-small.en",
    "medium.en":         "whisper-medium.en",
    # 🌀 Distil-Whisper (smaller decoder, ~6× faster, near-v3 quality)
    "distil-large-v2":   "distil-whisper-large-v2",
    "distil-large-v3":   "distil-whisper-large-v3",
}

# 🔁 Aliases & fallbacks for models not pre-converted in OpenVINO/*
# Each entry: canonical_name → (substitute_model, user_warning)
# To convert on-the-fly:
# optimum-cli export openvino --model openai/whisper-large-v3-turbo --weight-format int8 ./whisper-turbo-ov

_OV_FALLBACKS = {
    "large":            ("large-v3",
                         "ℹ️ Using large-v3 (generic 'large' alias)"),
    "large-v2":         ("large-v3",
                         "⚠️ large-v2 not pre-converted; using large-v3 instead"),
    "turbo":            ("large-v3-turbo",
                         "⚠️ turbo is alias for large-v3-turbo"
                         "using large-v3 (Higher quality, but slower.)"),
    "distil":           ("distil-large-v3",
                         "ℹ️ Using distil-large-v3 (latest distil variant)"),
}

# 🎯 Quantization → repo suffix
_QUANT_SUFFIX = {
    "int4":     "int4-ov",   # smallest, fastest, lossy
    "int8":     "int8-ov",   # good balance
    "fp16":     "fp16-ov",   # default, near-FP32 quality
    # Aliases mapping to fp16
    "float16":  "fp16-ov",
    "default":  "fp16-ov",
    "auto":     "fp16-ov",
}


def _resolve_repo_id(
    model: str,
    compute_type: str,
    progress_cb=None,
) -> Optional[str]:
    """Build the HF repo id for a (model, quantization) pair.

    Handles fallbacks with user-facing warnings (via progress_cb).
    Returns None if no repo exists for the requested model.
    """
    # 🔁 Resolve fallback aliases (turbo → distil-large-v3, etc.)
    if model in _OV_FALLBACKS:
        new_model, warning = _OV_FALLBACKS[model]
        if progress_cb:
            progress_cb(warning)
        model = new_model

    base = _OV_REPO_BASE.get(model)
    if base is None:
        return None

    suffix = _QUANT_SUFFIX.get((compute_type or "fp16").lower(), "fp16-ov")
    return f"OpenVINO/{base}-{suffix}"


# ═══════════════════════════════════════════════════════════
#  Wrapper — faster-whisper-compatible shape
# ═══════════════════════════════════════════════════════════

class _Segment:
    __slots__ = ("text", "start", "end")
    def __init__(self, text: str, start: float = 0.0, end: float = 0.0):
        self.text = text
        self.start = start
        self.end = end


class _Info:
    __slots__ = ("language", "language_probability",
                 "all_language_probs", "duration")
    def __init__(self, language: str, duration: float):
        self.language = language or "en"
        self.language_probability = 1.0
        self.all_language_probs = None
        self.duration = duration or 0.0


class OpenVINOGenAIWhisperModel:
    """🪶 Thin wrapper around `openvino_genai.WhisperPipeline`.

    Provides a `.transcribe(path, **kwargs)` method that mirrors
    faster-whisper's contract: returns `(segments_iter, info)`.
    """

    def __init__(self, pipeline: Any, model_dir: Path, device: str):
        self._pipeline = pipeline
        self._model_dir = model_dir
        self._device = device

    # ── Public API ────────────────────────────────────────────
    def transcribe(
        self,
        audio_path: str,
        beam_size: int = 5,
        language: str | None = None,
        vad_filter: bool = False,           # 🚫 ignored — no VAD inside genai
        initial_prompt: str | None = None,  # 🚫 ignored — not exposed by WhisperPipeline
        **_ignored,
    ):
        """Transcribe one WAV file. Returns `(segments_iter, info)`."""
        import openvino_genai as ov_genai  # 🪶 lazy
        import librosa                      # 🎵 lazy

        # 🎵 Load mono 16 kHz float32 — required by WhisperPipeline
        audio, _sr = librosa.load(audio_path, sr=16000, mono=True)
        duration = float(len(audio)) / 16000.0

        # 🧠 Build generation config
        gen_cfg = self._pipeline.get_generation_config()

        if language:
            gen_cfg.language = f"<|{language}|>"
        gen_cfg.task = "transcribe"
        gen_cfg.max_new_tokens = 448
        gen_cfg.return_timestamps = True
        gen_cfg.num_beams = 1 if self._device == "GPU" else beam_size

        result = self._pipeline.generate(audio, gen_cfg)

        # The result stringifies cleanly; segments come from result.chunks
        full_text = str(result).strip()
        segments: list[_Segment] = []

        chunks = getattr(result, "chunks", None)
        if chunks:
            for ch in chunks:
                # ch.start_ts / ch.end_ts are seconds (floats); ch.text is str
                segments.append(_Segment(
                    text=getattr(ch, "text", "") or "",
                    start=float(getattr(ch, "start_ts", 0.0) or 0.0),
                    end=float(getattr(ch, "end_ts", 0.0) or 0.0),
                ))
        elif full_text:
            segments.append(_Segment(full_text, 0.0, duration))

        info = _Info(language or "en", duration)
        return iter(segments), info


# ═══════════════════════════════════════════════════════════
#  Loader
# ═══════════════════════════════════════════════════════════

def load_openvino_repo_model(
    config: WhisperConfig,
    progress_cb=None,
) -> OpenVINOGenAIWhisperModel:
    """Download (if needed) a pre-converted OpenVINO Whisper IR model
    from HuggingFace and load it with `openvino_genai.WhisperPipeline`.

    Args:
        config: WhisperConfig — uses .model, .compute_type, .device,
                .download_root, .local_files_only.
        progress_cb: optional callable(str) for status messages.

    Raises:
        ImportError: if `openvino_genai` or `huggingface_hub` is missing.
        ValueError:  if the requested model has no OV repo equivalent.
        RuntimeError: on download / load failure.
    """
    def _p(msg: str):
        if progress_cb:
            progress_cb(msg)

    # ── 1. Imports (lazy + clear errors) ─────────────────────
    _p("📦 Importing openvino_genai…")
    try:
        import openvino_genai as ov_genai
    except ImportError as e:
        raise ImportError(
            f"openvino_genai not installed: {e}\n"
            "Install with: pip install openvino-genai"
        ) from e

    _p("📦 Importing huggingface_hub…")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise ImportError(
            f"huggingface_hub not installed: {e}\n"
            "Install with: pip install huggingface_hub"
        ) from e

    # ── 2. Resolve repo id ───────────────────────────────────
    repo_id = _resolve_repo_id(config.model, config.compute_type, progress_cb=_p)
    if repo_id is None:
        raise ValueError(
            f"Model {config.model!r} has no known OpenVINO repo.\n"
            f"Supported: {sorted(_OV_REPO_BASE)} "
            f"(plus aliases: {sorted(_OV_FALLBACKS)})"
        )

    # ── 3. Resolve cache & device ────────────────────────────
    cache_dir = (
        str(Path(config.download_root).expanduser())
        if config.download_root else None
    )
    _, raw_device = config.parsed_device()  # e.g. "CPU", "GPU", "AUTO", "NPU"

    # ── 4. Download (or reuse) the IR snapshot ───────────────
    _p(f"📥 Fetching {repo_id} (device={raw_device})…")
    t0 = time.time()
    try:
        model_dir = Path(snapshot_download(
            repo_id=repo_id,
            cache_dir=cache_dir,
            local_files_only=bool(config.local_files_only),
            # 🎯 We only need IR + tokenizer assets, no PyTorch weights
            allow_patterns=[
                "*.xml", "*.bin",                 # IR
                "*.json",                         # configs
                "tokenizer*", "vocab*", "merges*",
                "preprocessor_config.json",
                "generation_config.json",
                "added_tokens.json",
                "special_tokens_map.json",
                "openvino_tokenizer*", "openvino_detokenizer*",
            ],
        ))
    except Exception as e:
        raise RuntimeError(
            f"Failed to download {repo_id}: {e}\n"
            "Check internet connection or try a different quantization "
            "(compute_type=int4|int8|fp16)."
        ) from e
    download_time = time.time() - t0
    _p(f"✅ Snapshot ready in {download_time:.1f}s ({model_dir})")

    # ── 5. Build the pipeline ────────────────────────────────
    _p(f"⚙️ Initializing WhisperPipeline on {raw_device}…")
    try:
        pipeline = ov_genai.WhisperPipeline(str(model_dir), device=raw_device)
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize WhisperPipeline on {raw_device}: {e}\n"
            "Try device=CPU or a smaller / different-quant model."
        ) from e

    _p(f"🎉 OpenVINO-GenAI model ready ({repo_id} on {raw_device})")
    return OpenVINOGenAIWhisperModel(pipeline, model_dir, raw_device)


# ═══════════════════════════════════════════════════════════
#  Availability probe
# ═══════════════════════════════════════════════════════════

def is_openvino_genai_available() -> bool:
    """True if `openvino_genai` can be imported."""
    try:
        import openvino_genai  # noqa: F401
        import huggingface_hub  # noqa: F401
        return True
    except ImportError:
        return False
