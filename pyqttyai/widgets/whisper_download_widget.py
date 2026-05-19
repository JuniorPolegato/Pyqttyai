"""Download button + progress bar for Whisper models."""

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QProgressBar, QTextEdit,
)

from pyqttyai.core.whisper_config import (
    WhisperConfig,
    has_openvino_equivalent, has_openvino_genai_equivalent,
)
from pyqttyai.audio.transcription_service import TranscriptionService


class WhisperDownloadWidget(QWidget):
    """Button + progress bar for pre-downloading Whisper models.

    Uses the shared TranscriptionService — no separate model load.
    """

    config_requested = pyqtSignal()

    def __init__(
            self, parent=None,
            shared_service: Optional[TranscriptionService] = None
        ):
        super().__init__(parent)
        self._service = shared_service
        self._service.model_loading.connect(self._on_progress)
        self._service.model_ready.connect(self._on_ready)
        self._service.model_failed.connect(self._on_failed)
        self._pending_config: Optional[WhisperConfig] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._download_btn = QPushButton("📥 Download Model")
        self._download_btn.setToolTip(
            "Download (and convert if OpenVINO) the selected model.\n"
            "If already loaded with the same settings, this is instant."
        )
        self._download_btn.setFixedHeight(28)
        self._download_btn.clicked.connect(self._start_download)
        layout.addWidget(self._download_btn)

        self._status_label = QTextEdit()
        self._status_label.setReadOnly(True)
        self._status_label.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 0 4px;"
        )
        self._status_label.setMaximumHeight(56)
        self._status_label.setMaximumWidth(300)
        layout.addWidget(self._status_label, stretch=1)

        self._progress = QProgressBar()
        self._progress.setMaximumHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #f9e2af;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self._progress)

    # ── Public API ──────────────────────────────────────

    def attach_service(self, service: TranscriptionService):
        """🔌 Wire to the shared transcription service."""
        if self._service is service:
            return
        self._service = service
        service.model_loading.connect(self._on_progress)
        service.model_ready.connect(self._on_ready)
        service.model_failed.connect(self._on_failed)

    def supply_config(self, config: WhisperConfig):
        """Called by parent dialog with current UI state."""
        self._pending_config = config
        self._do_start()

    def shutdown(self):
        """🔌 Disconnect from the shared service — do NOT stop it.

        The service is owned by main.py and must outlive this dialog
        (the toolbar mic button keeps using it).
        """
        if self._service is not None:
            try:
                self._service.model_loading.disconnect(self._on_progress)
                self._service.model_ready.disconnect(self._on_ready)
                self._service.model_failed.disconnect(self._on_failed)
            except (TypeError, RuntimeError):
                pass  # already disconnected, that's fine
        self._service = None  # drop our borrowed reference

    # ── Internal ────────────────────────────────────────

    def _start_download(self):
        # 📡 Ask parent for current config
        self.config_requested.emit()

    def _do_start(self):
        print("self._pending_config:", self._pending_config)
        print("self._service:", self._service)
        if self._pending_config is None or self._service is None:
            return

        cfg = self._pending_config
        self._pending_config = None
        cfg.local_files_only = False  # 🌐 allow download

        errors = cfg.validate()
        if errors:
            self._show_error(f"Invalid config: {errors[0]}")
            return

        if cfg.is_openvino_genai and not has_openvino_genai_equivalent(cfg.model):
            self._show_error(
                f"Model {cfg.model!r} has no OpenVINO GenAI equivalent."
            )
            return

        if cfg.is_openvino and not has_openvino_equivalent(cfg.model):
            self._show_error(
                f"Model {cfg.model!r} has no OpenVINO equivalent."
            )
            return

        # ⚡ Already loaded with same config?
        if (self._service.is_model_loaded
                and self._service.matches_config(cfg)):
            self._on_ready(cfg.model, 0.0)
            return

        self._download_btn.setEnabled(False)
        self._download_btn.setText("⏳ Downloading…")
        self._progress.setRange(0, 0)
        self._status_label.setText("Starting download…")
        self._status_label.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 0 4px;"
        )

        # 🚀 Restart service with new config (or start fresh)
        if self._service.is_running:
            self._service.restart(cfg)
        else:
            self._service.start(cfg)

    # ── Service signal handlers ─────────────────────────

    def _on_progress(self, msg: str):
        self._status_label.setText(msg)

    def _on_ready(self, model_name: str, load_time: float):
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        if load_time == 0.0:
            self._status_label.setText(f"⚡ {model_name} already loaded")
        else:
            self._status_label.setText(
                f"✅ {model_name} ready ({load_time:.1f}s)"
            )
        self._status_label.setStyleSheet(
            "color: #a6e3a1; font-size: 11px; padding: 0 4px;"
        )
        self._download_btn.setEnabled(True)
        self._download_btn.setText("📥 Download Model")

    def _on_failed(self, msg: str):
        self._show_error(msg)

    def _show_error(self, msg: str):
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._status_label.setText(f"❌ {msg}")
        self._status_label.setStyleSheet(
            "color: #f38ba8; font-size: 11px; padding: 0 4px;"
        )
        self._download_btn.setEnabled(True)
        self._download_btn.setText("📥 Download Model")
