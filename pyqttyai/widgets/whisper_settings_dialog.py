"""Whisper configuration dialog."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QLabel, QPushButton, QDialogButtonBox, QFrame,
    QSpinBox, QLineEdit, QFileDialog, QToolButton, QWidget,
    QTextEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from pyqttyai.core.paths import whisper_models_dir
from pyqttyai.core.whisper_config import (
    WhisperConfig,
    WHISPER_MODELS, WHISPER_DEVICES, WHISPER_COMPUTE_TYPES,
    COMPUTE_TYPE_HINTS, OPENVINO_COMPUTE_TYPES, FASTER_WHISPER_COMPUTE_TYPES,
    CPU_THREADS_AUTO, CPU_THREADS_MAX,
    BEAM_SIZE_MIN, BEAM_SIZE_MAX, BEAM_SIZE_DEFAULT,
    is_openvino_device, has_openvino_equivalent,
    is_openvino_genai_device,
    has_openvino_genai_equivalent, openvino_genai_resolved_name,
    is_groq_device, has_groq_equivalent, is_openai_device,
)
from pyqttyai.audio.transcription_service import TranscriptionService
from pyqttyai.widgets.whisper_test_panel import WhisperTestPanel
from pyqttyai.widgets.whisper_download_widget import WhisperDownloadWidget
from pyqttyai.widgets.api_key_dialog import ApiKeyDialog


# ═══════════════════════════════════════════════════════════
#  Descriptions
# ═══════════════════════════════════════════════════════════

_MODEL_DESCRIPTIONS: dict[str, str] = {
    "tiny.en":            "🪶 ~39M  English-only · fastest",
    "tiny":               "🪶 ~39M  Multilingual · fastest",
    "base.en":            "🐦 ~74M  English-only · very fast",
    "base":               "🐦 ~74M  Multilingual · very fast",
    "small.en":           "🐤 ~244M English-only · fast",
    "small":              "🐤 ~244M Multilingual · fast",
    "medium.en":          "🦅 ~769M English-only · balanced",
    "medium":             "🦅 ~769M Multilingual · balanced",
    "large-v1":           "🦉 ~1.5G Legacy large model",
    "large-v2":           "🦉 ~1.5G Improved large model",
    "large-v3":           "🦉 ~1.5G Latest large model",
    "large":              "🦉 ~1.5G Alias for latest large",
    "distil-large-v2":    "⚡ Distilled · 6× faster than large-v2",
    "distil-medium.en":   "⚡ Distilled English medium · fast",
    "distil-small.en":    "⚡ Distilled English small · very fast",
    "distil-large-v3":    "⚡ Distilled v3 · faster, near-equal accuracy",
    "distil-large-v3.5":  "⚡ Latest distilled · best speed/quality",
    "large-v3-turbo":     "🚀 Turbo · 8× faster than large-v3 (recommended)",
    "turbo":              "🚀 Alias for large-v3-turbo",
}

_DEVICE_DESCRIPTIONS: dict[str, str] = {
    "auto (faster)":          "🤖 Auto-detect best (faster-whisper)",
    "cpu (faster)":           "💻 CPU · faster-whisper",
    "cuda (faster)":          "🎮 NVIDIA GPU (CUDA) · fastest",
    "auto (OpenVINO)":        "🤖 Auto-detect (Intel hardware)",
    "cpu (OpenVINO)":         "💻 CPU · OpenVINO optimized",
    "gpu (OpenVINO)":         "🎮 Intel iGPU · OpenVINO accelerated",
    "auto (OpenVINO-GenAI)":  "🤖 Auto-detect (Intel hardware)",
    "cpu (OpenVINO-GenAI)":   "💻 CPU · OpenVINO optimized",
    "gpu (OpenVINO-GenAI)":   "🎮 Intel iGPU · OpenVINO accelerated",
}

# 🆕 (description, is_openvino) — used to filter combo by backend
_COMPUTE_DESCRIPTIONS: dict[str, tuple[str, bool]] = {
    # ── faster-whisper ──
    "int8":          ("📦 8-bit · smallest, fastest, lowest quality", False),
    "int8_float32":  ("📦 INT8 weights + FP32 compute · CPU-friendly", False),
    "int8_float16":  ("⚖️ INT8 + FP16 · best GPU balance", False),
    "int8_bfloat16": ("⚖️ INT8 + BF16 · modern GPUs (Ampere+)", False),
    "int16":         ("📦 16-bit integer · CPU compromise", False),
    "float16":       ("🎯 FP16 · standard GPU precision", False),
    "bfloat16":      ("🎯 BF16 · better range, modern GPUs", False),
    "float32":       ("💎 FP32 · highest precision, slowest", False),
    # ── Groq cloud ──
    "Groq API":      ("🌐 Cloud · Groq API · no local compute", None),
    # ── Open cloud ──
    "OpenAI API":    ("🌐 Cloud · OpenAI API · no local compute", None),
    # ── OpenVINO ──
    "FP32":          ("💎 FP32 · OpenVINO full precision", True),
    "FP16":          ("🎯 FP16 · OpenVINO half precision (recommended)", True),
    "INT8":          ("📦 INT8 · OpenVINO quantized (fastest)", True),
    "INT4":          ("📦 INT4 · OpenVINO quantized (fastest)", True),
}


# ═══════════════════════════════════════════════════════════
#  Dialog
# ═══════════════════════════════════════════════════════════

class WhisperSettingsDialog(QDialog):
    """Dialog to configure Whisper transcription settings."""

    config_saved = pyqtSignal(WhisperConfig)

    def __init__(
            self, parent=None,
            current_config: WhisperConfig | None = None,
            shared_service: TranscriptionService | None = None
        ):
        super().__init__(parent)
        self.setWindowTitle("Whisper Configuration")
        self.setMinimumSize(600, 720)
        self.setModal(True)

        self._config = current_config or WhisperConfig.load()
        self._service = shared_service
        self._initial_prompt: str = self._config.initial_prompt
        self._no_speech_text: str = self._config.no_speech_text
        self._noise_level: float =  self._config.noise_level
        self._delay_transcription: float = self._config.delay_transcription

        self._build_ui()
        self._apply_styles()
        self._load_values()
        self._wire_signals()

        # 🔑 Listen for API-key requests from any cloud backend
        if self._service is not None:
            self._service.api_key_required.connect(self._on_api_key_required)
            # 🚫 Suppress main-window injection while this dialog is open
            self._service.setProperty("suppress_injection", True)

        self._refresh_compute_combo()
        self._refresh_hints()
        self._refresh_enabled_state()

    # ═══════════════════════════════════════════════════════
    #  UI construction
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(4)

        header = QLabel("🎙️ Whisper Speech-to-Text Settings")
        header.setStyleSheet(
            "color: #89b4fa; font-size: 13px; font-weight: bold;"
        )
        root.addWidget(header)

        subtitle = QLabel(
            "Configure the transcription engine used for voice input."
        )
        subtitle.setStyleSheet("color: #a6adc8; font-size: 11px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── Two-column layout ──
        columns = QHBoxLayout()
        columns.setSpacing(8)

        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        left_col.addWidget(self._build_model_group())
        left_col.addStretch(1)

        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        right_col.addWidget(self._build_processing_group())
        right_col.addStretch(1)

        columns.addLayout(left_col, stretch=1)
        columns.addLayout(right_col, stretch=1)
        root.addLayout(columns)

        # ── Test panel ──
        self._test_panel = WhisperTestPanel(
            self, current_config=self._config, shared_service=self._service)
        self._test_panel.config_requested.connect(self._supply_test_config)
        root.addWidget(self._test_panel)

        self._test_panel.set_initial_language(self._config.language)
        self._test_panel.update_model_context(self._config.model)
        self._model_combo.currentTextChanged.connect(
            self._test_panel.update_model_context
        )

        root.addLayout(self._build_buttons())

    def _build_model_group(self) -> QGroupBox:
        group = QGroupBox("Model && Storage")
        form = QFormLayout(group)
        form.setContentsMargins(12, 18, 12, 12)
        form.setSpacing(6)

        # ── Model combo ──
        self._model_combo = QComboBox()
        self._model_combo.addItems(WHISPER_MODELS)
        form.addRow(QLabel("Whisper model:"), self._model_combo)

        columns = QHBoxLayout()
        columns.setSpacing(8)
        self._model_instruction = QPushButton()
        self._model_instruction.setText("📝")
        self._model_instruction.setToolTip("Model instructions and trigger")
        self._model_instruction.clicked.connect(self._model_instruction_dialog)
        columns.addWidget(self._model_instruction)
        self._transcription_rules = QPushButton()
        self._transcription_rules.setText("📘")  # 🗒️
        self._transcription_rules.setToolTip("Rules for adjusting the transcribed text")
        self._transcription_rules.clicked.connect(self._model_instruction_dialog)
        columns.addWidget(self._transcription_rules)

        self._model_hint = QLabel("")
        self._model_hint.setWordWrap(True)
        self._model_hint.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 0;"
        )

        form.addRow(self._wrap_layout(columns), self._model_hint)

        # ⚠️ OpenVINO compatibility warning
        self._openvino_warning = QLabel("")
        self._openvino_warning.setWordWrap(True)
        self._openvino_warning.setStyleSheet(
            "color: #f9e2af; font-size: 11px; "
            "padding: 4px 8px; background-color: #313244; "
            "border-left: 3px solid #f9e2af; border-radius: 3px;"
        )
        self._openvino_warning.setVisible(False)
        form.addRow(self._openvino_warning)

        form.addRow(self._hsep())

        # ── Models folder ──
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(4)

        self._download_root_edit = QLineEdit()
        self._download_root_edit.setPlaceholderText(
            "Default: HuggingFace cache"
        )
        path_row.addWidget(self._download_root_edit, stretch=1)

        self._browse_btn = QToolButton()
        self._browse_btn.setText("📁")
        self._browse_btn.setToolTip("Browse for folder")
        self._browse_btn.setFixedHeight(28)
        path_row.addWidget(self._browse_btn)

        self._reset_path_btn = QToolButton()
        self._reset_path_btn.setText("↺")
        self._reset_path_btn.setToolTip(
            f"Use Pyqttyai default: {whisper_models_dir()}"
        )
        self._reset_path_btn.setFixedHeight(28)
        path_row.addWidget(self._reset_path_btn)

        form.addRow(QLabel("Models folder:"), self._wrap_layout(path_row))

        self._download_root_hint = QLabel(
            "💾 Where Whisper models are stored (1+ GB each)."
        )
        self._download_root_hint.setWordWrap(True)
        self._download_root_hint.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 0;"
        )
        form.addRow("", self._download_root_hint)

        form.addRow(self._hsep())

        # 🆕 Download widget (replaces old offline mode section)
        download_label = QLabel("Download status:")
        self._download_widget = WhisperDownloadWidget(
            self, shared_service=self._service)
        self._download_widget.config_requested.connect(
            self._supply_download_config
        )
        form.addRow(download_label, self._download_widget)

        return group

    def _build_processing_group(self) -> QGroupBox:
        group = QGroupBox("Processing")
        form = QFormLayout(group)
        form.setContentsMargins(12, 18, 12, 12)
        form.setSpacing(6)

        # ── Device + Beam size on same row ──
        device_row = QHBoxLayout()
        device_row.setContentsMargins(0, 0, 0, 0)
        device_row.setSpacing(8)

        self._device_combo = QComboBox()
        self._device_combo.addItems(WHISPER_DEVICES)
        device_row.addWidget(self._device_combo)

        beam_label = QLabel("Beam:")
        beam_label.setStyleSheet("color: #cdd6f4;")
        beam_label.setFixedWidth(45)
        device_row.addWidget(beam_label)

        self._beam_spin = QSpinBox()
        self._beam_spin.setRange(BEAM_SIZE_MIN, BEAM_SIZE_MAX)
        self._beam_spin.setValue(BEAM_SIZE_DEFAULT)
        self._beam_spin.setRange(1, 9)
        self._beam_spin.setFixedWidth(50)
        self._beam_spin.setToolTip(
            "Beam size: higher = better quality, slower.\n"
            "Default: 5"
        )
        device_row.addWidget(self._beam_spin)

        device_row.setStretch(1, 1)
        form.addRow(QLabel("Device:"), self._wrap_layout(device_row))

        self._device_hint = QLabel("")
        self._device_hint.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 0;"
        )
        form.addRow("", self._device_hint)

        form.addRow(self._hsep())

        # Compute type
        self._compute_combo = QComboBox()
        form.addRow(QLabel("Compute type:"), self._compute_combo)

        self._compute_hint = QLabel("")
        self._compute_hint.setWordWrap(True)
        self._compute_hint.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 0;"
        )
        form.addRow("", self._compute_hint)

        self._compat_warning = QLabel("")
        self._compat_warning.setWordWrap(True)
        self._compat_warning.setStyleSheet(
            "color: #f9e2af; font-size: 11px; "
            "padding: 4px 8px; background-color: #313244; "
            "border-left: 3px solid #f9e2af; border-radius: 3px;"
        )
        self._compat_warning.setVisible(False)
        form.addRow(self._compat_warning)

        form.addRow(self._hsep())

        # CPU threads
        self._cpu_threads_spin = QSpinBox()
        self._cpu_threads_spin.setRange(CPU_THREADS_AUTO, CPU_THREADS_MAX)
        self._cpu_threads_spin.setSpecialValueText("Auto (library default)")
        self._cpu_threads_spin.setSuffix(" threads")
        self._cpu_threads_spin.setMinimumWidth(220)
        form.addRow(QLabel("CPU threads:"), self._cpu_threads_spin)

        self._cpu_threads_hint = QLabel(
            "🧵 Number of CPU threads (only applies for CPU device)."
        )
        self._cpu_threads_hint.setWordWrap(True)
        self._cpu_threads_hint.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 0;"
        )
        form.addRow("", self._cpu_threads_hint)

        return group

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._reset_btn = QPushButton("Reset Defaults")
        self._reset_btn.clicked.connect(self._reset_defaults)
        row.addWidget(self._reset_btn)
        row.addStretch(1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close
        )
        self._buttons.button(
            QDialogButtonBox.StandardButton.Save
        ).setObjectName("saveBtn")
        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self._on_close)
        row.addWidget(self._buttons)
        return row

    def _hsep(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #45475a;")
        return sep

    def _wrap_layout(self, layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    # ═══════════════════════════════════════════════════════
    #  Styles (unchanged from original)
    # ═══════════════════════════════════════════════════════

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; color: #cdd6f4; }
            QGroupBox {
                color: #89b4fa;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
            }
            QLabel { color: #cdd6f4; background: transparent; }
            QComboBox, QSpinBox, QLineEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                padding: 5px 8px;
                border-radius: 4px;
                min-width: 100px;
            }
            QSpinBox {
                min-width: 50px;
            }
            QSpinBox, QLineEdit {
                min-width: 25px;
            }
            QComboBox:hover, QSpinBox:hover, QLineEdit:hover {
                border: 1px solid #89b4fa;
            }
            QComboBox QAbstractItemView {
                background-color: #313244;
                color: #cdd6f4;
                selection-background-color: #45475a;
                selection-color: #f5c2e7;
                border: 1px solid #45475a;
            }
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: 1px solid #585b70;
                padding: 6px 14px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #585b70; }
            QPushButton#saveBtn {
                background-color: #a6e3a1;
                color: #1e1e2e;
                border: none;
            }
            QPushButton#saveBtn:hover { background-color: #94e2d5; }
            QToolButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: 1px solid #585b70;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
            }
            QToolButton:hover {
                background-color: #585b70;
                border: 1px solid #89b4fa;
            }
        """)

    # ═══════════════════════════════════════════════════════
    #  Wiring & state
    # ═══════════════════════════════════════════════════════

    def _wire_signals(self):
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        self._device_combo.currentTextChanged.connect(self._on_device_changed)
        self._compute_combo.currentTextChanged.connect(self._refresh_hints)
        self._browse_btn.clicked.connect(self._browse_download_root)
        self._reset_path_btn.clicked.connect(self._reset_download_root)

    def _load_values(self):
        c = self._config
        self._model_combo.setCurrentText(c.model)
        self._device_combo.setCurrentText(c.device)
        self._beam_spin.setValue(c.beam_size)
        self._cpu_threads_spin.setValue(c.cpu_threads)
        self._download_root_edit.setText(c.download_root)
        # 🆕 compute combo populated by _refresh_compute_combo
        self._refresh_compute_combo()
        if c.compute_type in [
            self._compute_combo.itemText(i)
            for i in range(self._compute_combo.count())
        ]:
            self._compute_combo.setCurrentText(c.compute_type)

    def _on_model_changed(self, _model: str):
        self._refresh_hints()

    def _on_device_changed(self, _device: str):
        self._refresh_compute_combo()
        self._refresh_hints()
        self._refresh_enabled_state()

    def _refresh_compute_combo(self):
        """🆕 Filter compute_type combo based on selected backend."""
        device = self._device_combo.currentText()
        is_ov_genai = is_openvino_genai_device(device)
        is_ov = is_ov_genai or is_openvino_device(device)
        is_groq = is_groq_device(device)
        is_openai =  is_openai_device(device)

        current = self._compute_combo.currentText()

        self._compute_combo.blockSignals(True)
        self._compute_combo.clear()

        if is_groq:
            # 🌐 Groq has no compute type — just show "api"
            self._compute_combo.addItem("Groq API")
        elif is_openai:
            # 🌐 Groq has no compute type — just show "api"
            self._compute_combo.addItem("OpenAI API")
        else:
            for ct in WHISPER_COMPUTE_TYPES:
                desc = _COMPUTE_DESCRIPTIONS.get(ct)
                if desc is None:
                    continue
                _, ct_is_ov = desc
                if ct_is_ov is None:
                    continue  # skip "api" outside Groq
                if ct_is_ov == is_ov:
                    if ct != "FP32" or not is_ov_genai:
                        self._compute_combo.addItem(ct)

        if current and self._compute_combo.findText(current) >= 0:
            self._compute_combo.setCurrentText(current)
        elif is_groq:
            self._compute_combo.setCurrentText("api")
        else:
            default = "INT8" if is_ov else "int8_float16"
            if self._compute_combo.findText(default) >= 0:
                self._compute_combo.setCurrentText(default)

        self._compute_combo.blockSignals(False)

    def _refresh_enabled_state(self):
        device = self._device_combo.currentText()
        cpu_relevant = "cpu" in device.lower() or "auto" in device.lower()
        self._cpu_threads_spin.setEnabled(cpu_relevant)
        if not cpu_relevant:
            self._cpu_threads_hint.setText("🚫 Not applicable for GPU.")
        else:
            self._cpu_threads_hint.setText(
                "🧵 0 = library default. Higher = faster, more CPU."
            )

    def _refresh_hints(self):
        model = self._model_combo.currentText()
        device = self._device_combo.currentText()
        compute = self._compute_combo.currentText()

        self._model_hint.setText(_MODEL_DESCRIPTIONS.get(model, ""))
        self._device_hint.setText(_DEVICE_DESCRIPTIONS.get(device, ""))

        compute_desc = _COMPUTE_DESCRIPTIONS.get(compute)
        if compute_desc:
            self._compute_hint.setText(compute_desc[0])
        else:
            self._compute_hint.setText("")

        # ⚠️ Backend model availability warning (OpenVINO + Groq)
        if is_openvino_device(device) and not has_openvino_equivalent(model):
            self._openvino_warning.setText(
                f"⚠ Model {model!r} has no known OpenVINO equivalent. "
                f"Try: tiny, base, small, medium, large-v3, "
                f"large-v3-turbo, distil-large-v3."
            )
            self._openvino_warning.setVisible(True)
        # ⚠️ Backend model availability warning (OpenVINO + Groq)
        elif is_openvino_genai_device(device):
            if not has_openvino_genai_equivalent(model):
                self._openvino_warning.setText(
                    f"⚠ Model {model!r} has no pre-converted OpenVINO IR. "
                    f"Try: tiny, base, small, medium, large-v3, "
                    f"distil-large-v3, turbo (→ distil-large-v3)."
                )
                self._openvino_warning.setVisible(True)
            else:
                _, warning = openvino_genai_resolved_name(model)  # resolved
                if warning:
                    self._openvino_warning.setText(warning)
                    self._openvino_warning.setVisible(True)
                else:
                    self._openvino_warning.setVisible(False)
        elif is_groq_device(device) and not has_groq_equivalent(model):
            self._openvino_warning.setText(
                f"⚠ Model {model!r} is not available on Groq Cloud. "
                f"Try: large-v3, large-v3-turbo, turbo, distil-large-v3."
            )
            self._openvino_warning.setVisible(True)
        else:
            self._openvino_warning.setVisible(False)

        # Compatibility warning
        recommended = COMPUTE_TYPE_HINTS.get(device, set())
        if recommended and compute not in recommended:
            self._compat_warning.setText(
                f"⚠ '{compute}' is unusual for '{device}'. "
                f"Recommended: {', '.join(sorted(recommended))}."
            )
            self._compat_warning.setVisible(True)
        else:
            self._compat_warning.setVisible(False)

    # ═══════════════════════════════════════════════════════
    #  Actions
    # ═══════════════════════════════════════════════════════

    def _browse_download_root(self):
        current = self._download_root_edit.text().strip()
        start_dir = current or str(whisper_models_dir())
        try:
            Path(start_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError:
            start_dir = str(Path.home())

        chosen = QFileDialog.getExistingDirectory(
            self, "Select Whisper Models Folder",
            start_dir, QFileDialog.Option.ShowDirsOnly,
        )
        if chosen:
            self._download_root_edit.setText(chosen)

    def _reset_download_root(self):
        self._download_root_edit.setText(str(whisper_models_dir()))

    def _reset_defaults(self):
        defaults = WhisperConfig()
        self._model_combo.setCurrentText(defaults.model)
        self._device_combo.setCurrentText(defaults.device)
        self._beam_spin.setValue(defaults.beam_size)
        self._cpu_threads_spin.setValue(defaults.cpu_threads)
        self._download_root_edit.setText(defaults.download_root)
        self._refresh_compute_combo()
        self._compute_combo.setCurrentText(defaults.compute_type)
        self._refresh_enabled_state()

    def _build_config_from_ui(self) -> WhisperConfig:
        """Build a WhisperConfig from current UI state."""
        return WhisperConfig(
            model=self._model_combo.currentText(),
            device=self._device_combo.currentText(),
            compute_type=self._compute_combo.currentText(),
            cpu_threads=self._cpu_threads_spin.value(),
            beam_size=self._beam_spin.value(),
            download_root=self._download_root_edit.text().strip(),
            local_files_only=True,  # 🔒 always offline for now
            language=self._test_panel._selected_language(),
            num_workers=self._config.num_workers,
            device_index=self._config.device_index,
            use_auth_token=self._config.use_auth_token,
            initial_prompt=self._initial_prompt,
            no_speech_text=self._no_speech_text,
            noise_level=self._noise_level,
            delay_transcription=self._delay_transcription,
            vad_pretrim=getattr(self._config, "vad_pretrim", True),
            vad_threshold=getattr(self._config, "vad_threshold", 0.3),
            vad_speech_pad_ms=getattr(self._config, "vad_speech_pad_ms", 500),
            vad_min_silence_ms=getattr(self._config, "vad_min_silence_ms", 500),
            vad_keep_temp=getattr(self._config, "vad_keep_temp", False),
        )

    def _on_save(self):
        cfg = self._build_config_from_ui()
        errors = cfg.validate()
        if errors:
            QMessageBox.critical(
                self,
                "Save",
                f"❌ Configuration wasn't saved.\n\n⚠ Invalid config: {errors}",
            )
            return
        if not cfg.save():
            QMessageBox.critical(
                self,
                "Save",
                f"❌ Configuration wasn't saved.",
            )
            return
        self._config = cfg
        self.config_saved.emit(cfg)
        QMessageBox.information(
            self,
            "Save",
            "💾 Configuration saved successfully!",
        )
        #self.accept()

    def _on_close(self):
        if self._config != self._build_config_from_ui():
            resp = QMessageBox.question(
                self,
                "Save",
                "Do you want to save the atual configuration?",
                buttons=(
                    QMessageBox.StandardButton.Yes|
                    QMessageBox.StandardButton.No|
                    QMessageBox.StandardButton.Cancel
                ),
            )
            if resp == QMessageBox.StandardButton.Yes:
                self._on_save()
            elif resp != QMessageBox.StandardButton.No:
                return
        self.reject()

    def _on_api_key_required(self, provider: str, env_var: str, message: str):
        """🔑 Cloud backend asked for credentials — prompt user."""

        dlg = ApiKeyDialog(provider, env_var, message, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # 🚀 Retry with the same config — env var is now set
        cfg = self._build_config_from_ui()
        if self._service is not None:
            self._service.restart(cfg)

    def _supply_test_config(self):
        self._test_panel.supply_config(self._build_config_from_ui())

    def _supply_download_config(self):
        """🆕 Provide config to the download widget.

        ⚠️ Do NOT call _cleanup_resources() here — the service is owned by
        main.py and lives for the whole app lifetime. The download widget
        will restart() the shared service with the new config as needed.
        """
        self._download_widget.supply_config(self._build_config_from_ui())

    def reject(self):
        """Ensure cleanup runs even if reject() is called directly."""
        self._cleanup_resources()
        super().reject()

    def accept(self):
        """Ensure cleanup runs even if accept() is called directly."""
        self._cleanup_resources()
        super().accept()

    def closeEvent(self, event):
        """Ensure cleanup runs even if close() is called directly."""
        self._cleanup_resources()
        super().closeEvent(event)

    def _cleanup_resources(self):
        # 🔓 Re-enable main-window injection
        if getattr(self, "_service", None) is not None:
            try:
                self._service.setProperty("suppress_injection", False)
            except Exception:
                pass

        """🧹 Idempotent cleanup — safe to call multiple times."""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True

        if hasattr(self, "_test_panel"):
            try:
                self._test_panel.shutdown()
            except Exception as e:
                print(f"Test panel shutdown error: {e}")

        if hasattr(self, "_download_widget"):
            try:
                self._download_widget.shutdown()
            except Exception as e:
                print(f"Download widget shutdown error: {e}")

        # 🔌 Drop our borrowed reference — service lives on for main.py
        if getattr(self, "_service", None) is not None:
            try:
                self._service.api_key_required.disconnect(self._on_api_key_required)
            except (TypeError, RuntimeError):
                pass
            self._service.restart(self._config)
            self._service = None


    def current_config(self) -> WhisperConfig:
        return self._config

    def _model_instruction_dialog(self):
        """Show a dialog asking the user for a text value for model instructions."""

        dialog = QDialog(self._model_instruction)
        dialog.setWindowTitle("Instruções")
        dialog.setMinimumWidth(512)
        dialog.setModal(True)

        # 🎨 Catppuccin Mocha style
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QFrame#contentFrame {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
            }
            QLabel {
                color: #cdd6f4;
                background: transparent;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                padding: 6px 8px;
                border-radius: 4px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #89b4fa;
            }
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: 1px solid #585b70;
                padding: 6px 14px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #585b70;
            }
            QPushButton#okBtn {
                background-color: #a6e3a1;
                color: #1e1e2e;
                border: none;
            }
            QPushButton#okBtn:hover {
                background-color: #94e2d5;
            }
        """)

        # ── Main layout ──
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ── Frame containing label + text box ──
        frame = QFrame()
        frame.setObjectName("contentFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(14, 12, 14, 12)
        frame_layout.setSpacing(8)

        label_widget = QLabel("Custom Prompt with initial instructions")
        frame_layout.addWidget(label_widget)

        text_editor = QTextEdit()
        text_editor.setText(self._initial_prompt)
        text_editor.setPlaceholderText("Text for initial instructions")
        text_editor.selectAll()  # 🎯 pre-select default for quick replace
        frame_layout.addWidget(text_editor)

        label_widget = QLabel("No speech detected text")
        frame_layout.addWidget(label_widget)

        line_editor = QLineEdit()
        line_editor.setText(self._no_speech_text)
        line_editor.setPlaceholderText("Text for use when no speech is detected")
        line_editor.selectAll()
        frame_layout.addWidget(line_editor)

        label_widget = QLabel("Noise level")
        frame_layout.addWidget(label_widget)

        noise_editor = QSpinBox()
        noise_editor.setRange(1, 99)
        noise_editor.setSuffix('%')
        noise_editor.setValue(int(self._noise_level * 100))
        frame_layout.addWidget(noise_editor)

        label_widget = QLabel("Delay for begin the transcribe")
        frame_layout.addWidget(label_widget)

        delay_editor = QSpinBox()
        delay_editor.setSuffix('ms')
        delay_editor.setRange(100, 5000)
        delay_editor.setValue(int(self._delay_transcription * 1000))
        frame_layout.addWidget(delay_editor)

        # ✂️ VAD pre-trim section
        from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox

        vad_label = QLabel("✂️ VAD pre-trim (cuts silence before transcription)")
        vad_label.setStyleSheet(
            "color: #fab387; font-weight: bold; margin-top: 8px;"
        )
        frame_layout.addWidget(vad_label)

        vad_check = QCheckBox("Enable VAD pre-trim (recommended)")
        vad_check.setChecked(getattr(self._config, "vad_pretrim", True))
        vad_check.setToolTip(
            "Trim silence/noise before sending to Whisper.\n"
            "🚀 ~3× faster + more accurate (especially for cloud backends)."
        )
        frame_layout.addWidget(vad_check)

        frame_layout.addWidget(QLabel("VAD threshold (0.05 — 0.95):"))
        vad_threshold_editor = QDoubleSpinBox()
        vad_threshold_editor.setRange(0.05, 0.95)
        vad_threshold_editor.setSingleStep(0.05)
        vad_threshold_editor.setDecimals(2)
        vad_threshold_editor.setValue(
            getattr(self._config, "vad_threshold", 0.3)
        )
        vad_threshold_editor.setToolTip(
            "Lower = more sensitive (catches quieter speech).\n"
            "0.3 works great for most microphones."
        )
        frame_layout.addWidget(vad_threshold_editor)

        frame_layout.addWidget(QLabel("VAD speech padding:"))
        vad_pad_editor = QSpinBox()
        vad_pad_editor.setRange(0, 2000)
        vad_pad_editor.setSingleStep(50)
        vad_pad_editor.setSuffix(" ms")
        vad_pad_editor.setValue(
            getattr(self._config, "vad_speech_pad_ms", 500)
        )
        vad_pad_editor.setToolTip(
            "Padding around speech segments.\n"
            "Prevents clipping the first/last syllable."
        )
        frame_layout.addWidget(vad_pad_editor)

        frame_layout.addWidget(QLabel("VAD min silence:"))
        vad_silence_editor = QSpinBox()
        vad_silence_editor.setRange(100, 5000)
        vad_silence_editor.setSingleStep(100)
        vad_silence_editor.setSuffix(" ms")
        vad_silence_editor.setValue(
            getattr(self._config, "vad_min_silence_ms", 500)
        )
        vad_silence_editor.setToolTip(
            "Minimum silence to split speech segments."
        )
        frame_layout.addWidget(vad_silence_editor)

        main_layout.addWidget(frame)

        main_layout.addWidget(frame)

        # ── OK / Cancel buttons ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("okBtn")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        main_layout.addWidget(buttons)

        # ⌨️ Enter = OK, Escape = Cancel (already handled by QDialogButtonBox)
        text_editor.setFocus()

        # ── Show & return ──
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._initial_prompt = text_editor.toPlainText()
            self._no_speech_text = line_editor.text()
            self._noise_level = noise_editor.value() / 100.
            self._delay_transcription = delay_editor.value() / 1000.
            self._config.vad_pretrim = vad_check.isChecked()
            self._config.vad_threshold = vad_threshold_editor.value()
            self._config.vad_speech_pad_ms = vad_pad_editor.value()
            self._config.vad_min_silence_ms = vad_silence_editor.value()

