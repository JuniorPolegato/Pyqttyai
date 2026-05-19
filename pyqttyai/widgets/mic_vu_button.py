"""Microphone button with integrated VU meter and broker-aware claim protocol.

🎙️ This widget OWNS its own AudioRecorder. The TranscriptionService is just
the broker + transcribe-WAV pipeline; it does NOT touch audio devices.

Lifecycle:
    click → request(self) → (broker grants) → recorder.start() → 🎚️ VU
    click again → recorder.stop() → finished(wav) → service.enqueue(wav)
                                                   → transcribed → text_ready
                                                   → release(self)
"""

import time
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen
from PyQt6.QtWidgets import QWidget

from pyqttyai.audio.recorder import AudioRecorder


class VuPosition(Enum):
    TOP = auto()
    BOTTOM = auto()
    LEFT = auto()
    RIGHT = auto()
    NONE = auto()


class VuShape(Enum):
    THIN_VERTICAL = auto()
    THIN_HORIZONTAL = auto()
    SQUARE = auto()


class VuFill(Enum):
    VERTICAL = auto()
    HORIZONTAL = auto()


class MicStatus(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()
    ERROR = auto()


# 🎨 Catppuccin Mocha palette
_BG_NORMAL   = QColor("#313244")
_BG_HOVER    = QColor("#585b70")
_BG_DISABLED = QColor("#1e1e2e")
_TRACK       = QColor("#11111b")
_MIC_ON      = QColor("#a6e3a1")
_MIC_OFF     = QColor("#a6adc8")
_MIC_DIS     = QColor("#45475a")
_LVL_LOW     = QColor("#a6e3a1")
_LVL_MID     = QColor("#f9e2af")
_LVL_HIGH    = QColor("#f38ba8")
_DOT_IDLE    = QColor("#a6e3a1")
_DOT_REC     = QColor("#f38ba8")
_DOT_TRANS   = QColor("#f9e2af")
_DOT_ERROR   = QColor("#eba0ac")


class MicVuButton(QWidget):
    """🎙️ Universal mic button: owns a recorder, coordinates via broker."""

    # 📡 Public signals
    toggled        = pyqtSignal(bool)
    enable_changed = pyqtSignal(bool)
    transcribed    = pyqtSignal(dict)
    text_ready     = pyqtSignal(str)
    failed         = pyqtSignal(object)
    status_changed = pyqtSignal(object)
    recorder_error = pyqtSignal(str)   # 🆕 surfaced from AudioRecorder

    # 🔧 Re-export enums
    Position = VuPosition
    Shape    = VuShape
    Fill     = VuFill
    Status   = MicStatus

    def __init__(
        self,
        service,
        parent=None,
        *,
        position: VuPosition = VuPosition.RIGHT,
        shape: VuShape = VuShape.THIN_VERTICAL,
        fill_direction: Optional[VuFill] = None,
        auto_enable: bool = True,
        noise_level: float = 0.15,
        auto_transcribe_idle_seconds: float = float('inf'),
    ):
        super().__init__(parent)

        self._service = service
        self._position = position
        self._shape = shape
        self._fill = fill_direction or self._auto_fill(position, shape)
        self._auto_enable = auto_enable
        self._noise_level = max(0.05, min(noise_level, 0.95))
        self._auto_transcribe_idle_seconds = (
            float('inf') if auto_transcribe_idle_seconds < 0
            else auto_transcribe_idle_seconds)
        self._last_audio_timestamp = float('inf')

        # 🚦 State
        self._enabled_for_mic: bool = False
        self._pending_request: bool = False
        self._level: float = 0.0
        self._hover: bool = False
        self._status: MicStatus = MicStatus.IDLE
        self._awaiting_transcriptions: int = 0  # count of transcriptions awaiting

        # 🎙️ Per-button recorder (lazy-init so we don't hold a stream we don't need)
        self._recorder: Optional[AudioRecorder] = None
        self._init_recorder()

        # 🎨 UI
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("🎙️ Voice Recognition (click to toggle)")
        self.setFixedSize(self._compute_size())

        # 📉 Decay timer
        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(40)
        self._decay_timer.timeout.connect(self._decay_step)

        # 🔌 Broker / service wiring
        self._service.release_requested.connect(self._on_release_requested)
        self._service.granted.connect(self._on_service_granted)
        self._service.transcribed.connect(self._on_transcribed)
        self._service.transcription_failed.connect(self._on_failed)

    # ── Recorder setup ───────────────────────────────────────

    def _init_recorder(self) -> None:
        """🎙️ Create the per-button recorder and wire its signals."""
        self._recorder = AudioRecorder(self)

        if not self._recorder.is_available:
            self.setEnabled(False)
            self.setToolTip(
                "🚫 No microphone detected.\n"
                "Connect a mic and restart the app."
            )
            self._recorder = None
            return

        self._recorder.level_changed.connect(self._on_level)
        self._recorder.finished.connect(self._on_recording_saved)
        self._recorder.error.connect(self._on_recorder_error)

    # ── Public API ───────────────────────────────────────────

    def set_noise_level(self, noise_level: float,
            auto_transcribe_idle_seconds: float = -1):
        """Noise level threshold between idle and recording,
           optional set auto_transcribe_idle_seconds >= 0."""
        self._noise_level = max(0.05, min(noise_level, 0.95))
        if auto_transcribe_idle_seconds < 0:
            return
        self._auto_transcribe_idle_seconds = auto_transcribe_idle_seconds

    def is_active(self) -> bool:
        return self._enabled_for_mic

    def set_active(self, active: bool) -> None:
        """Programmatic enable/disable. Goes through the broker."""
        if active == self._enabled_for_mic and not self._pending_request:
            return
        if active:
            self._request_mic()
        else:
            self._release_mic()

    def set_status(self, status: MicStatus) -> None:
        self._set_status(status)

    # ── Broker protocol ──────────────────────────────────────

    def _request_mic(self) -> None:
        """Ask the broker to grant us the mic."""
        if self._enabled_for_mic or self._recorder is None:
            return
        self._pending_request = True
        self._service.request(self)
        # _on_service_granted will fire when broker grants us

    def _release_mic(self) -> None:
        """User toggled off (or eviction). Stop recording cleanly."""
        if not self._enabled_for_mic and not self._pending_request:
            return

        was_active = self._enabled_for_mic
        self._pending_request = False

        # 🛑 If we were actively recording, finalize the WAV now.
        #    finished() → _on_recording_saved → enqueue → wait for transcribed.
        if was_active and self._recorder is not None and self._recorder.is_recording:
            self._set_status(MicStatus.TRANSCRIBING)
            self._recorder.stop()  # async-ish: finished signal fires
            # 🤚 Keep the broker claim until pipeline drains
            self._enabled_for_mic = False
            self._decay_timer.stop()
            self._level = 0.0
            self.enable_changed.emit(False)
            self.update()
            return

        # No active recording → release immediately
        self._enabled_for_mic = False
        self._decay_timer.stop()
        self._level = 0.0
        self._set_status(MicStatus.IDLE)
        self._service.release(self)
        if was_active:
            self.enable_changed.emit(False)
        self.update()

    def _on_granted(self) -> None:
        """Broker confirmed: we own the mic. Start capturing."""
        if self._enabled_for_mic or self._recorder is None:
            return

        self._enabled_for_mic = True
        self._pending_request = False
        self._set_status(MicStatus.IDLE)

        # 🎬 Start capturing audio
        if not self._recorder.start():
            # Recorder couldn't start → release and surface the error
            self._set_status(MicStatus.ERROR)
            self._service.release(self)
            self._enabled_for_mic = False
            self.enable_changed.emit(False)
            return

        self._decay_timer.start()
        self.enable_changed.emit(True)
        self.update()

    def _on_release_requested(self, requester) -> None:
        """Broker says someone else wants the mic — yield gracefully."""
        if requester is self:
            return
        if self._enabled_for_mic or self._pending_request:
            self._release_mic()

    def _on_service_granted(self, borrower) -> None:
        if borrower is self and not self._enabled_for_mic:
            self._on_granted()

    # ── Recorder signal handlers ─────────────────────────────

    def _on_level(self, rms: float) -> None:
        """🎚️ Recorder pushed a new level — update VU."""
        if not self._enabled_for_mic:
            return
        clamped = max(0.0, min(1.0, rms))
        self._level = max(self._level, clamped)

        now = time.time()
        print(f"{now % 100:.2f} | {clamped:.2f} | {now - self._last_audio_timestamp:.2f}")
        if clamped > self._noise_level:
            self._last_audio_timestamp = now
            if self._status not in (MicStatus.TRANSCRIBING, MicStatus.RECORDING):
                self._set_status(MicStatus.RECORDING)
        elif now - self._last_audio_timestamp >= self._auto_transcribe_idle_seconds:
            self._set_status(MicStatus.TRANSCRIBING)
            self._recorder.stop()
            self._recorder.start()
            self._last_audio_timestamp = float('inf')
        elif self._status not in (MicStatus.TRANSCRIBING, MicStatus.IDLE):
            self._set_status(MicStatus.IDLE)
        self.update()

    def _on_recording_saved(self, wav_path: str) -> None:
        """💾 Recorder finished writing → hand WAV to the service."""
        if not wav_path:
            return

        if not self._service.is_running:
            self._on_recorder_error("No transcription service.")
            return None

        # 🧠 Send to transcription pipeline — we keep the broker claim
        #    until transcribed/failed comes back.
        self._set_status(MicStatus.TRANSCRIBING)
        self._awaiting_transcriptions += 1
        self._service.enqueue(wav_path)

    def _on_recorder_error(self, message: str) -> None:
        """⚠️ Recorder-side failure (device gone, write error, etc.)."""
        self._set_status(MicStatus.ERROR)
        self._enabled_for_mic = False
        self._pending_request = False
        self._decay_timer.stop()
        self._level = 0.0
        self._service.release(self)
        self.enable_changed.emit(False)
        self.recorder_error.emit(message)
        QTimer.singleShot(1500, self._clear_error_status)
        self.update()

    # ── Service signal handlers ──────────────────────────────

    def _on_transcribed(self, result) -> None:
        """Only the *waiting* button consumes the result."""
        if not (self._enabled_for_mic or self._awaiting_transcriptions):
            return
        self._awaiting_transcriptions -= 1
        self._set_status(MicStatus.IDLE)

        text = result.get("text", "") if isinstance(result, dict) else str(result)
        self.transcribed.emit(result)
        if text:
            self.text_ready.emit(text)

        if self._recorder.is_recording:
            return

        # 🤝 Now safe to let go of the broker claim
        self._service.release(self)
        if self._enabled_for_mic:
            self._enabled_for_mic = False
            self.enable_changed.emit(False)
        self.update()

    def _on_failed(self, wav_path: str, error: str) -> None:
        """Transcription pipeline failed for our WAV."""
        if not (self._enabled_for_mic or self._awaiting_transcriptions):
            return
        self._awaiting_transcriptions -= 1
        self._set_status(MicStatus.ERROR)
        self.failed.emit(error)
        self._service.release(self)
        if self._enabled_for_mic:
            self._enabled_for_mic = False
            self.enable_changed.emit(False)
        QTimer.singleShot(1500, self._clear_error_status)
        self.update()

    def _clear_error_status(self) -> None:
        if self._status == MicStatus.ERROR:
            self._set_status(MicStatus.IDLE)

    # ── Mouse / hover ────────────────────────────────────────

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._enabled_for_mic:
                self._release_mic()
                self.toggled.emit(False)
            else:
                if self._auto_enable and self._recorder is not None:
                    self._request_mic()
                    self.toggled.emit(True)
            event.accept()
            return
        super().mousePressEvent(event)

    # ── Internal helpers ─────────────────────────────────────

    def _set_status(self, status: MicStatus) -> None:
        if status == self._status:
            return
        self._status = status
        self.status_changed.emit(status)
        self.update()

    def _decay_step(self) -> None:
        self._level *= 0.85
        if self._level < 0.01:
            self._level = 0.0
        self.update()

    @staticmethod
    def _auto_fill(position: VuPosition, shape: VuShape) -> VuFill:
        if shape == VuShape.THIN_HORIZONTAL:
            return VuFill.HORIZONTAL
        if shape == VuShape.THIN_VERTICAL:
            return VuFill.VERTICAL
        if position in (VuPosition.LEFT, VuPosition.RIGHT):
            return VuFill.HORIZONTAL
        return VuFill.VERTICAL

    # ── Geometry / Painting (unchanged) ──────────────────────

    def _compute_size(self) -> QSize:
        icon_w, icon_h = 32, 32
        bar_long, bar_short = 36, 14
        gap = 4

        if self._position == VuPosition.NONE:
            return QSize(icon_w + 16, icon_h + 16)

        if self._shape == VuShape.SQUARE:
            bw = bh = 28
        elif self._shape == VuShape.THIN_VERTICAL:
            bw, bh = bar_short, bar_long
        else:
            bw, bh = bar_long, bar_short

        if self._position in (VuPosition.LEFT, VuPosition.RIGHT):
            w = icon_w + gap + bw + 12
            h = max(icon_h, bh) + 12
        else:
            w = max(icon_w, bw) + 12
            h = icon_h + gap + bh + 12
        return QSize(w, h)

    def _layout_rects(self) -> tuple[QRect, QRect]:
        w, h = self.width(), self.height()
        icon_w, icon_h = 32, 32
        gap = 4
        border = 6

        if self._position == VuPosition.NONE:
            icon_x = (w - icon_w) // 2
            icon_y = (h - icon_h) // 2
            return QRect(icon_x, icon_y, icon_w, icon_h), QRect()

        if self._shape == VuShape.SQUARE:
            bw = bh = min(w - 2 * gap - icon_w, h - 2 * gap - icon_h)
        elif self._shape == VuShape.THIN_VERTICAL:
            bw = 14
            if self._position in (VuPosition.RIGHT, VuPosition.LEFT):
                bh = h - 2 * border
            else:
                bh = h - gap - icon_h - 2 * border
        else:
            bh = 14
            if self._position in (VuPosition.RIGHT, VuPosition.LEFT):
                bw = w - gap - icon_w - 2 * border
            else:
                bw = w - 2 * border

        if self._position == VuPosition.RIGHT:
            icon_r = QRect(6, (h - icon_h) // 2, icon_w, icon_h)
            bar_r  = QRect(icon_r.right() + gap, (h - bh) // 2, bw, bh)
        elif self._position == VuPosition.LEFT:
            bar_r  = QRect(6, (h - bh) // 2, bw, bh)
            icon_r = QRect(bar_r.right() + gap, (h - icon_h) // 2, icon_w, icon_h)
        elif self._position == VuPosition.BOTTOM:
            icon_r = QRect((w - icon_w) // 2, 6, icon_w, icon_h)
            bar_r  = QRect((w - bw) // 2, icon_r.bottom() + gap, bw, bh)
        else:
            bar_r  = QRect((w - bw) // 2, 6, bw, bh)
            icon_r = QRect((w - icon_w) // 2, bar_r.bottom() + gap, icon_w, icon_h)
        return icon_r, bar_r

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if not self.isEnabled():
            bg = _BG_DISABLED
        elif self._hover:
            bg = _BG_HOVER
        else:
            bg = _BG_NORMAL
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 2, w - 4, h - 4, 6, 6)

        icon_rect, bar_rect = self._layout_rects()
        self._paint_mic_icon(p, icon_rect)
        if self._position != VuPosition.NONE and bar_rect.isValid():
            self._paint_vu_bar(p, bar_rect)
        self._paint_status_dot(p)
        p.end()

    def _paint_mic_icon(self, p: QPainter, rect: QRect) -> None:
        if not self.isEnabled():
            color = _MIC_DIS
        else:
            color = _MIC_ON if self._enabled_for_mic else _MIC_OFF

        cx = rect.center().x() + 1
        top = rect.top()
        mic_w = 14
        mic_h = 18
        mic_x = cx - mic_w // 2
        mic_y = top + 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(mic_x, mic_y, mic_w, mic_h, 6, 6)

        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc_x = mic_x - 4
        arc_y = mic_y + mic_h - 6
        p.drawArc(arc_x, arc_y, mic_w + 8, 10, 180 * 16, 180 * 16)
        p.drawLine(cx, arc_y + 8, cx, rect.bottom() - 4)
        p.drawLine(cx - 4, rect.bottom() - 4, cx + 4, rect.bottom() - 4)

    def _paint_vu_bar(self, p: QPainter, rect: QRect) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_TRACK))
        p.drawRoundedRect(rect, 3, 3)

        if not (self._enabled_for_mic and self._level > 0.0):
            return

        if self._level < 0.5:
            color = _LVL_LOW
        elif self._level < 0.8:
            color = _LVL_MID
        else:
            color = _LVL_HIGH
        p.setBrush(QBrush(color))

        if self._fill == VuFill.VERTICAL:
            fill_h = int(rect.height() * self._level)
            fill_y = rect.bottom() - fill_h + 1
            p.drawRoundedRect(rect.x(), fill_y, rect.width(), fill_h, 3, 3)
        else:
            fill_w = int(rect.width() * self._level)
            p.drawRoundedRect(rect.x(), rect.y(), fill_w, rect.height(), 3, 3)

    def _paint_status_dot(self, p: QPainter) -> None:
        if self._status == MicStatus.RECORDING:
            color = _DOT_REC
        elif self._status == MicStatus.TRANSCRIBING:
            color = _DOT_TRANS
        elif self._status == MicStatus.ERROR:
            color = _DOT_ERROR
        else:
            color = _DOT_IDLE
        if not self._enabled_for_mic:
            color = QColor(color.red(), color.green(), color.blue(), 90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(5, 5, 6, 6)

    def sizeHint(self) -> QSize:
        return self._compute_size()
