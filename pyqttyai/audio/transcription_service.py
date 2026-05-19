"""Persistent transcription service running in a separate OS process.

The main process talks to a worker process via two queues:
- in_queue:  WAV file paths (and STOP command)
- out_queue: events (model_ready, transcribed, errors, etc.)

A small QThread in the main process reads from out_queue and emits Qt signals.
"""

import multiprocessing as mp
from dataclasses import asdict, is_dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal

from pyqttyai.core.whisper_config import WhisperConfig
from pyqttyai.audio.transcription_worker_process import worker_main, _Cmd


# ═══════════════════════════════════════════════════════════
#  Reader thread — drains out_queue and re-emits as Qt signals
# ═══════════════════════════════════════════════════════════

class _QueueReader(QThread):
    """Tiny QThread that pulls events from the worker's out_queue
    and turns them into Qt signals on the main thread."""

    event = pyqtSignal(dict)

    def __init__(self, out_queue: mp.Queue, parent=None):
        super().__init__(parent)
        self._out_queue = out_queue
        self._running = True

    def run(self):
        while self._running:
            try:
                # ⏱️ Short timeout so we can react to stop() quickly
                msg = self._out_queue.get(timeout=0.1)
            except Exception:
                # Queue empty (timeout) OR closed — re-check running flag
                continue

            if msg is None:
                break

            # 🛡️ Don't emit if we're shutting down
            if not self._running:
                break

            self.event.emit(msg)

    def stop(self):
        """Request stop — caller must wait() afterwards."""
        self._running = False


# ═══════════════════════════════════════════════════════════
#  Service — public API
# ═══════════════════════════════════════════════════════════

class TranscriptionService(QObject):
    """Persistent Whisper service in a separate OS process.

    Usage:
        svc = TranscriptionService()
        svc.start(config)              # 🧠 spawns worker, loads model
        svc.enqueue("/tmp/clip1.wav")  # 📥 queue a file
        svc.enqueue("/tmp/clip2.wav")
        svc.stop()                     # 🛑 kill worker, free memory
        svc.restart(new_config)        # 🔄 reload with new model
    """

    # ── Signals (mirror the worker events) ──
    model_loading = pyqtSignal(str)
    model_ready = pyqtSignal(str, float)
    model_failed = pyqtSignal(str)

    transcription_started = pyqtSignal(str)         # wav_path
    transcribing = pyqtSignal(str)                  # progress message during a
    transcribed = pyqtSignal(dict)                  # full result dict
    transcription_failed = pyqtSignal(str, str)     # wav_path, message

    queue_size_changed = pyqtSignal(int)

    # 🔑 Cloud backend needs an API key
    api_key_required = pyqtSignal(str, str, str)   # provider, env_var, message

    release_requested = pyqtSignal(object)  # emitted with the requester
    idle              = pyqtSignal()        # emitted when fully quiescent
    granted           = pyqtSignal(object)  # emitted with the new active_borrower

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config: Optional[WhisperConfig] = None
        self._process: Optional[mp.Process] = None
        self._in_queue: Optional[mp.Queue] = None
        self._out_queue: Optional[mp.Queue] = None
        self._reader: Optional[_QueueReader] = None
        self._pending_count = 0
        self._model_loaded = False
        self._load_time: float = 0
        self._active_borrower = None
        self._pending_requester = None

    # ── Properties ────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.is_alive()

    @property
    def is_model_loaded(self) -> bool:
        return self._model_loaded

    def matches_config(self, cfg: WhisperConfig) -> bool:
        if not self._config:
            return False
        c = self._config
        return (
            c.model == cfg.model
            and c.device == cfg.device
            and c.compute_type == cfg.compute_type
            and c.cpu_threads == cfg.cpu_threads
        )

    # ── Lifecycle ─────────────────────────────────────────

    def start(self, config: WhisperConfig):
        """Spawn the worker process and start loading the model."""
        if self.is_running:
            return

        self._config = config
        self._model_loaded = False
        self._pending_count = 0

        # 🌐 Use 'spawn' for cross-platform consistency
        ctx = mp.get_context("spawn")
        self._in_queue = ctx.Queue()
        self._out_queue = ctx.Queue()

        # 🚀 Pass the config object directly — dataclass is picklable
        self._process = ctx.Process(
            target=worker_main,
            args=(config, self._in_queue, self._out_queue),
            daemon=True,
        )
        self._process.start()

        self._reader = _QueueReader(self._out_queue, self)
        self._reader.event.connect(self._on_event)
        self._reader.start()

    def enqueue(self, wav_path: str):
        """Send a WAV path to the worker for transcription."""
        if not self.is_running or self._in_queue is None:
            return
        try:
            self._in_queue.put(wav_path)
            self._pending_count += 1
            self.queue_size_changed.emit(self._pending_count)
        except (ValueError, OSError) as e:
            # Queue already closed — silently drop
            print('enqueue error:', e)

    def stop(self, timeout: float = 5.0):
        """Stop the worker and free all resources (safe at any state)."""
        # ── Step 1: tell worker to exit ─────────────────────
        if self.is_running and self._in_queue is not None:
            try:
                self._in_queue.put(_Cmd.STOP)
            except (ValueError, OSError):
                pass  # queue already closed

        # ── Step 2: stop the reader BEFORE closing queues ──
        if self._reader is not None:
            self._reader.stop()
            # 🛡️ Wait until reader thread truly exits — prevents
            #     "QThread: Destroyed while thread is still running"
            if not self._reader.wait(2000):
                # Last-resort: terminate (very rare, but better than crash)
                self._reader.terminate()
                self._reader.wait(1000)
            self._reader.deleteLater()
            self._reader = None

        # ── Step 3: wait for worker process ─────────────────
        if self._process is not None:
            if self._process.is_alive():
                self._process.join(timeout=timeout)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=2.0)
                    if self._process.is_alive():
                        self._process.kill()
                        self._process.join(timeout=1.0)
            self._process = None

        # ── Step 4: close queues (releases semaphores!) ─────
        self._close_queues()

        # ── Reset state ─────────────────────────────────────
        self._model_loaded = False
        self._pending_count = 0
        self._config = None

    def _close_queues(self):
        """Close + join multiprocessing queues to release semaphores."""
        for q_attr in ("_in_queue", "_out_queue"):
            q = getattr(self, q_attr, None)
            if q is None:
                continue
            try:
                q.close()
                q.join_thread()  # 🔑 THIS releases the semaphores!
            except Exception:
                pass
            setattr(self, q_attr, None)

    def restart(self, new_config: WhisperConfig):
        """Stop the worker and start a fresh one with new config."""
        self.stop()
        self.start(new_config)

    # ── Internal ──────────────────────────────────────────

    def _cleanup(self):
        if self._reader:
            self._reader.stop()
            self._reader.wait(2000)
            self._reader.deleteLater()
            self._reader = None

        for q in (self._in_queue, self._out_queue):
            if q is not None:
                try:
                    q.close()
                except Exception:
                    pass

        self._in_queue = None
        self._out_queue = None
        self._process = None
        self._model_loaded = False
        self._pending_count = 0

    def _on_event(self, msg: dict):
        """Translate worker events into Qt signals."""
        kind = msg.get("event")

        if kind == "model_loading":
            self.model_loading.emit(msg.get("message", ""))

        elif kind == "api_key_required":
            self.api_key_required.emit(
                msg.get("provider", ""),
                msg.get("env_var", ""),
                msg.get("message", ""),
            )

        elif kind == "model_ready":
            self._model_loaded = True
            self._load_time = msg.get("load_time", 0.0)
            self.model_ready.emit(self._config.model, self._load_time)

        elif kind == "model_failed":
            self.model_failed.emit(msg.get("message", "Unknown error"))

        elif kind == "progress":  # 🆕 mid-transcription updates
            self.transcribing.emit(msg.get("message", ""))

        elif kind == "transcription_started":
            self.transcription_started.emit(msg.get("wav_path", ""))

        elif kind == "transcribed":
            self._pending_count = max(0, self._pending_count - 1)
            self.queue_size_changed.emit(self._pending_count)
            data = {k: v for k, v in msg.items() if k != "event"}
            self.transcribed.emit(data)
            if self._pending_count == 0:
                self.idle.emit()

        elif kind == "transcription_failed":
            self._pending_count = max(0, self._pending_count - 1)
            self.queue_size_changed.emit(self._pending_count)
            self.transcription_failed.emit(
                msg.get("wav_path", ""),
                msg.get("message", "Unknown error"),
            )
            if self._pending_count == 0:
                self.idle.emit()

        elif kind == "stopped":
            pass  # worker confirmed shutdown

        elif kind in ("shutdown_signal", "worker_cleanup", "worker_exit"):
            # 🪵 Optional: forward to a debug log
            print(f"[worker] {msg.get('message', kind)}")

    # 🎯 New broker methods

    def request(self, requester) -> None:
        """Universal claim. Tells everyone else to release, then grants when idle."""
        if self._active_borrower is requester:
            return

        self._pending_requester = requester
        # 📢 Tell every listener to disconnect/stop
        self.release_requested.emit(requester)

        if self.is_idle():
            self._grant_pending()
        else:
            # one-shot: wait for idle, then grant
            self.idle.connect(
                self._grant_pending,
                Qt.ConnectionType.SingleShotConnection,
            )

    def release(self, who) -> None:
        """Drop a borrower. If it was active, mic becomes free."""
        if self._active_borrower is who:
            self._active_borrower = None
        if self._pending_requester is who:
            self._pending_requester = None

    def is_idle(self) -> bool:
        """True when queue is empty."""
        return self._pending_count == 0

    def _grant_pending(self) -> None:
        if self._pending_requester is not None:
            self._active_borrower = self._pending_requester
            self._pending_requester = None
            if not self.is_running:
                self.restart(self._config)
            self.granted.emit(self._active_borrower)
