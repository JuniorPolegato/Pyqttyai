"""Audio recorder with live level monitoring for VU meter."""

import tempfile
import wave
import struct

from PyQt6.QtCore import (
    QObject, pyqtSignal, QByteArray, QBuffer, QIODevice, QTimer,
)
from PyQt6.QtMultimedia import QAudioSource, QMediaDevices, QAudioFormat


class AudioRecorder(QObject):
    """Records mic audio to a WAV file with live level monitoring."""

    finished = pyqtSignal(str)         # path to .wav file
    level_changed = pyqtSignal(float)  # 🎚️ 0.0 .. 1.0 (RMS level)
    error = pyqtSignal(str)            # 🚨 error message

    SAMPLE_RATE = 16000  # 🎯 Whisper-friendly
    LEVEL_INTERVAL_MS = 50  # 🎚️ ~20 fps VU meter

    def __init__(self, parent=None):
        super().__init__(parent)

        fmt = QAudioFormat()
        fmt.setSampleRate(self.SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self._source = None
            self._available = False
        else:
            self._source = QAudioSource(device, fmt)
            self._available = True

        self._buffer = QBuffer()
        self._is_recording = False

        # 🎚️ Level monitoring timer
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(self.LEVEL_INTERVAL_MS)
        self._level_timer.timeout.connect(self._emit_level)
        self._last_read_pos = 0

    @property
    def is_available(self) -> bool:
        """True if a microphone was detected."""
        return self._available

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start(self) -> bool:
        """Start recording. Returns True on success."""
        print(f"self._available: {self._available} | self._is_recording: {self._is_recording}")
        if not self._available or self._is_recording:
            return False

        # Reset buffer
        self._buffer = QBuffer()
        self._buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self._last_read_pos = 0

        self._source.start(self._buffer)

        # Check that it actually started
        if self._source.error().value != 0:
            self.error.emit(f"Audio source error: {self._source.error()}")
            return False

        self._is_recording = True
        self._level_timer.start()
        return True

    def stop(self, silent=False) -> str | None:
        """Stop recording and write WAV. Returns path or None on failure."""
        if not self._is_recording:
            return None

        self._level_timer.stop()
        self._source.stop()
        self._is_recording = False

        # Get raw PCM data
        raw = bytes(self._buffer.data())
        self._buffer.close()

        if not raw:
            self.error.emit("No audio captured (empty buffer).")
            return None

        # 💾 Save to temp WAV
        try:
            path = tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False, prefix="pyqttyai_test_",
            ).name
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(raw)
        except (OSError, wave.Error) as e:
            self.error.emit(f"Failed to write WAV: {e}")
            return None

        self.finished.emit(path)
        return path

    # ── Level monitoring ──────────────────────────────────

    def _emit_level(self):
        """Compute RMS of newest samples and emit normalized level."""
        if not self._is_recording:
            return

        data = self._buffer.data()
        total = data.size()

        # 🎯 Read only NEW samples since last tick
        new_bytes = total - self._last_read_pos
        if new_bytes < 2:
            return
        # Make new_bytes even (16-bit samples)
        new_bytes = new_bytes - (new_bytes % 2)

        chunk = bytes(data)[self._last_read_pos:self._last_read_pos + new_bytes]
        self._last_read_pos += new_bytes

        # Compute RMS for 16-bit signed PCM
        sample_count = len(chunk) // 2
        if sample_count == 0:
            return

        try:
            samples = struct.unpack(f"<{sample_count}h", chunk)
        except struct.error:
            return

        # RMS normalized to 0..1
        sum_sq = sum(s * s for s in samples)
        rms = (sum_sq / sample_count) ** 0.5
        level = min(1.0, rms / 32768.0 * 4)  # 🎚️ scale up for visibility

        self.level_changed.emit(level)
