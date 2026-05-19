"""Device tab: combines ScriptEditor (top) + TTYConsole (bottom) with controls."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QLabel, QSpinBox, QProgressBar, QFrame,
)
from PyQt6.QtGui import QTextCursor
from PyQt6.QtCore import Qt, pyqtSignal

from ..core.device import Device, DeviceStatus
from ..core.session import ConnectionWorker
from ..core.script_runner import ScriptRunner
from .script_editor import ScriptEditor
from .tty_console import TTYConsole
from .find_replace_bar import FindReplaceBar


class DeviceTab(QWidget):
    """A single device tab with editor + console."""

    status_changed = pyqtSignal(Device)
    apply_rules_requested = pyqtSignal(object, str)  # (DeviceTab, line_text)

    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self.device = device
        self._worker: ConnectionWorker | None = None
        self._runner: ScriptRunner | None = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        # ── Vertical Splitter: Editor (top) / Console (bottom) ─
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Script Editor ──────────────────────────────────
        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_header = QLabel("📝 Script Editor")
        editor_header.setStyleSheet(
            "background-color: #181825; padding: 4px 8px; "
            "color: #cba6f7; font-weight: bold; font-size: 11px;"
        )
        editor_layout.addWidget(editor_header)

        self._editor = ScriptEditor()
        self._editor.apply_rules_requested.connect(
            lambda line: self.apply_rules_requested.emit(self, line)
        )
        self._find_replace_bar = FindReplaceBar(self._editor, with_replace=True, parent=self)
        self._find_replace_bar.hide()
        self._editor.set_find_replace_bar(self._find_replace_bar)
        editor_layout.addWidget(self._find_replace_bar)
        editor_layout.addWidget(self._editor)

        splitter.addWidget(editor_container)

        # ── Console container (control bar + tty) ──────────
        console_container = QWidget()
        console_layout = QVBoxLayout(console_container)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(0)

        # ── Control Bar (between editor and console) ───────
        BTN_H = 28

        ctrl_frame = QFrame()
        ctrl_frame.setFixedHeight(BTN_H + 8)
        ctrl_frame.setStyleSheet(
            "QFrame { background-color: #181825; padding: 0px; }"
        )
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(8, 2, 8, 2)
        ctrl_layout.setSpacing(6)

        # Delay spinner
        delay_label = QLabel("Delay:")
        delay_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        ctrl_layout.addWidget(delay_label)
        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(50, 10000)
        self._delay_spin.setValue(500)
        self._delay_spin.setSingleStep(100)
        self._delay_spin.setSuffix(" ms")
        self._delay_spin.setFixedHeight(BTN_H)
        self._delay_spin.setStyleSheet(
            "QSpinBox { font-size: 11px; padding: 1px 4px; }"
        )
        ctrl_layout.addWidget(self._delay_spin)

        ctrl_layout.addStretch()

        # ▼ Send Script (entire script)
        self._send_btn = QPushButton("▼ Send Script")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setFixedHeight(BTN_H)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._send_script)
        self._send_btn.setToolTip("Send entire script to device")
        ctrl_layout.addWidget(self._send_btn)

        # ▶ Selected (selection or current line)
        self._send_sel_btn = QPushButton("▶ Selected")
        self._send_sel_btn.setFixedHeight(BTN_H)
        self._send_sel_btn.setEnabled(False)
        self._send_sel_btn.clicked.connect(self._send_selected)
        self._send_sel_btn.setToolTip(
            "Send selected text (or current line if nothing selected)"
        )
        self._send_sel_btn.setStyleSheet(
            "QPushButton { background-color: #89b4fa; color: #1e1e2e; "
            "border: none; font-weight: bold; padding: 2px 12px; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #74c7ec; }"
            "QPushButton:disabled { background-color: #45475a; color: #6c7086; }"
        )
        ctrl_layout.addWidget(self._send_sel_btn)

        # ⏹ Stop
        self._stop_btn = QPushButton("⏹ Stop")
        self._stop_btn.setFixedHeight(BTN_H)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_script)
        ctrl_layout.addWidget(self._stop_btn)

        # 🗑 Clear
        self._clear_btn = QPushButton("🗑️ Clear")
        self._clear_btn.setFixedHeight(BTN_H)
        self._clear_btn.clicked.connect(lambda: self._console.clear_console())
        ctrl_layout.addWidget(self._clear_btn)

        console_layout.addWidget(ctrl_frame)

        # ── Progress Bar ─────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setMaximumHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { background-color: #313244; border: none; "
            "border-radius: 2px; }"
            "QProgressBar::chunk { background-color: #a6e3a1; "
            "border-radius: 2px; }"
        )
        # self._progress.hide()
        console_layout.addWidget(self._progress)

        # ── TTY Console ──────────────────────────────────
        console_header = QLabel("🖥 TTY Console")
        console_header.setStyleSheet(
            "background-color: #181825; padding: 4px 8px; "
            "color: #a6e3a1; font-weight: bold; font-size: 11px;"
        )
        console_layout.addWidget(console_header)
        self._console = TTYConsole()
        self._find_bar = FindReplaceBar(self._console, with_replace=False, parent=self)
        self._find_bar.hide()
        self._console.set_find_bar(self._find_bar)
        console_layout.addWidget(self._find_bar)
        console_layout.addWidget(self._console)

        splitter.addWidget(console_container)

        # 40% editor / 60% console
        splitter.setSizes([300, 500])
        layout.addWidget(splitter)

    # ── Connection ─────────────────────────────────────────

    def connect_device(self):
        if self._worker and self._worker.isRunning():
            return

        self.device.status = DeviceStatus.CONNECTING
        self._update_status()

        self._console.append_output(
            f"--- Connecting to {self.device.host}:{self.device.port} "
            f"via {self.device.protocol.value}... ---\n"
        )

        self._worker = ConnectionWorker(self.device)
        self._worker.connected.connect(self._on_connected)
        self._worker.data_received.connect(self._console.append_ansi)
        self._worker.connection_lost.connect(self._on_disconnected)
        self._console.key_pressed.connect(self._worker.send)
        self._worker.start()

    def disconnect_device(self):
        if self._runner:
            self._runner.stop()
        if self._worker:
            self._console.key_pressed.disconnect(self._worker.send)
            self._worker.stop()
            self._worker = None
        self.device.status = DeviceStatus.DISCONNECTED
        self._update_status()
        self._console.append_output("\n--- Disconnected ---\n")

    def _on_connected(self):
        self.device.status = DeviceStatus.CONNECTED
        self._update_status()
        self._console.append_output("--- Connected! ---\n")

    def _on_disconnected(self, reason: str):
        self.device.status = DeviceStatus.DISCONNECTED
        self._update_status()
        self._console.append_output(f"\n--- {reason} ---\n")
        if self._worker:
            try:
                self._console.key_pressed.disconnect(self._worker.send)
            except TypeError:
                pass
            self._worker = None

    def _update_status(self):
        connected = self.device.status == DeviceStatus.CONNECTED
        self._send_btn.setEnabled(connected)
        self._send_sel_btn.setEnabled(connected)
        self.status_changed.emit(self.device)

    # ── Script Runner ──────────────────────────────────────

    def _send_script(self):
        """Send the entire script (including blank lines)."""
        if not self._worker:
            return
        script = self._editor.toPlainText()
        if not script:
            return
        self._run_script(script)

    def _send_selected(self):
        """Send selected text, or the current line if nothing selected."""
        if not self._worker:
            return

        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            text = text.replace("\u2029", "\n")
        else:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            text = cursor.selectedText()

        # Allow blank lines — only skip if completely None/empty
        if text is None:
            return
        self._run_script(text)

    def _run_script(self, script: str):
        """Run a script (full or partial) through ScriptRunner."""
        self._runner = ScriptRunner(self._worker.send)
        self._runner.line_sent.connect(self._on_line_sent)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_script_finished)

        self._send_btn.setEnabled(False)
        self._send_sel_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress.setValue(0)
        self._progress.show()

        self._runner.start(script, self._delay_spin.value())

    def _stop_script(self):
        if self._runner:
            self._runner.stop()

    def _on_line_sent(self, line_num: int, text: str):
        pass

    def _on_progress(self, current: int, total: int):
        self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_script_finished(self):
        connected = self.device.status == DeviceStatus.CONNECTED
        self._send_btn.setEnabled(connected)
        self._send_sel_btn.setEnabled(connected)
        self._stop_btn.setEnabled(False)
        self._progress.hide()
        self._runner = None

    # ── Public API ─────────────────────────────────────────

    def get_script_text(self) -> str:
        return self._editor.toPlainText()

    def set_script_text(self, text: str):
        self._editor.setPlainText(text)

    def insert_script_text(self, text: str):
        """Insert text at the current cursor position in the script editor.

        Preserves undo/redo history and moves the cursor to the end
        of the inserted text. If the editor doesn't have focus, the
        insertion happens at the existing cursor position.
        """
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()  # 🧩 group as a single undo step
        cursor.insertText(text)
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)  # 📍 cursor now at end of inserted text
        self._editor.ensureCursorVisible()
        self._editor.setFocus()  # 🎯 keep typing flow natural
