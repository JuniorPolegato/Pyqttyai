"""Worker function that runs in a SEPARATE OS process.

Loads a Whisper model ONCE (faster-whisper or OpenVINO), then consumes
WAV paths from a queue and emits results.

Communicates with the main process via two multiprocessing.Queue:
  - in_queue:  receives WAV paths or control commands.
  - out_queue: emits dicts {"event": ..., **data}.
"""

import multiprocessing as mp
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any
import signal

from pyqttyai.core.whisper_config import WhisperConfig, model_name_to_groq_id

# ═══════════════════════════════════════════════════════════
#  Control commands (sent via in_queue)
# ═══════════════════════════════════════════════════════════

class _Cmd:
    STOP = "__STOP__"
    PING = "__PING__"


# ═══════════════════════════════════════════════════════════
#  Model loaders (run INSIDE the worker process)
# ═══════════════════════════════════════════════════════════

def _load_faster_whisper(config, emit) -> tuple[Any, float]:
    """Load model via faster-whisper. Returns (model, load_time)."""
    emit("model_loading", message="📦 Importing faster_whisper…")
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            f"faster_whisper not installed: {e}\n"
            "Install using `pip install -r requirements_min.txt`."
        )

    _, raw_device = config.parsed_device()
    emit("model_loading",
         message=f"⏳ Downloading '{config.model}' for {raw_device}…")

    t0 = time.time()
    model = WhisperModel(**config.to_kwargs())
    load_time = time.time() - t0

    emit("model_loading",
         message=f"📥 Loaded '{config.model}' on {raw_device} ({load_time:.1f}s)")
    return model, load_time


def _load_openvino(config, emit) -> tuple[Any, float]:
    """Load model via OpenVINO. Returns (model, load_time)."""
    emit("model_loading", message="📦 Importing openvino…")
    try:
        from pyqttyai.audio.openvino_engine import load_openvino_model
    except ImportError as e:
        raise RuntimeError(
            f"openvino problem: {e}\nInstall it or fix the problem."
        )

    t0 = time.time()
    model = load_openvino_model(
        config,
        progress_cb=lambda msg: emit("model_loading", message=msg),
    )
    load_time = time.time() - t0

    _, raw_device = config.parsed_device()
    emit("model_loading",
         message=f"📥 Loaded 'ov_{config.model}' on {raw_device} ({load_time:.1f}s)")
    return model, load_time


def _load_openvino_genai(config: WhisperConfig, emit) -> tuple[Any, float]:
    """Load model via openvino-genai (pre-converted HF repo)."""
    emit("model_loading", message="📦 Importing openvino_genai…")
    try:
        from pyqttyai.audio.openvino_genai_engine import load_openvino_repo_model
    except ImportError as e:
        raise RuntimeError(
            f"openvino_genai not available: {e}\n"
            "Install with: pip install openvino-genai huggingface_hub"
        )

    t0 = time.time()
    model = load_openvino_repo_model(
        config,
        progress_cb=lambda msg: emit("model_loading", message=msg),
    )
    load_time = time.time() - t0

    _, raw_device = config.parsed_device()
    emit("model_loading",
         message=f"📥 Loaded 'ov_{config.model}' on {raw_device} ({load_time:.1f}s)")
    return model, load_time


# ═══════════════════════════════════════════════════════════
#  🌐 Groq cloud backend
# ═══════════════════════════════════════════════════════════

class _GroqWords:
    """Minimal segment object: only `.text` is read by _transcribe_one."""
    __slots__ = ("word", "start", "end")
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end

class _GroqSegment:
    """Minimal segment object: only `.text` is read by _transcribe_one."""
    __slots__ = ("text", "start", "end", "words")
    def __init__(self, text: str, start: float = 0, end: float = 0, words: list[_GroqWords] | list[dict] | None = None):
        self.text = text
        self.start = start
        self.end = end
        if words:
            if isinstance(words[0], _GroqWords):
                self.words = words
            elif isinstance(words[0], dict):
                self.words = [_GroqWords(**w) for w in words]
            else:
                self.words = None
        else:
            self.words = None

class _GroqInfo:
    """Mimics faster-whisper's TranscriptionInfo."""
    __slots__ = ("language", "language_probability",
                 "all_language_probs", "duration")
    def __init__(self, language, duration):
        self.language = language or "en"
        self.language_probability = 1.0
        self.all_language_probs = None
        self.duration = duration or 0.0


class _GroqClientAdapter:
    """🎁 Adapter so the cloud client looks like faster-whisper's WhisperModel."""

    def __init__(self, client, model_id: str):
        self._client = client
        self._model_id = model_id

    def transcribe(self, wav_path: str, **kwargs):
        language = kwargs.get("language")
        prompt = kwargs.get("initial_prompt")
        temperature = kwargs.get("temperature")
        word_timestamps = kwargs.get("word_timestamps")

        with open(wav_path, "rb") as f:
            audio_bytes = f.read()

        params = {
            "file": (Path(wav_path).name, audio_bytes),
            "model": self._model_id,
            "response_format": "verbose_json",
        }

        if language:
            params["language"] = language

        if prompt:
            params["prompt"] = prompt

        if temperature:
            params["temperature"] = temperature

        params["timestamp_granularities"] = ['segment']
        if word_timestamps:
            params["timestamp_granularities"].append('word')

        resp = self._client.audio.transcriptions.create(**params)
        print('~' * 100)
        print(resp)
        print('~' * 100)

        duration = getattr(resp, "duration", 0.0) or 0.0
        lang = getattr(resp, "language", language) or language or "en"

        if hasattr(resp, "segments"):
            segments = []
            for seg in getattr(resp, "segments", []) or []:
                if hasattr(resp, "words"):
                    try:
                        segment_words = seg['text'].strip().split()
                        segment_words_striped = [re.sub(r"\W+$", "", s) for s in segment_words]
                        words = []
                        for w in resp.words:
                            if seg['start'] <= w['start'] <= seg['end']:
                                words.append(w)
                                words[-1].update({"word": re.sub(r"\W+$", "", w['word'].lstrip())})
                        for i, sw in enumerate(segment_words_striped):
                            if sw == words[i]['word']:
                                words[i]['word'] = segment_words[i]
                                continue
                            if sw not in [w['word'] for w in words[i:i + 1]]:
                                words.insert(i, {"word": segment_words[i],
                                                 "start": words[i]["start"],
                                                 "end": words[i]["end"]})
                            elif words[i + 1:] and sw == words[i + 1]:
                                words.pop(i)
                        words = words[:i + 1]
                    except Exception:
                        print('ð' * 100)
                        traceback.print_exc()
                        print('Segment:', seg['text'])
                        print('Words:', words)
                        print('ð' * 100, flush=True)
                else:
                    words = None
                segments.append(
                    _GroqSegment(seg['text'], seg['start'], seg['end'], words)
                )
        else:
            text = getattr(resp, "text", "") or ""
            segments = (_GroqSegment(text),)

        info = _GroqInfo(lang, duration)
        return segments, info


def _load_groq(config, emit):
    """Initialize a Groq client. Returns (adapter, load_time)."""

    emit("model_loading", message="📦 Importing groq SDK…")
    try:
        from groq import Groq, AuthenticationError, APIError
    except ImportError as e:
        raise RuntimeError(
            f"groq SDK not installed: {e}\n"
            "Install with: pip install groq"
        )

    api_key = os.environ.get("GROQ_API_KEY") or getattr(config, "api_key", "") or ""
    if not api_key:
        emit("api_key_required",
             provider="groq",
             env_var="GROQ_API_KEY",
             message="🔑 Groq API key missing — please supply it.")
        raise RuntimeError(
            "GROQ_API_KEY not set. Set the environment variable "
            "or supply it via the UI."
        )

    # 🏷️ Map canonical model name → Groq API ID (single source of truth)
    groq_model_id = model_name_to_groq_id(config.model)
    if groq_model_id is None:
        raise RuntimeError(
            f"Model {config.model!r} has no known Groq equivalent.\n"
            f"Try: large-v3, large-v3-turbo, turbo, distil-large-v3."
        )

    emit("model_loading", message=f"🌐 Connecting to Groq ({groq_model_id})…")
    t0 = time.time()
    try:
        client = Groq(api_key=api_key)
        available = {m.id for m in client.models.list().data}
        if groq_model_id not in available:
            # 🔍 Surface the available whisper models for clarity
            whisper_models = sorted(m for m in available if "whisper" in m.lower())
            raise RuntimeError(
                f"Groq model {groq_model_id!r} not available.\n"
                f"Available Whisper models: {whisper_models}"
            )
    except AuthenticationError as e:
        emit("api_key_required",
             provider="groq",
             env_var="GROQ_API_KEY",
             message=f"🔑 Invalid Groq API key: {e}")
        raise RuntimeError(f"Invalid Groq API key: {e}")
    except APIError as e:
        raise RuntimeError(f"Groq API error: {e}")
    load_time = time.time() - t0

    return _GroqClientAdapter(client, groq_model_id), load_time

def _load_openai(config, emit):
    """Initialize an OpenAI-compatible cloud client."""
    try:
        from pyqttyai.audio.openai_compat_engine import (
            OpenAICompatibleEngine, PROVIDERS,
        )
    except ImportError as e:
        raise RuntimeError(
            f"OpenAI SDK not installed: {e}\n"
            "Install with: pip install openai"
        )

    provider = config.backend
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise RuntimeError(f"Unknown cloud provider: {provider!r}")

    emit("model_loading", message=f"📦 Initializing {provider} client…")

    api_key = os.environ.get(spec["env_var"]) or getattr(config, "api_key", "")
    if not api_key:
        emit("api_key_required",
             provider=provider,
             env_var=spec["env_var"],
             message=f"🔑 {provider.title()} API key missing — please supply it.")
        raise RuntimeError(f"{spec['env_var']} not set.")

    emit("model_loading",
         message=f"🌐 Connecting to {provider} ({config.model or spec['default_model']})…")

    engine = OpenAICompatibleEngine(config, provider=provider)
    try:
        load_time = engine.load()
    except RuntimeError as e:
        # 🔑 Re-emit api_key_required if invalid
        if "key" in str(e).lower():
            emit("api_key_required",
                 provider=provider,
                 env_var=spec["env_var"],
                 message=str(e))
        raise

    return engine, load_time


def _load_model(config: WhisperConfig, emit) -> tuple[Any, float]:
    """Dispatch to the right backend based on config."""
    if config.is_groq:
        return _load_groq(config, emit)
    if config.is_openai:
        return _load_openai(config, emit)
    if config.is_openvino:
        return _load_openvino(config, emit)
    if config.is_openvino_genai:
        return _load_openvino_genai(config, emit)
    return _load_faster_whisper(config, emit)


# ═══════════════════════════════════════════════════════════
#  Worker entry point
# ═══════════════════════════════════════════════════════════

def worker_main(
    config: "WhisperConfig",
    in_queue: mp.Queue,
    out_queue: mp.Queue,
):
    """Entry point for the worker process.

    Args:
        config:    a WhisperConfig instance (must be picklable — dataclass is).
        in_queue:  receives WAV paths or _Cmd.STOP / _Cmd.PING.
        out_queue: emits event dicts back to main process.
    """

    # 🛡️ Graceful shutdown flag
    _shutdown_requested = {"flag": False}

    def _handle_signal(signum, _frame):
        """Mark for shutdown — we'll exit at next safe point."""
        _shutdown_requested["flag"] = True
        try:
            out_queue.put({
                "event": "shutdown_signal",
                "signum": signum,
                "message": f"⚠️ Worker received signal {signum}, shutting down…",
            })
        except Exception:
            pass

    # 🔌 Register signal handlers (SIGTERM = polite kill, SIGINT = Ctrl+C)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
    except (ValueError, OSError):
        # Some platforms / threading contexts disallow this — that's fine
        pass

    def emit(event: str, **data):
        """Push an event back to the main process."""
        try:
            out_queue.put({"event": event, **data})
        except Exception:
            pass

    # ── Phase 1: load model ──────────────────────────────
    try:
        model, load_time = _load_model(config, emit)
    except Exception as e:
        traceback.print_exc()
        print(config.to_kwargs())
        emit("model_failed",
             message=f"{e}",
             traceback=traceback.format_exc())
        _safe_cleanup(None, emit)
        return

    if _shutdown_requested["flag"]:
        # 🛑 Killed during loading — clean up and exit
        _safe_cleanup(model, emit)
        return

    emit("model_ready", load_time=load_time)

    # ── Phase 2: pre-extract transcription parameters ────
    beam_size = config.beam_size
    language = (config.language or "").strip() or None
    initial_prompt = (config.initial_prompt or "").strip() or None
    no_speech_text = (config.no_speech_text or "").strip() or None
    # OpenVINO path doesn't support faster-whisper's VAD filter
    vad_filter = not (config.is_openvino or config.is_groq)

    # ── Phase 3: consume queue ───────────────────────────
    while not _shutdown_requested["flag"]:
        try:
            item = in_queue.get(timeout=0.5)  # ⏱️ poll for shutdown flag
        except (EOFError, KeyboardInterrupt):
            break
        except Exception:
            continue  # queue.Empty etc.

        # 🛑 Shutdown
        if item == _Cmd.STOP:
            emit("stopped")
            break
        if item == _Cmd.PING:
            emit("pong")
            continue

        wav_path = str(item)

        if not Path(wav_path).exists():
            emit("transcription_failed",
                 wav_path=wav_path,
                 message=f"WAV not found: {wav_path}")
            continue

        emit("transcription_started", wav_path=wav_path)

        # ✂️ Optional VAD pre-trim (cuts silence before transcription)
        wav_to_transcribe = wav_path
        vad_stats = None
        if getattr(config, "vad_pretrim", False):
            try:
                from pyqttyai.audio.vad_preprocessor import vad_trim
                emit("progress", message="✂️ Running VAD pre-trim…")
                wav_to_transcribe, vad_stats = vad_trim(
                    wav_path,
                    threshold=config.vad_threshold,
                    speech_pad_ms=config.vad_speech_pad_ms,
                    min_silence_ms=config.vad_min_silence_ms,
                )
                if vad_stats.get("reason") == "no_speech_detected":
                    # 🤐 Skip transcription entirely
                    emit("transcribed",
                            wav_path=wav_path,
                            text=no_speech_text or "",
                            language="",
                            language_probability=0.0,
                            language_was_forced=False,
                            all_language_probs=None,
                            duration=vad_stats["original_duration"],
                            load_time=load_time,
                            transcribe_time=0.0,
                            rtf=0.0,
                            vad_stats=vad_stats)
                    try:
                        Path(wav_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                    if _shutdown_requested["flag"]:
                        break
                    continue
                if not vad_stats.get("skipped"):
                    emit("progress",
                            message=f"✂️ VAD: "
                                    f"{vad_stats['original_duration']:.1f}s → "
                                    f"{vad_stats['trimmed_duration']:.1f}s "
                                    f"({vad_stats['ratio']:.0%})")
            except Exception as e:
                traceback.print_exc()
                emit("progress", message=f"⚠ VAD skipped: {e}")
                wav_to_transcribe = wav_path
                vad_stats = None

        try:
            print("_transcribe_one:", {"model":model, "wav_path":wav_to_transcribe, "load_time":load_time, "beam_size":beam_size, "language":language, "vad_filter":vad_filter, "initial_prompt":initial_prompt, "no_speech_text":no_speech_text, "emit":emit,})
            _transcribe_one(
                model=model,
                wav_path=wav_to_transcribe,
                load_time=load_time,
                beam_size=beam_size,
                language=language,
                # 🔑 If we already pre-trimmed, disable built-in VAD
                vad_filter=False if (vad_stats and not vad_stats.get("skipped"))
                            else vad_filter,
                initial_prompt=initial_prompt,
                no_speech_text=no_speech_text,
                emit=emit,
                vad_stats=vad_stats,
            )
        except Exception as e:
            traceback.print_exc()
            emit("transcription_failed",
                    wav_path=wav_path,
                    message=f"Transcription failed: {e}",
                    traceback=traceback.format_exc())
        finally:
            # 🧹 Clean up original + (optionally) trimmed WAV
            try:
                Path(wav_path).unlink(missing_ok=True)
                if (wav_to_transcribe != wav_path
                        and not getattr(config, "vad_keep_temp", False)):
                    Path(wav_to_transcribe).unlink(missing_ok=True)
            except OSError:
                pass

        # 🛑 Check between jobs
        if _shutdown_requested["flag"]:
            break

    # ── Phase 4: graceful cleanup ────────────────────────
    _safe_cleanup(model, emit)


def _safe_cleanup(model, emit):
    """Release model resources cleanly. Never raises."""
    emit("worker_cleanup", message="🧹 Releasing model…")
    try:
        if model is not None:
            # 🎮 Free GPU memory if applicable
            if hasattr(model, "model") and hasattr(model.model, "to"):
                try:
                    model.model.to("cpu")
                except Exception:
                    pass
            del model
        # 🧽 Force GC to release native handles
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    except Exception as e:
        emit("worker_cleanup", message=f"⚠️ Cleanup warning: {e}")

    emit("worker_exit", message="👋 Worker exiting cleanly")


# ═══════════════════════════════════════════════════════════
#  Single-file transcription (backend-agnostic)
# ═══════════════════════════════════════════════════════════

def _process_word_timestamps_srt(segments):
    """Create SRT output"""
    chunk: int
    start: float
    line_chars: int
    line: list

    def hmsf(seconds: float):
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds_part = divmod(remainder, 60)
        secs = int(seconds_part)
        millis = int(round((seconds_part % 1) * 1000))
        return f"{int(hours):02}:{int(minutes):02}:{secs:02},{millis:03}"

    print('=' * 50 + ' SRT ' + '=' * 50, flush=True)
    chunk = 1
    for segment in segments:
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}", flush=True)
        start = segment.start
        line_chars = 0
        line = []
        for word in segment.words:
            w = word.word.strip()
            if line_chars + len(w) >= 42:
                line.append('\n')
                line_chars = len(w)
            else:
                line_chars += 1 + len(w)
            line.append(w)
            if start == 0:
                start = word.start
            if w[-1] in ('.', '!', '?') or line.count('\n') == 2:
                if line.count('\n') == 2:
                    print_line = (' '.join(line[:-2])).replace(' \n ', '\n')
                    line = [w]
                else:
                    print_line = (' '.join(line)).replace(' \n ', '\n')
                    end = word.end
                    line = []
                print(f"{chunk}\n{hmsf(start)} --> {hmsf(end)}\n{print_line}\n", flush=True)
                start = word.start if line else 0
                chunk += 1
                line_chars = len(line[0]) if line else 0
            end = word.end
        if start > 0:
            print_line = (' '.join(line)).replace('\n ', '\n').strip()
            print(f"{chunk}\n{hmsf(start)} --> {hmsf(segment.end)}\n{print_line}\n", flush=True)
            chunk += 1
    print('=' * 100)

def _transcribe_one(
    model: Any,
    wav_path: str,
    load_time: float,
    beam_size: int,
    language: str | None,
    vad_filter: bool,
    initial_prompt: str | None,
    no_speech_text: str | None,
    emit,
    vad_stats: dict | None = None,
    word_timestamps: bool = False,
):
    """Transcribe one WAV file and emit the result.

    Both faster-whisper and your OpenVINO wrapper expose a `.transcribe()`
    method returning `(segments, info)` — same shape, so this is unified.
    """
    if language:
        emit("progress", message=f"🎙️ Transcribing in {language}…")
    else:
        emit("progress", message="🎙️ Transcribing (auto-detect)…")

    kwargs: dict[str, Any] = {
        "beam_size": beam_size,
        "vad_filter": vad_filter,
    }
    if language:
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    if word_timestamps:
        kwargs["word_timestamps"] = word_timestamps

    print('_' * 100)
    print(wav_path, kwargs)
    print('·' * 100)

    t0 = time.time()
    segments, info = model.transcribe(wav_path, **kwargs)

    if word_timestamps:
        _process_word_timestamps_srt(segments)

    text_parts = [seg.text for seg in segments]
    transcribe_time = time.time() - t0

    print('+' * 100, transcribe_time)
    print(wav_path, segments, info)
    if hasattr(model, "_client") and hasattr(model, "_model_id"):
        print(
            wav_path,
            [{s: getattr(segment, s) for s in segment.__slots__ if hasattr(segment, s)}
                for segment in segments],
            {s: getattr(info, s) for s in info.__slots__ if hasattr(info, s)}
        )
    print('‾' * 100)

    full_text = " ".join(p.strip() for p in text_parts).strip()

    emit(
        "transcribed",
        wav_path=wav_path,
        text=full_text or no_speech_text or "",
        language=info.language,
        language_probability=info.language_probability,
        language_was_forced=bool(language),
        all_language_probs=info.all_language_probs,
        duration=info.duration,
        load_time=load_time,
        transcribe_time=transcribe_time,
        rtf=(transcribe_time / info.duration) if info.duration > 0 else 0.0,
        vad_stats=vad_stats,
    )
