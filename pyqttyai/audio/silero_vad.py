"""🔇 Standalone Silero VAD — auto-detects v4/v5 (h,c) vs v6 (state)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np

_MODEL_FILENAME = "silero_vad.onnx"
_SAMPLE_RATE = 16000

# 🔒 Singletons
_lock = threading.Lock()
_SESSION_CACHE = {"session": None, "kind": None, "shapes": None}


def _asset_path() -> Path:
    """📍 Resolve bundled ONNX — works in source tree AND frozen exe."""
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "pyqttyai" / "audio" / "assets" / _MODEL_FILENAME
        if p.exists():
            return p
    return Path(__file__).resolve().parent / "assets" / _MODEL_FILENAME


def is_vad_available() -> bool:
    """🔍 Capability probe."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return _asset_path().exists()


def _get_session():
    """🏗️ Lazy singleton init — also detects model version."""
    if  _SESSION_CACHE["session"] is None:
        with _lock:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3  # 🤫 silence ORT warnings
            sess = ort.InferenceSession(
                str(_asset_path()),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            # 🔎 Auto-detect by input names
            kind, shapes = _detect_kind_and_state_shapes(sess)
            _SESSION_CACHE.update(session=sess, kind=kind, shapes=shapes)

    return _SESSION_CACHE["session"], _SESSION_CACHE["kind"]


def _get_initial_state():
    """🔧 Helper público para chamadas que precisam recriar estado."""
    _get_session()  # garante carregamento
    return _init_state(_SESSION_CACHE["kind"], _SESSION_CACHE["shapes"])


def _detect_kind_and_state_shapes(session):
    """🔎 Detecta tipo, shapes, has_sr e window_size *do áudio consumido*."""
    input_names = {i.name: i for i in session.get_inputs()}
    has_sr = "sr" in input_names

    if "state" in input_names:
        shape = input_names["state"].shape
        concrete = tuple(d if isinstance(d, int) else 1 for d in shape)
        # 🎯 v6 oficial: consome chunks de 512, concatena 64 de context internamente
        return "v6", {
            "state_shape": concrete,
            "has_sr": has_sr,
            "window_size": 512,  # 🪟 chunks que VOCÊ alimenta (context é interno)
        }

    if "h" in input_names and "c" in input_names:
        h_shape = tuple(d if isinstance(d, int) else 1 for d in input_names["h"].shape)
        c_shape = tuple(d if isinstance(d, int) else 1 for d in input_names["c"].shape)
        # 🧬 _fw: shape declarada [None, None], mas exige 576
        return "lstm", {
            "h_shape": h_shape,
            "c_shape": c_shape,
            "has_sr": has_sr,
            "window_size": 576,  # 🪟 chunk completo (context embutido)
        }

    raise RuntimeError(f"❌ Modelo ONNX desconhecido. Inputs: {list(input_names)}")


def _init_state(kind: str, shapes: dict):
    """🎬 Cria estado zerado com as dimensões corretas pro modelo carregado."""
    if kind == "v6":
        return {
            "state": np.zeros(shapes["state_shape"], dtype=np.float32),
            "_context": np.zeros(64, dtype=np.float32),  # 🆕 buffer interno
        }
    else:
        return {
            "h": np.zeros(shapes["h_shape"], dtype=np.float32),
            "c": np.zeros(shapes["c_shape"], dtype=np.float32),
        }


def _run_chunk(session, kind: str, chunk: np.ndarray, state: dict, sr_tensor):
    """🎯 Single forward pass; returns (speech_prob, new_state)."""
    if kind == "v6":
        # 🪡 Concatena context (64) + chunk (512) = 576 amostras
        context = state["_context"]
        input_array = np.concatenate([context, chunk])[None, :]

        feed = {"input": input_array, "state": state["state"]}
        if _SESSION_CACHE["shapes"].get("has_sr", True):
            feed["sr"] = sr_tensor

        outputs = session.run(None, feed)
        prob = outputs[0]
        new_state = {
            "state": outputs[1],
            "_context": chunk[-64:].copy(),  # 🔄 últimas 64 amostras viram next context
        }
    else:
        # 🧬 lstm (_fw): chunk já vem no tamanho certo (576), sem context externo
        feed = {"input": chunk[None, :], "h": state["h"], "c": state["c"]}
        if _SESSION_CACHE["shapes"].get("has_sr", True):
            feed["sr"] = sr_tensor

        outputs = session.run(None, feed)
        prob = outputs[0]
        new_state = {"h": outputs[1], "c": outputs[2]}

    return float(prob.flatten()[0]), new_state


def get_speech_timestamps(
    audio: np.ndarray,
    threshold: float = 0.3,
    min_speech_ms: int = 250,
    min_silence_ms: int = 500,
    speech_pad_ms: int = 500,
) -> list[dict]:
    """🎙️ Return list of {'start': sample_idx, 'end': sample_idx}."""
    session, kind = _get_session()
    state = _get_initial_state()
    sr_tensor = np.array(_SAMPLE_RATE, dtype=np.int64)

    # 🪟 Lê o window size descoberto na detecção
    window_size = _SESSION_CACHE["shapes"]["window_size"]

    n_windows = len(audio) // window_size
    if n_windows == 0:
        return []

    probs = np.empty(n_windows, dtype=np.float32)
    for i in range(n_windows):
        chunk = audio[i * window_size:(i + 1) * window_size].astype(np.float32)
        probs[i], state = _run_chunk(session, kind, chunk, state, sr_tensor)

    # 🎚️ Convert frame probabilities → time ranges (usa window_size!)
    min_speech_frames  = max(1, min_speech_ms  * _SAMPLE_RATE // (1000 * window_size))
    min_silence_frames = max(1, min_silence_ms * _SAMPLE_RATE // (1000 * window_size))
    pad_samples        = speech_pad_ms * _SAMPLE_RATE // 1000

    speaking = probs >= threshold
    segments: list[dict] = []
    start = None
    silence_run = 0

    for i, is_speech in enumerate(speaking):
        if is_speech:
            if start is None:
                start = i
            silence_run = 0
        else:
            if start is not None:
                silence_run += 1
                if silence_run >= min_silence_frames:
                    end = i - silence_run + 1
                    if end - start >= min_speech_frames:
                        segments.append({
                            "start": max(0, start * window_size - pad_samples),
                            "end":   min(len(audio), end * window_size + pad_samples),
                        })
                        start = None
                        silence_run = 0

    if start is not None and (n_windows - start) >= min_speech_frames:
        segments.append({
            "start": max(0, start * window_size - pad_samples),
            "end":   len(audio),
        })

    # 🔗 Merge overlaps
    merged: list[dict] = []
    for seg in segments:
        if merged and seg["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], seg["end"])
        else:
            merged.append(seg)
    return merged
