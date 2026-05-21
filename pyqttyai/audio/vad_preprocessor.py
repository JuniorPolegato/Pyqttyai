"""✂️ Silero VAD pre-trimming for cleaner Whisper input — provider-agnostic.

Inspired by Claudio's benchmark showing 3× speedup + better accuracy
when silence/noise is removed before transcription.

CRITICAL: Whisper hallucinates on non-speech audio. VAD pre-trim
eliminates silence, coughs, doorbells, music, etc. before they
reach the model, dramatically reducing "ghost text" output.
"""

import wave
from pathlib import Path
from typing import Optional


# 🪶 Lazy-imported Silero VAD from faster_whisper assets
_VAD_FN = None


def _ensure_vad_loaded():
    """🔌 Lazy-load standalone Silero VAD."""
    global _VAD_FN
    if _VAD_FN is None:
        from pyqttyai.audio.silero_vad import get_speech_timestamps
        _VAD_FN = get_speech_timestamps


def vad_trim(
    wav_path: str,
    out_path: Optional[str] = None,
    threshold: float = 0.3,
    speech_pad_ms: int = 500,
    min_silence_ms: int = 500,
) -> tuple[str, dict]:
    """✂️ Cut silence/noise from a WAV using Silero VAD.

    Returns
    -------
    (out_wav_path, stats_dict)
        out_wav_path : path to trimmed WAV
                       (== wav_path if no speech / wrong sample rate)
        stats_dict   : {
            "original_duration": float,
            "trimmed_duration": float,
            "ratio": float,             # 0..1, 1 = no trimming
            "segments": int,            # number of speech segments
            "skipped": bool,            # True if VAD couldn't run
            "reason": str,              # only when skipped
        }
    """
    import numpy as np

    _ensure_vad_loaded()

    # 📥 Load WAV
    with wave.open(wav_path, "rb") as wf:
        params = wf.getparams()
        if params.framerate != 16000:
            # ⚠️ Silero expects 16k — return original
            dur = params.nframes / params.framerate
            return wav_path, {
                "original_duration": dur,
                "trimmed_duration": dur,
                "ratio": 1.0,
                "segments": 0,
                "skipped": True,
                "reason": f"sample_rate={params.framerate} (need 16000)",
            }
        audio_bytes = wf.readframes(wf.getnframes())

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    original_duration = len(audio_np) / 16000.0

    # 🎚️ Run VAD (standalone, no VadOptions object needed)
    timestamps = _VAD_FN(
        audio_np,
        threshold=threshold,
        speech_pad_ms=speech_pad_ms,
        min_silence_ms=min_silence_ms,
    )

    if not timestamps:
        # 🤐 No speech detected
        return wav_path, {
            "original_duration": original_duration,
            "trimmed_duration": 0.0,
            "ratio": 0.0,
            "segments": 0,
            "skipped": False,
            "reason": "no_speech_detected",
        }

    # ✂️ Stitch speech segments
    chunks = [audio_np[ts["start"]:ts["end"]] for ts in timestamps]
    final = np.concatenate(chunks)
    final_int16 = (final * 32767).astype(np.int16)

    # 💾 Write
    if out_path is None:
        p = Path(wav_path)
        out_path = str(p.with_name(p.stem + "_vad" + p.suffix))

    with wave.open(out_path, "wb") as wf_out:
        wf_out.setparams(params)
        wf_out.writeframes(final_int16.tobytes())

    return out_path, {
        "original_duration": original_duration,
        "trimmed_duration": len(final) / 16000.0,
        "ratio": len(final) / max(len(audio_np), 1),
        "segments": len(timestamps),
        "skipped": False,
    }
