"""Microphone + transcription test panel with parallel model loading."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional
import time

from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QSignalBlocker,
)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QComboBox,
)

from pyqttyai.core.whisper_languages import (
    AUTO_DETECT,
    POPULAR_LANGUAGES,
    WHISPER_LANGUAGES,
    is_english_only_model,
    language_display,
    sorted_language_codes,
)
from pyqttyai.core.whisper_config import WhisperConfig
from pyqttyai.audio.transcription_service import TranscriptionService
from pyqttyai.widgets.mic_vu_button import MicVuButton

# ═══════════════════════════════════════════════════════════
#  State machine
# ═══════════════════════════════════════════════════════════

class State(Enum):
    """Test panel states for clear orchestration."""
    IDLE = auto()              # 💤 Nothing happening
    LOADING_RECORDING = auto() # 🎙️⏳ Both happening in parallel
    LOADING_DONE_RECORDING = auto()  # 🎙️✅ Model ready, still recording
    RECORDING_DONE_LOADING = auto()  # 🛑⏳ Stopped recording, waiting for model
    TRANSCRIBING = auto()      # 📝 Final step
    READY_CACHED = auto()      # ⚡ Model already loaded from previous test


# ═══════════════════════════════════════════════════════════
#  Cached model holder
# ═══════════════════════════════════════════════════════════

@dataclass
class CachedModel:
    """Holds a loaded Whisper model + the config it was built with."""
    model: Any
    config: WhisperConfig
    load_time: float

    def matches(self, other: WhisperConfig) -> bool:
        """True if `other` would produce an identical model."""
        # Compare only the fields that affect model loading
        return (
            self.config.model == other.model
            and self.config.device == other.device
            and self.config.compute_type == other.compute_type
            and self.config.cpu_threads == other.cpu_threads
            and self.config.download_root == other.download_root
            and self.config.local_files_only == other.local_files_only
            and self.config.device_index == other.device_index
            and self.config.use_auth_token == other.use_auth_token
            and self.config.initial_prompt == other.initial_prompt
            and self.config.no_speech_text == other.no_speech_text
            and self.config.language == other.language
        )


# ═══════════════════════════════════════════════════════════
#  Test Panel
# ═══════════════════════════════════════════════════════════

class WhisperTestPanel(QGroupBox):
    """Mic + Whisper test with parallel model loading and caching."""

    config_requested = pyqtSignal()

    MAX_RECORD_SECONDS = 30

    def __init__(
            self,
            parent=None,
            current_config: Optional[WhisperConfig] = None,
            shared_service: Optional[TranscriptionService] = None):
        super().__init__("🧪 Test Microphone && Transcription", parent)

        # 🧵 Loader and Transcriber as a service
        # detached thread - multiprocessing
        self._service = shared_service
        self._wire_service_signals()

        # 🗃️ Cached model (survives across tests)
        self._cached: Optional[CachedModel] = (
            None if current_config is None else CachedModel(
                model=current_config.model,
                config=current_config,
                load_time=self._service._load_time
            )
        )

        # 📊 Pending state
        self._state: State = State.IDLE
        self._pending_config: Optional[WhisperConfig] = None
        self._pending_wav: Optional[str] = None
        self._pending_load_time: float = 0.0
        self._lang_dict = {'_': 0}

        # ⏱️ Recording timer
        self._elapsed_ms = 0

        # Model name passed from parent (for compat warnings)
        self._current_model_name: str = ""

        self._build_ui()

    # ── UI construction ────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(8)

        # ⚠️ Compatibility warning (hidden by default)
        self._lang_warning = QLabel("")
        self._lang_warning.setWordWrap(True)
        self._lang_warning.setStyleSheet(
            "color: #f9e2af; font-size: 11px; "
            "padding: 4px 8px; background-color: #313244; "
            "border-left: 3px solid #f9e2af; border-radius: 3px;"
        )
        self._lang_warning.setVisible(False)
        layout.addWidget(self._lang_warning)

        # ── Top row: language + button + model status badge + timer ──
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # 🌍 Language selector (compact, left of record button)
        lang_label = QLabel("🌍")
        lang_label.setToolTip("Transcription language")
        lang_label.setStyleSheet("font-size: 14px; padding: 0 2px;")
        top_row.addWidget(lang_label)

        self._language_combo = QComboBox()
        self._language_combo.setMinimumWidth(160)
        self._language_combo.setMaximumWidth(200)
        self._populate_language_combo()
        self._language_combo.currentIndexChanged.connect(
            self._on_language_changed
        )
        top_row.addWidget(self._language_combo)

        self._panel_mic = MicVuButton(
            self._service,           # the SHARED service from main window
            position=MicVuButton.Position.RIGHT,
            shape=MicVuButton.Shape.THIN_HORIZONTAL,
            auto_enable=True,
            noise_level=self._cached.config.noise_level,
            auto_transcribe_idle_seconds=self._cached.config.delay_transcription,
        )
        self._panel_mic.setFixedWidth(500)
        self._panel_mic.toggled.connect(self._toggle_test)
        self._panel_mic.transcribed.connect(self._on_transcription_done)
        self._panel_mic.failed.connect(self._on_transcription_failed)
        top_row.addWidget(self._panel_mic)

        # 🎯 Model status badge (small, lives next to button)
        self._model_badge = QPushButton("")
        self._model_badge.setToolTip("Click to reset")
        self._model_badge.setFont(QFont("Sans", 10, QFont.Weight.Bold))
        # self._model_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._model_badge.setMinimumHeight(34)
        self._model_badge.setMinimumWidth(100)
        self._model_badge.setStyleSheet(
            "padding: 2px 8px; border-radius: 4px;"
        )
        self._model_badge.clicked.connect(
            lambda: self._panel_mic.set_active(False))
        self._model_badge.clicked.connect(self._reset_test_state)
        self._model_badge.clicked.connect(self._reset_to_idle)
        top_row.addWidget(self._model_badge)

        self._timer_label = QLabel("00:00")
        self._timer_label.setFont(QFont("Monospace", 11, QFont.Weight.Bold))
        self._timer_label.setStyleSheet(
            "color: #a6adc8; padding: 0 8px; min-width: 55px;"
        )
        self._timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self._timer_label)

        layout.addLayout(top_row)

        # ── VU meter ──
        self._vu_meter = QProgressBar()
        self._vu_meter.setRange(0, 100)
        self._vu_meter.setValue(0)
        self._vu_meter.setTextVisible(False)
        self._vu_meter.setFixedHeight(12)
        layout.addWidget(self._vu_meter)

        # ── Status line ──
        self._status_label = QLabel("Click to record a short test phrase.")
        self._status_label.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 0;"
        )
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # ── Result area ──
        self._result_view = QTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setPlaceholderText(
            "📝 Transcription result will appear here…"
        )
        self._result_view.setFixedHeight(90)
        layout.addWidget(self._result_view)

        # ── Timing label ──
        self._timing_label = QLabel("")
        self._timing_label.setFont(QFont("Monospace", 9))
        self._timing_label.setStyleSheet(
            "color: #6c7086; font-size: 10px;"
        )
        layout.addWidget(self._timing_label)

        self._apply_styles()
        self._update_badge("idle")

        # ⏱️ Elapsed timer
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

    def _apply_styles(self):
        self.setStyleSheet("""
            QGroupBox {
                color: #fab387;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QPushButton#recordBtn {
                background-color: #89b4fa;
                color: #1e1e2e;
                border: none;
                border-radius: 5px;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton#recordBtn:hover { background-color: #a3c2fb; }
            QPushButton#recordBtn[recording="true"] {
                background-color: #f38ba8;
            }
            QPushButton#recordBtn[recording="true"]:hover {
                background-color: #f5a0b8;
            }
            QPushButton#recordBtn:disabled {
                background-color: #45475a;
                color: #6c7086;
            }
            QProgressBar {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #a6e3a1;
                border-radius: 5px;
            }
            QTextEdit {
                background-color: #11111b;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
            }
        """)

    # ── Badge helper ───────────────────────────────────────

    def _update_badge(self, kind: str):
        """Update the small status badge next to the record button."""
        styles = {
            "idle":     ("Reset",            ""),
            "loading":  ("⏳ Loading",       "background:#f9e2af; color:#1e1e2e;"),
            "ready":    ("⚡ Model ready",   "background:#a6e3a1; color:#1e1e2e;"),
            "cached":   ("✓ Cached",        "background:#94e2d5; color:#1e1e2e;"),
            "error":    ("🚨 Error",         "background:#f38ba8; color:#1e1e2e;"),
            "transcribing": ("📝 Working",   "background:#89b4fa; color:#1e1e2e;"),
        }
        text, style = styles.get(kind, ("", ""))
        self._model_badge.setText(text)
        self._model_badge.setStyleSheet(
            f"padding: 2px 8px; border-radius: 4px; "
            f"font-size: 10px; {style}"
        )

    # ── Language combo population ──────────────────────────

    def _populate_language_combo(self):
        """Fill the language dropdown: Auto + Popular + separator + All."""
        combo = self._language_combo

        # 🤖 Auto-detect (always first)
        combo.addItem(language_display(AUTO_DETECT), AUTO_DETECT)

        # ── Separator + popular section ──
        combo.insertSeparator(combo.count())
        for code in POPULAR_LANGUAGES:
            if code in WHISPER_LANGUAGES:
                combo.addItem(language_display(code), code)

        # ── Separator + all languages alphabetically ──
        combo.insertSeparator(combo.count())
        for code in sorted_language_codes():
            combo.addItem(language_display(code), code)

    def _selected_language(self) -> str:
        """Return the currently selected language code (or AUTO_DETECT)."""
        return self._language_combo.currentData() or AUTO_DETECT

    def _set_selected_language(self, code: str):
        """Programmatically select a language without triggering signals."""
        blocker = QSignalBlocker(self._language_combo)  # noqa: F841
        # Find first occurrence (popular section may appear before alphabetical)
        for i in range(self._language_combo.count()):
            if self._language_combo.itemData(i) == code:
                self._language_combo.setCurrentIndex(i)
                return
        # Fallback: auto-detect
        self._language_combo.setCurrentIndex(0)

    # ── Slot ───────────────────────────────────────────────

    def _on_language_changed(self, _index: int):
        """Refresh compatibility warning when language changes."""
        self._refresh_language_warning()

    def _refresh_language_warning(self):
        """Show a warning if the current language is incompatible with model."""
        code = self._selected_language()
        model = self._current_model_name

        if not model or code == AUTO_DETECT:
            self._lang_warning.setVisible(False)
            return

        # ⚠️ .en models only support English
        if is_english_only_model(model) and code != "en":
            self._lang_warning.setText(
                f"⚠ Model '{model}' is English-only. "
                f"It will attempt to translate {language_display(code)} "
                f"speech to English."
            )
            self._lang_warning.setVisible(True)
            return

        self._lang_warning.setVisible(False)

    # ── Public API ─────────────────────────────────────────

    def supply_config(self, cfg: WhisperConfig):
        """Called by parent dialog after config_requested signal."""
        self._pending_config = cfg
        # 🌍 Track model name for compatibility warnings
        if cfg.model != self._current_model_name:
            self._current_model_name = cfg.model
            self._refresh_language_warning()

    def shutdown(self):
        """🔌 Disconnect from the shared service — do NOT stop it.

        The service is owned by main.py and must outlive this dialog
        (the toolbar mic button keeps using it).
        """
        # 🛑 Stop recorder first (don't enqueue more files)
        self._panel_mic.set_active(False)

        # 🔌 Disconnect our signal handlers from the shared service
        if self._service is not None:
            try:
                self._service.model_loading.disconnect(self._on_loader_progress)
                self._service.model_ready.disconnect(self._on_model_loaded)
                self._service.model_failed.disconnect(self._on_loader_failed)
                self._service.transcription_started.disconnect(self._start_transcription)
                self._service.queue_size_changed.disconnect(self._on_queue_changed)
            except (TypeError, RuntimeError):
                pass  # already disconnected

        self._service = None  # drop our borrowed reference
        self._cached = None   # 🧹 release cache reference

    def set_initial_language(self, code: str):
        """Called by parent on dialog open to restore saved language."""
        self._set_selected_language(code)
        self._refresh_language_warning()

    def update_model_context(self, model_name: str):
        """Parent calls this when the user changes the model in the dialog."""
        if model_name != self._current_model_name:
            self._current_model_name = model_name
            self._refresh_language_warning()

    # ═══════════════════════════════════════════════════════
    #  Phase 1: Begin test (start recording + maybe load model)
    # ═══════════════════════════════════════════════════════

    def _toggle_test(self, active: bool):
        if not active:
            self._stop_recording()
            return
        # 📡 Get current (unsaved) config from parent
        self._pending_config = None
        self.config_requested.emit()
        if self._pending_config is None:
            self._status_label.setText("⚠ Could not read configuration.")
            return

        cfg = self._pending_config

        # Set new noise and idle for transcribe times
        self._panel_mic.set_noise_level(cfg.noise_level, cfg.delay_transcription)

        # 🔒 Lock language selector while testing
        self._language_combo.setEnabled(False)
        self._lang_dict.clear()
        self._lang_dict['_'] = 0

        self._result_view.clear()
        self._timing_label.clear()
        self._elapsed_ms = 0
        self._timer_label.setText("00:00")
        self._elapsed_timer.start()

        # 🗃️ Check cache: skip loading if model is already in memory
        if (self._cached and self._cached.config and self._cached.matches(cfg)
                    and self._service.is_running):
            self._state = State.LOADING_DONE_RECORDING  # already "done"
            self._pending_load_time = 0.0  # cached → no load cost
            self._update_badge("cached")
            self._status_label.setText(
                "🔴 Recording… ⚡ model already loaded, transcription will be instant."
            )
            return

        # ⏳ Cache miss (or different config) — load in PARALLEL with recording
        # Drop old cached model first to free memory
        self._cached = None
        self._state = State.LOADING_RECORDING
        self._status_label.setText(
            "🔴 Recording… ⏳ loading model in background…"
        )
        # 🚀 will restart() the service if config differs
        self._service.restart(cfg)

    # ═══════════════════════════════════════════════════════
    #  Phase 2: Loader signals (model finishes loading)
    # ═══════════════════════════════════════════════════════

    def _wire_service_signals(self):
        s = self._service
        s.model_loading.connect(self._on_loader_progress)
        s.model_ready.connect(self._on_model_loaded)
        s.model_failed.connect(self._on_loader_failed)
        s.transcription_started.connect(self._start_transcription)
        s.queue_size_changed.connect(self._on_queue_changed)
        # This was connected by settings window
        # s.api_key_required.connect(self._on_api_key_required)

    def _on_loader_progress(self, msg: str):
        # Only update status if we're still loading
        if self._state == State.LOADING_RECORDING:
            self._status_label.setText(f"🔴 Recording… {msg}")
        elif self._state == State.RECORDING_DONE_LOADING:
            self._status_label.setText(msg)

    def _on_model_loaded(self, model: Any, load_time: float):
        # 🗃️ Cache the model
        self._cached = CachedModel(
            model=model,
            config=self._pending_config,
            load_time=load_time,
        )
        self._pending_load_time = load_time

        if self._state == State.LOADING_RECORDING:
            # 🎙️ Still recording — model is just sitting ready
            self._state = State.LOADING_DONE_RECORDING
            self._update_badge("ready")
            self._status_label.setText(
                f"🔴 Recording… ⚡ model ready ({load_time:.1f}s) "
                f"— stop when done."
            )
        elif self._state == State.RECORDING_DONE_LOADING:
            # 🛑 Recording already finished — start transcribing now
            self._update_badge("transcribing")

    def _on_loader_failed(self, msg: str):
        self._cached = None
        self._update_badge("error")

        if self._state == State.LOADING_RECORDING:
            # 🎙️ Still recording — stop and report
            self._panel_mic.set_active(False)
        self._reset_to_idle(f"🚨 {msg}")
        self._result_view.setPlainText(f"🚨 {msg}")

    def _on_queue_changed(self, size: int):
        print('_on_queue_changed:', size)
        if size > 0:
            previous_text = self._status_label.text()
            print('previous_text:', previous_text)
            self._status_label.setText(f"📥 Queue: {size} pending")
            self.update()
            if not previous_text.startswith("📥 Queue: "):
                QTimer.singleShot(
                    5000, lambda: self._restore_label(previous_text))

    def _restore_label(self, previous_text: str):
        print('_restore_label:', previous_text)
        try:
            if self._panel_mic.is_active() and \
                    self._status_label.text().startswith("📥 Queue: "):
                self._status_label.setText(previous_text)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════
    #  Phase 3: recording
    # ═══════════════════════════════════════════════════════

    def _stop_recording(self):
        self._elapsed_timer.stop()
        self._vu_meter.setValue(0)
        self._panel_mic.set_active(False)
        self._panel_mic.setEnabled(False)

    def _tick_elapsed(self):
        if self._pending_config:
            secs_to_trans = time.time() - self._panel_mic._last_audio_timestamp
            delay = self._pending_config.delay_transcription
            perc = 100 if secs_to_trans <0 else secs_to_trans / delay * 100
        else:
            perc = 100
        self._vu_meter.setValue(100 - int(perc))
        self._elapsed_ms += 100
        secs = self._elapsed_ms // 1000
        self._timer_label.setText(f"{secs // 60:02d}:{secs % 60:02d}")
        if secs >= self.MAX_RECORD_SECONDS:
            self._stop_recording()

    # ═══════════════════════════════════════════════════════
    #  Phase 4: Transcribe
    # ═══════════════════════════════════════════════════════

    def _start_transcription(self):
        self._state = State.TRANSCRIBING
        self._update_badge("transcribing")

    def _on_transcription_done(self, result: dict):
        cursor = self._result_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(" " + result["text"])
        self._result_view.setTextCursor(cursor)

        # ⏱️ Load time display
        rec_secs = self._elapsed_ms / 1000
        load_t = result["load_time"]
        if load_t == 0:
            load_str = "cached"
        elif load_t <= rec_secs:
            load_str = f"{load_t:.1f}s"
        else:
            load_str = f"{rec_secs:.1f}+{load_t - rec_secs:.1f}s"

        # 🌍 Language display: forced vs detected
        lang_code = result["language"]
        prob = result["language_probability"]
        if not result["all_language_probs"]:
            result["all_language_probs"] = ((lang_code, prob),)
        # lang_name = language_display(lang_code)

        count = self._lang_dict['_'] or 0
        for lang_code, prob in result["all_language_probs"]:
            if lang_code in self._lang_dict:
                self._lang_dict[lang_code] = (
                    self._lang_dict[lang_code] * count + prob) / (count + 1)
            else:
                self._lang_dict[lang_code] = prob / (count + 1)
        self._lang_dict['_'] = count + 1

        if result.get("language_was_forced"):
            lang_str = f"{lang_code} (👍) | "

        sorted_langs = sorted(
            self._lang_dict.items(),
            key=lambda v: v[1],
            reverse=True
        )
        lang_str = " | ".join(f"{lang}: {prob:.1%}"
                              f"{'👍' if result.get('language_was_forced') else ''}"
                              for lang, prob in sorted_langs[1:6])

        # ✂️ Show VAD savings if available
        vad_stats = result.get("vad_stats")
        vad_str = ""
        if vad_stats and not vad_stats.get("skipped"):
            saved_pct = (1 - vad_stats["ratio"]) * 100
            vad_str = (f"   ✂️: {vad_stats['original_duration']:.1f}s→"
                       f"{vad_stats['trimmed_duration']:.1f}s "
                       f"(-{saved_pct:.0f}%)")

        self._timing_label.setText(
            f"⏱️: {load_str}   "
            f"🎙️: {result['duration']:.1f}s   "
            f"📝: {result['transcribe_time']:.1f}s   "
            f"⚡: {(1 / result['rtf']) if result.get('rtf') else 0:.2f}x   "
            f"🌍: {lang_str}"
            f"{vad_str}"
        )

        # self._status_label.setText(
        #     f"✅ Done · language: "
        #     f"{result['language']} ({result['language_probability']:.0%})"
        # )

        self._update_badge("cached")  # ⚡ now in cache for next test
        self._reset_to_idle()

    def _on_transcription_failed(self, msg: str):
        self._result_view.setPlainText(f"🚨 {msg}")
        self._update_badge("error")
        self._reset_to_idle("Transcription failed.")

    # ═══════════════════════════════════════════════════════
    #  Cleanup helpers
    # ═══════════════════════════════════════════════════════

    def _reset_test_state(self):
        """🔄 Clear test panel's local state (cache + pending) — keep service alive."""
        self._cached = None
        self._pending_config = None
        self._pending_wav = None
        self._pending_load_time = 0.0
        self._lang_dict = {'_': 0}

    def _reset_to_idle(self, status: str = ""):
        if not self._service.is_idle():
            return

        # 🔓 Unlock language combo and mic
        self._language_combo.setEnabled(True)
        self._panel_mic.setEnabled(True)

        self._state = State.IDLE

        if status:
            self._status_label.setText(status)
        elif self._cached:
            self._status_label.setText(
                "✓ Ready for another test · model is cached."
            )
        else:
            self._status_label.setText("Click to record a short test phrase.")
        self._update_badge("cached" if self._cached else "idle")
