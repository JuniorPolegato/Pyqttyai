"""OpenVINO-based Whisper engine using optimum-intel."""

import time
from pathlib import Path
from typing import Any

from pyqttyai.core.whisper_config import (
    WhisperConfig, model_name_to_hf_id,
)


class OpenVINOWhisperModel:
    """Wrapper around optimum-intel Whisper that mimics faster-whisper API.

    Returned by `load_openvino_model()`. Provides a `.transcribe()` method
    compatible with the existing Transcriber worker.
    """

    def __init__(self, ov_model, processor, generation_config):
        self._model = ov_model
        self._processor = processor
        self._generation_config = generation_config

    def transcribe(
        self,
        audio_path: str,
        beam_size: int = 5,
        language: str | None = None,
        vad_filter: bool = False,  # 🚫 ignored (no VAD in optimum-intel)
        **_ignored,
    ):
        """Transcribe an audio file. Returns (segments_iter, info)."""
        import librosa  # 🎵 lazy import

        # 🎵 Load audio at 16kHz mono
        audio, _ = librosa.load(audio_path, sr=16000, mono=True)
        duration = len(audio) / 16000.0

        inputs = self._processor(
            audio, sampling_rate=16000, return_tensors="pt",
        )

        # 🧠 Generate
        gen_kwargs = {"num_beams": beam_size}
        if language:
            gen_kwargs["language"] = language
            gen_kwargs["task"] = "transcribe"

        predicted_ids = self._model.generate(
            inputs.input_features, **gen_kwargs,
        )
        text = self._processor.batch_decode(
            predicted_ids, skip_special_tokens=True,
        )[0].strip()

        # 🎯 Detect language (optimum-intel doesn't expose probability)
        detected_lang = language or "en"
        lang_prob = 1.0 if language else 0.0

        # 📋 Build a faster-whisper-compatible "segment"
        class _Segment:
            def __init__(self, text, dur):
                self.text = text
                self.start = 0.0
                self.end = dur

        class _Info:
            def __init__(self, lang, prob, dur):
                self.language = lang
                self.language_probability = prob
                self.duration = dur
                self.all_language_probs = None

        segments = [_Segment(text, duration)] if text else []
        info = _Info(detected_lang, lang_prob, duration)
        return iter(segments), info


def load_openvino_model(
    config: WhisperConfig,
    progress_cb=None,
) -> OpenVINOWhisperModel:
    """Load a Whisper model using OpenVINO via optimum-intel.

    Args:
        config: WhisperConfig (must have OpenVINO device)
        progress_cb: optional callable(str) for status messages

    Raises:
        ImportError: if optimum-intel/openvino not installed
        ValueError: if model has no HuggingFace OpenVINO equivalent
        RuntimeError: on load/conversion failure
    """
    def _progress(msg: str):
        if progress_cb:
            progress_cb(msg)

    _progress("📦 Importing optimum-intel + OpenVINO…")
    try:
        from optimum.intel import OVModelForSpeechSeq2Seq
        from transformers import AutoProcessor
    except ImportError as e:
        raise ImportError(
            f"OpenVINO backend not installed: {e}\n"
            "To install, uncomment the last lines in requirements_min.txt. "
            "Then, install using `pip install -r requirements_min.txt`."
        ) from e

    # 🤗 Map model name to HuggingFace ID
    hf_id = model_name_to_hf_id(config.model)
    if hf_id is None:
        raise ValueError(
            f"Model {config.model!r} has no known OpenVINO equivalent.\n"
            f"Try: tiny, base, small, medium, large-v3, large-v3-turbo, "
            f"or distil-large-v3."
        )

    # 🎮 Parse device (CPU / GPU / AUTO)
    _, raw_device = config.parsed_device()

    # 💾 Cache location
    cache_dir = None
    if config.download_root:
        cache_dir = str(Path(config.download_root).expanduser())

    _progress(f"📥 Loading {hf_id} on OpenVINO {raw_device}…\n"
              "First run downloads and converts model — may take minutes")

    try:
        ov_model = OVModelForSpeechSeq2Seq.from_pretrained(
            hf_id,
            export=True,             # ⚙️ auto-convert if needed
            device=raw_device,
            cache_dir=cache_dir,
            local_files_only=config.local_files_only,
        )
        processor = AutoProcessor.from_pretrained(
            hf_id,
            cache_dir=cache_dir,
            local_files_only=config.local_files_only,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to load OpenVINO model: {e}") from e

    _progress("✅ OpenVINO model ready")
    return OpenVINOWhisperModel(ov_model, processor, None)


def is_openvino_available() -> bool:
    """Check if OpenVINO + optimum-intel are importable."""
    try:
        import optimum.intel  # noqa: F401
        import openvino       # noqa: F401
        return True
    except ImportError:
        return False
