"""Main application window."""

import os
import json
import platform
from pathlib import Path
from urllib.parse import urlparse
import re

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QTabWidget, QToolBar, QStatusBar,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QLineEdit,
    QSpinBox, QComboBox, QDialogButtonBox, QWidget, QVBoxLayout,
    QMenuBar, QMenu, QLabel, QTabBar, QFontComboBox, QHBoxLayout,
    QListWidget, QListWidgetItem, QAbstractItemView, QCheckBox,
    QPushButton, QPlainTextEdit, QScrollArea, QToolButton,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, pyqtSlot, QSettings
from PyQt6.QtGui import (
    QAction, QIcon, QKeySequence, QPixmap, QPainter, QColor,
    QBrush, QMouseEvent, QFont, QShortcut, QTextCursor, QActionGroup,
)

from pyqttyai.core.device import Device, Protocol, DeviceStatus
from pyqttyai.core.whisper_config import WhisperConfig
from pyqttyai.core.voice_rules import load_rules
from pyqttyai.core.rules_engine import RuleSet
from pyqttyai.audio.transcription_service import TranscriptionService
from pyqttyai.widgets.whisper_settings_dialog import WhisperSettingsDialog
from pyqttyai.widgets.mic_vu_button import MicVuButton
from pyqttyai.widgets.rules_editor_dialog import RulesEditorDialog
from pyqttyai.widgets.api_key_dialog import ApiKeyDialog

from .about_dialog import AboutDialog
from .topology_viewer import TopologyViewer
from .device_tab import DeviceTab
from .send_all_dialog import SendAllDialog

SUPPORTED_SCHEMES = {"telnet", "ssh"}

# ── Clickable Tab Bar ──────────────────────────────────────

class _ClickableTabBar(QTabBar):
    """Tab bar: click icon = connect/disconnect, double-click = edit."""
    icon_clicked = pyqtSignal(int)
    tab_double_clicked = pyqtSignal(int)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self.tabAt(pos)
            if index >= 0:
                tab_rect = self.tabRect(index)
                icon_area_width = 28
                local_x = pos.x() - tab_rect.left()
                if local_x <= icon_area_width:
                    self.icon_clicked.emit(index)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self.tabAt(pos)
            if index >= 0:
                self.tab_double_clicked.emit(index)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


# ── Status Icon Factory ───────────────────────────────────

def _make_status_icon(status: DeviceStatus) -> QIcon:
    colors = {
        DeviceStatus.DISCONNECTED: "#f44336",
        DeviceStatus.CONNECTING:   "#ffcc32",
        DeviceStatus.CONNECTED:    "#7cb342",
    }
    color = colors.get(status, "#6c7086")
    pix = QPixmap(24, 24)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(color)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 20, 20)
    painter.end()
    return QIcon(pix)


# ── Font Configuration Dialog ─────────────────────────────

class FontConfigDialog(QDialog):
    def __init__(self, current_family: str = "", current_size: int = 12, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TTY Font Configuration")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        header = QLabel("Configure the font used in all TTY consoles:")
        header.setStyleSheet("font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(header)

        form = QFormLayout()

        self._font_combo = QFontComboBox()
        self._font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        if current_family:
            self._font_combo.setCurrentFont(QFont(current_family))
        else:
            self._font_combo.setCurrentFont(QFont("Monospace"))
        self._font_combo.currentFontChanged.connect(self._update_preview)
        form.addRow("Font Family:", self._font_combo)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(6, 36)
        self._size_spin.setValue(current_size)
        self._size_spin.setSuffix(" pt")
        self._size_spin.valueChanged.connect(self._update_preview)
        form.addRow("Font Size:", self._size_spin)

        layout.addLayout(form)

        self._preview = QLabel("AaBbCc 0123456789 !@#$%\nR1(config)# show ip route")
        self._preview.setMinimumHeight(60)
        self._preview.setStyleSheet(
            "background-color: #11111b; color: #a6e3a1; "
            "padding: 10px; border-radius: 6px; border: 1px solid #45475a;"
        )
        layout.addWidget(self._preview)
        self._update_preview()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _update_preview(self):
        font = QFont(self._font_combo.currentFont().family(), self._size_spin.value())
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self._preview.setFont(font)

    def selected_family(self) -> str:
        return self._font_combo.currentFont().family()

    def selected_size(self) -> int:
        return self._size_spin.value()


# ── Device Dialog (Add / Edit) ────────────────────────────

class DeviceDialog(QDialog):
    def __init__(self, dev_dict: dict | None = None, parent=None):
        super().__init__(parent)
        self._editing = dev_dict is not None
        self.setWindowTitle("Edit Device" if self._editing else "Add Device")
        self.setMinimumWidth(380)

        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. R1-Core")
        layout.addRow("Device Name:", self.name_edit)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("e.g. 192.168.1.100")
        layout.addRow("Host / IP:", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(32769)
        layout.addRow("Port:", self.port_spin)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["telnet", "ssh"])
        self.protocol_combo.currentTextChanged.connect(self._on_protocol_change)
        layout.addRow("Protocol:", self.protocol_combo)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("(SSH only)")
        self.user_edit.setEnabled(False)
        layout.addRow("Username:", self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("(SSH only)")
        self.pass_edit.setEnabled(False)
        layout.addRow("Password:", self.pass_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Optional description")
        layout.addRow("Description:", self.desc_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        if dev_dict:
            self.name_edit.setText(dev_dict.get("name", ""))
            self.host_edit.setText(dev_dict.get("host", ""))
            self.port_spin.setValue(dev_dict.get("port", 23))
            proto = dev_dict.get("protocol", "telnet")
            self.protocol_combo.setCurrentText(proto)
            self.user_edit.setText(dev_dict.get("username", ""))
            self.pass_edit.setText(dev_dict.get("password", ""))
            self.desc_edit.setText(dev_dict.get("description", ""))
            self._on_protocol_change(proto)

    def _on_protocol_change(self, proto: str):
        is_ssh = proto == "ssh"
        self.user_edit.setEnabled(is_ssh)
        self.pass_edit.setEnabled(is_ssh)
        if not self._editing:
            self.port_spin.setValue(22 if is_ssh else 32769)

    def to_dict(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "Device",
            "host": self.host_edit.text().strip(),
            "port": self.port_spin.value(),
            "protocol": self.protocol_combo.currentText(),
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
            "description": self.desc_edit.text().strip(),
            "eve_node_id": None,
            "script": "",
        }


# ── EVE-NG Import Dialog ─────────────────────────────────

class EveNgImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import from EVE-NG")
        self.setMinimumSize(520, 480)
        self._nodes: list[dict] = []

        layout = QVBoxLayout(self)

        header = QLabel("🌐 EVE-NG Connection")
        header.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #89b4fa; margin-bottom: 4px;"
        )
        layout.addWidget(header)

        form = QFormLayout()

        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("e.g. 192.168.56.101")
        form.addRow("EVE-NG Host:", self._host_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(80)
        form.addRow("HTTP Port:", self._port_spin)

        self._user_edit = QLineEdit("admin")
        form.addRow("Username:", self._user_edit)

        self._pass_edit = QLineEdit("eve")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self._pass_edit)

        self._lab_edit = QLineEdit()
        self._lab_edit.setPlaceholderText("e.g. LAB_OSPF.unl  or  folder/lab.unl")
        form.addRow("Lab Path:", self._lab_edit)

        layout.addLayout(form)

        fetch_row = QHBoxLayout()
        fetch_row.addStretch()
        self._fetch_btn = QPushButton("🔍 Fetch Nodes")
        self._fetch_btn.setObjectName("connectBtn")
        self._fetch_btn.setFixedHeight(32)
        self._fetch_btn.clicked.connect(self._fetch_nodes)
        fetch_row.addWidget(self._fetch_btn)
        layout.addLayout(fetch_row)

        list_header = QLabel("📋 Lab Nodes (select which to import):")
        list_header.setStyleSheet("margin-top: 10px; font-weight: bold;")
        layout.addWidget(list_header)

        self._node_list = QListWidget()
        self._node_list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        self._node_list.setStyleSheet(
            "QListWidget { background-color: #313244; border: 1px solid #45475a; "
            "border-radius: 4px; }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:selected { background-color: #45475a; color: #a6e3a1; }"
        )
        layout.addWidget(self._node_list)

        self._select_all_cb = QCheckBox("Select All")
        self._select_all_cb.setChecked(True)
        self._select_all_cb.toggled.connect(self._toggle_select_all)
        layout.addWidget(self._select_all_cb)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self._status_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("Import Selected")
        self._ok_btn.setEnabled(False)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _toggle_select_all(self, checked: bool):
        for i in range(self._node_list.count()):
            self._node_list.item(i).setSelected(checked)

    def _fetch_nodes(self):
        import requests

        host = self._host_edit.text().strip()
        port = self._port_spin.value()
        username = self._user_edit.text().strip()
        password = self._pass_edit.text()
        lab_path = self._lab_edit.text().strip()

        if not host or not lab_path:
            self._status_label.setText("⚠ Host and Lab Path are required.")
            return

        if not lab_path.endswith(".unl"):
            lab_path += ".unl"

        base_url = f"http://{host}:{port}" if port != 80 else f"http://{host}"
        session = requests.Session()

        self._fetch_btn.setEnabled(False)
        self._status_label.setText("🔄 Logging in...")
        self._status_label.repaint()

        try:
            login_resp = session.post(
                f"{base_url}/api/auth/login",
                json={
                    "username": username,
                    "password": password,
                    "html5": "-1",
                },
                timeout=10,
            )
            login_data = login_resp.json()
            if login_data.get("status") != "success":
                self._status_label.setText(
                    f"❌ Login failed: {login_data.get('message', 'Unknown error')}"
                )
                return

            self._status_label.setText("🔄 Fetching nodes...")
            self._status_label.repaint()

            nodes_resp = session.get(
                f"{base_url}/api/labs/{lab_path}/nodes",
                timeout=10,
            )
            nodes_data = nodes_resp.json()

            if nodes_data.get("status") != "success":
                self._status_label.setText(
                    f"❌ Failed: {nodes_data.get('message', 'Unknown error')}"
                )
                return

            raw_nodes = nodes_data.get("data", {})
            self._nodes = []
            for node_id, node in raw_nodes.items():
                url = node.get("url", "")
                parsed = urlparse(url)
                telnet_port = parsed.port or 0

                self._nodes.append({
                    "node_id": node_id,
                    "name": node.get("name", f"Node-{node_id}"),
                    "host": host,
                    "port": telnet_port,
                    "protocol": "telnet",
                    "url": url,
                    "type": node.get("type", ""),
                    "template": node.get("template", ""),
                    "status": node.get("status", 0),
                })

            import re

            def sort_key(n):
                name = n["name"]
                if name.upper().startswith("R"):
                    group = 1
                elif name.upper().startswith("SW"):
                    group = 2
                else:
                    group = 3
                m = re.search(r'(\d+)$', name)
                num = int(m.group(1)) if m else 0
                return (group, num, name)

            self._nodes.sort(key=sort_key)

            self._node_list.clear()
            for node in self._nodes:
                status_icon = "🟢" if node["status"] == 2 else "🔴"
                item_text = (
                    f"{status_icon} {node['name']}  —  "
                    f"telnet://{node['host']}:{node['port']}  "
                    f"[{node['template']}]"
                )
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, node)
                self._node_list.addItem(item)
                item.setSelected(True)

            self._ok_btn.setEnabled(len(self._nodes) > 0)
            self._status_label.setText(
                f"✅ Found {len(self._nodes)} nodes in lab."
            )

            try:
                session.get(f"{base_url}/api/auth/logout", timeout=5)
            except Exception:
                pass

        except Exception as e:
            self._status_label.setText(f"❌ Error: {e}")
        finally:
            self._fetch_btn.setEnabled(True)

    def selected_nodes(self) -> list[dict]:
        result = []
        for item in self._node_list.selectedItems():
            node = item.data(Qt.ItemDataRole.UserRole)
            if node:
                result.append(node)
        return result

    def eve_host(self) -> str:
        return self._host_edit.text().strip()


# ── Shortcuts Dialog ──────────────────────────────────────

class ShortcutsDialog(QDialog):
    """Quick reference for keyboard shortcuts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setFixedSize(700, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ──
        header = QLabel("Keyboard Shortcuts")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFont(QFont("Sans", 15, QFont.Weight.Bold))
        header.setStyleSheet(
            "QLabel {"
            "  background-color: #181825; padding: 16px;"
            "  color: #89b4fa;"
            "  border-bottom: 2px solid #45475a;"
            "}"
        )
        layout.addWidget(header)

        # ── Scrollable content ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background-color: #1e1e2e; border: none; }"
            "QScrollBar:vertical {"
            "  background: #181825; width: 8px; border: none;"
            "}"
            "QScrollBar::handle:vertical {"
            "  background: #45475a; border-radius: 4px; min-height: 20px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "  height: 0px;"
            "}"
        )

        content = QWidget()
        content.setStyleSheet("QWidget { background-color: #1e1e2e; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 12, 24, 8)
        content_layout.setSpacing(3)

        shortcuts = [
            ("General", [
                ("Ctrl+O", "Open Workspace"),
                ("Ctrl+S", "Save Workspace"),
                ("Ctrl+Shift+S", "Save Workspace As"),
                ("Ctrl+Shift+W", "Whisper Playground"),
                ("Ctrl+Space", "🎙️ Toggle Voice Recognition"),
                ("Ctrl+Shift+R", "📋 NLP Rules Editor"),
                ("Ctrl+Q", "Quit"),
            ]),
            ("View", [
                ("Ctrl+0", "Zoom Fit"),
                ("Ctrl+1", "Zoom 100%"),
                ("F2", "Toggle Map Editor"),
            ]),
            ("Map Editor", [
                ("Click + Drag", "Draw new hotspot"),
                ("Right-Click + Drag", "Pan / move view"),
                ("Delete", "Delete selected hotspot"),
                ("Escape", "Deselect / cancel drawing"),
                ("Double-Click", "Rename hotspot"),
            ]),
            ("Tabs", [
                ("Click ball icon", "Connect / Disconnect"),
                ("Double-Click tab", "Edit device"),
                ("Click + Drag", "Move tab"),
                ("Ctrl+PgUp", "Previous tab"),
                ("Ctrl+PgDown", "Next tab"),
                ("Ctrl+Shift+PgUp", "Move tab backward"),
                ("Ctrl+Shift+PgDown", "Move tab forward"),
            ]),
            ("Script Editor", [
                ("Ctrl+C (no selection)", "📋 Copy current line (with trailing \\n)"),
                ("Ctrl+X (no selection)", "✂️ Cut current line (with trailing \\n)"),
                ("Tab",                   "➡️ Indent line / selected lines"),
                ("Shift+Tab",             "⬅️ Dedent line / selected lines"),
                ("Ctrl+;",                "🔢 Normalize IPv6 separator (`:`)"),
                ("Ctrl+.",                "🔢 Normalize IPv4 separator (`.`)"),
                ("Ctrl+-",                "🔢 Normalize MAC separator (`-`)"),
                ("Ctrl+Shift+Space",      "🔢 Normalize separator to space"),
                ("Ctrl+Shift+A",          "🎯 Apply NLP rules to current line"),
                ("Ctrl+Shift+F",          "🔎 Open Find & Replace (pre-fills selection)"),
                ("F3",                    "➡️ Find next match (opens bar if hidden)"),
                ("Shift+F3",              "⬅️ Find previous match (opens bar if hidden)"),
                ("Enter (in Find box)",   "➡️ Go to next match"),
                ("Esc",                   "❌ Close Find & Replace bar"),
            ]),
            ("TTY Console — Find", [
                ("Ctrl+Shift+F", "🔎 Open Find bar — ONLY when text is selected "
                                "(pre-fills with selection)"),
                ("Enter (in Find box)", "➡️ Go to next match"),
                ("Esc",          "❌ Close Find bar"),
            ]),
            ("TTY Console — Cisco IOS", [
                ("Ctrl+A", "Move cursor to start of line"),
                ("Ctrl+E", "Move cursor to end of line"),
                ("Ctrl+F", "Forward one character"),
                ("Ctrl+B", "Backward one character"),
                ("Ctrl+P", "Previous command (history ↑)"),
                ("Ctrl+N", "Next command (history ↓)"),
                ("Ctrl+K", "Kill from cursor to end of line"),
                ("Ctrl+U", "Clear entire line"),
                ("Ctrl+W", "Delete word to the left"),
                ("Ctrl+R", "Redisplay line / refresh line"),
                ("Ctrl+L", "Redisplay line / Clear screen"),
                ("Ctrl+D", "Delete character / Logout"),
                ("Ctrl+Z", "Exit config → Privileged Exec"),
                ("Ctrl+C", "Interrupt current process"),
                ("Ctrl+H", "Backspace"),
                ("Ctrl+I", "Tabulation"),
                ("Ctrl+6", "Break sequence (stop DNS, etc.)"),
                ("Ctrl+Shift+6", "Break sequence (stop DNS, etc.)"),
            ]),
            ("TTY Console — Clipboard & Navigation", [
                ("Ctrl+Shift+C", "Copy selection"),
                ("Ctrl+Shift+V", "Paste into terminal"),
                ("Ctrl + ←", "Jump left to start of words"),
                ("Ctrl + →", "Jump right to end of words"),
                ("Home", "Send Ctrl+A (start of line)"),
                ("End", "Send Ctrl+E (end of line)"),
                ("Delete", "Delete a character"),
            ]),
        ]

        for section, items in shortcuts:
            section_label = QLabel(section)
            section_label.setFont(QFont("Sans", 10, QFont.Weight.Bold))
            section_label.setStyleSheet(
                "QLabel {"
                "  color: #f5c2e7; background: transparent;"
                "  margin-top: 8px; padding: 2px 0;"
                "}"
            )
            content_layout.addWidget(section_label)

            for key, desc in items:
                row_widget = QWidget()
                row_widget.setStyleSheet("QWidget { background: transparent; }")
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 2, 0, 2)
                row_layout.setSpacing(12)

                key_label = QLabel(key)
                key_label.setFixedWidth(200)
                key_label.setFont(QFont("Monospace", 10, QFont.Weight.Bold))
                key_label.setStyleSheet(
                    "QLabel {"
                    "  background-color: #313244;"
                    "  color: #fab387;"
                    "  padding: 4px 10px;"
                    "  border-radius: 4px;"
                    "  border: 1px solid #45475a;"
                    "}"
                )
                row_layout.addWidget(key_label)

                desc_label = QLabel(desc)
                desc_label.setFont(QFont("Sans", 10))
                desc_label.setStyleSheet(
                    "QLabel { color: #cdd6f4; background: transparent; }"
                )
                row_layout.addWidget(desc_label, stretch=1)

                content_layout.addWidget(row_widget)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # ── Footer ──
        footer = QWidget()
        footer.setStyleSheet(
            "QWidget { background-color: #181825; border-top: 1px solid #45475a; }"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 8, 20, 10)
        footer_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFont(QFont("Sans", 10, QFont.Weight.Bold))
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #89b4fa; color: #1e1e2e;"
            "  border: none; border-radius: 6px; padding: 6px 16px;"
            "}"
            "QPushButton:hover { background-color: #b4d0fb; }"
        )
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)

        layout.addWidget(footer)


# ── Main Window ───────────────────────────────────────────

class MainWindow(QMainWindow):
    """Main application window with topology viewer and device tabs."""

    def __init__(
        self,
        parent=None,
        whisper_config: WhisperConfig | None = None,
        transcription_service: TranscriptionService | None = None,
        voice_rules: RuleSet | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Pyqttyai — Network Lab Study")
        self.setMinimumSize(400, 600)

        self._workspace_path: str | None = None
        self._devices: list[dict] = []
        self._send_all_scripts: list[dict] = []
        self._topology_path: str = ""
        self._topology_map_path: str = ""
        self._tty_font_family: str = ""
        self._tty_font_size: int = 12
        self._bring_to_front_enabled: bool = False

        # 🔢 Editor indent size (1–8 spaces, default 1 = Cisco style)
        self._settings = QSettings("Pyqttyai", "Pyqttyai")
        self._indent_size: int = int(self._settings.value("editor/indent_size", 1))
        self._indent_size = max(1, min(8, self._indent_size))

        # Use injected dependencies (fallback for backward compat)
        self._whisper_config: WhisperConfig = (
            whisper_config if whisper_config is not None
            else WhisperConfig.load()
        )
        self._transcription_service: TranscriptionService | None = (
            transcription_service
        )

        # 📋 Voice rewrite rules (lazy-loaded fallback if not injected)
        self._voice_rules = (
            voice_rules if voice_rules is not None else load_rules())

       # _setup_ui must be called BEFORE _setup_menubar (needs self._topology)
        self._setup_ui()
        self._setup_menubar()
        self._setup_statusbar()

        # ── Tab navigation shortcuts ──
        shortcut_next = QShortcut(QKeySequence("Ctrl+PgUp"), self)
        shortcut_next.activated.connect(lambda: self._next_tab(-1))

        shortcut_prev = QShortcut(QKeySequence("Ctrl+PgDown"), self)
        shortcut_prev.activated.connect(lambda: self._next_tab(1))

        # ── Move tab position ──
        shortcut_forward = QShortcut(QKeySequence("Ctrl+Shift+PgUp"), self)
        shortcut_forward.activated.connect(lambda: self._move_current_tab(-1))

        shortcut_backward = QShortcut(QKeySequence("Ctrl+Shift+PgDown"), self)
        shortcut_backward.activated.connect(lambda: self._move_current_tab(1))

        # 🎙️ Toggle microphone (voice recognition)
        shortcut_mic = QShortcut(QKeySequence("Ctrl+Space"), self)
        shortcut_mic.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_mic.activated.connect(self._toggle_mic_shortcut)

        # 📝 Wire transcription service results → active tab
        if self._transcription_service is not None:
            # 🎤 NOTE: transcribed/transcription_failed are routed via the active
            #    MicVuButton (broker pattern). See MicVuButton.transcribed / .failed.
            self._transcription_service.model_loading.connect(
                lambda _m: self._set_backend_indicator(
                    "loading", f"{self._backend_kind()} loading…"
                )
            )
            self._transcription_service.model_ready.connect(
                lambda _m, _t: (
                    self._set_backend_indicator(
                        "ready", f"{self._backend_kind()} {_m}"
                    )
                )
            )
            self._transcription_service.model_ready.connect(
                lambda _m, _t: (
                    self._statusbar.showMessage(
                        f"⚡ Whisper model ready "
                        f"(🌍 {self._whisper_config.language or 'auto'} "
                        f"| {_m} | {_t:.1f}s | {self._whisper_config.device})"
                    )
                )
            )
            self._transcription_service.transcribing.connect(
                lambda msg: self._statusbar.showMessage(msg, 3000)
            )
            self._transcription_service.transcription_started.connect(
                lambda _wav: self._set_backend_indicator(
                    "working", f"{self._backend_kind()} 🎙️ working…"
                )
            )
            self._transcription_service.transcribed.connect(
                lambda _r: self._set_backend_indicator(
                    "ready", f"{self._backend_kind()} {self._whisper_config.model}"
                )
            )
            self._transcription_service.transcription_failed.connect(
                lambda _w, _m: self._set_backend_indicator(
                    "ready", f"{self._backend_kind()} {self._whisper_config.model}"
                )
            )
            self._transcription_service.api_key_required.connect(
                self._on_api_key_required_main
            )
            self._transcription_service.model_failed.connect(
                lambda _m: self._set_backend_indicator("error", "🚨 failed")
            )
            self._transcription_service.model_failed.connect(
                lambda _m: self._statusbar.showMessage(
                    f"🚨 Whisper model failed! Please, verify in settings... [{_m}]"
                )
            )
            if not self._transcription_service.is_running:
                self._transcription_service.restart(self._whisper_config)


    def _on_api_key_required_main(self, provider: str, env_var: str, message: str):
        """🔑 Worker needs an API key (only handled here if no dialog is open)."""
        if self._transcription_service and \
                self._transcription_service.property("suppress_injection"):
            return

        self._set_backend_indicator("error", f"🚨 {provider.title()} key needed")
        dlg = ApiKeyDialog(provider, env_var, message, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._statusbar.showMessage(
                f"🔑 {provider.title()} key not provided — transcription disabled."
            )
            return

        self._transcription_service.restart(self._whisper_config)
        self._statusbar.showMessage(f"🔑 {provider.title()} key set, reconnecting…")

    def _set_backend_indicator(self, kind: str, text: str = ""):
        """🎯 Update the persistent backend status label in the status bar.

        kind: 'idle' | 'loading' | 'ready' | 'error'
        """
        if not hasattr(self, "_backend_label"):
            return
        colors = {
            "idle":    ("#a6adc8", ""),
            "loading": ("#f9e2af", "background:#313244;"),
            "ready":   ("#a6e3a1", "background:#313244;"),
            "working": ("#89b4fa", "background:#1e2a3a;"),
            "error":   ("#f38ba8", "background:#3a1f24;"),
        }
        color, bg = colors.get(kind, ("#a6adc8", ""))
        self._backend_label.setText(text or kind)
        self._backend_label.setStyleSheet(
            f"color: {color}; {bg} padding: 2px 10px; "
            f"border-radius: 3px; font-weight: bold;"
        )

    def _backend_kind(self) -> str:
        """🏠/🎮/🌐 emoji marker for the current backend."""
        if not self._whisper_config:
            return "❓"
        if getattr(self._whisper_config, "is_groq", False):
            return "🌐"
        device = getattr(self._whisper_config, "device", "")
        if device[:3] in ("cud", "gpu"):
            return "🎮"
        return "💻"

    def closeEvent(self, event):
        if self._toolbar_mic is not None:
            if self._toolbar_mic._recorder and self._toolbar_mic._recorder.is_recording:
                self._toolbar_mic._recorder.stop(silent=True)  # drop, don't transcribe
            self._toolbar_mic.set_active(False)
        if self._transcription_service is not None and self._transcription_service.is_running:
            self._transcription_service.stop()
        super().closeEvent(event)

    def _setup_menubar(self):
        menubar: QMenuBar = self.menuBar()

        # ── File ──
        file_menu: QMenu = menubar.addMenu("&File")

        open_ws = QAction("📂 Open Workspace…", self)
        open_ws.setShortcut(QKeySequence("Ctrl+O"))
        open_ws.triggered.connect(self._open_workspace)
        file_menu.addAction(open_ws)

        save_ws = QAction("💾 Save Workspace", self)
        save_ws.setShortcut(QKeySequence("Ctrl+S"))
        save_ws.triggered.connect(self._save_workspace)
        file_menu.addAction(save_ws)

        save_ws_as = QAction("💾 Save As…", self)
        save_ws_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_ws_as.triggered.connect(self._save_workspace_as)
        file_menu.addAction(save_ws_as)

        file_menu.addSeparator()

        load_topo = QAction("🕸️ Load Topology…", self)
        load_topo.triggered.connect(self._load_topology)
        file_menu.addAction(load_topo)

        load_map = QAction("🗺️ Load Topology Map…", self)
        load_map.triggered.connect(self._load_topology_map)
        file_menu.addAction(load_map)

        font_cfg = QAction("🔤 TTY Font…", self)
        font_cfg.triggered.connect(self._configure_font)
        file_menu.addAction(font_cfg)

        file_menu.addSeparator()

        quit_action = QAction("🚪 Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # ── View ──
        view_menu: QMenu = menubar.addMenu("&View")

        zoom_fit = QAction("🔍 Zoom Fit", self)
        zoom_fit.setShortcut(QKeySequence("Ctrl+0"))
        zoom_fit.triggered.connect(self._topology.fit_view)
        view_menu.addAction(zoom_fit)

        zoom_reset = QAction("🔍 Zoom 100%", self)
        zoom_reset.setShortcut(QKeySequence("Ctrl+1"))
        zoom_reset.triggered.connect(self._topology.reset_zoom)
        view_menu.addAction(zoom_reset)

        view_menu.addSeparator()

        self._hotspot_act = QAction("👁️ Show Hotspot Overlay", self)
        self._hotspot_act.setCheckable(True)
        self._hotspot_act.toggled.connect(self._topology.toggle_hotspot_overlay)
        view_menu.addAction(self._hotspot_act)

        view_menu.addSeparator()

        self._editor_act = QAction("✏️ Map Editor", self)
        self._editor_act.setCheckable(True)
        self._editor_act.setShortcut(QKeySequence("F2"))
        self._editor_act.toggled.connect(self._on_toggle_editor)
        view_menu.addAction(self._editor_act)

        view_menu.addSeparator()

        self._bring_front_act = QAction("🔝 Bring to Front on URI", self)
        self._bring_front_act.setCheckable(True)
        self._bring_front_act.setChecked(False)
        self._bring_front_act.setToolTip(
            "When checked, the window will be brought to front\n"
            "when a second instance sends a URI argument"
        )
        self._bring_front_act.toggled.connect(self._on_toggle_bring_to_front)
        view_menu.addAction(self._bring_front_act)

        # ── Devices ──
        device_menu: QMenu = menubar.addMenu("&Devices")

        add_dev = QAction("➕ Add Device…", self)
        add_dev.triggered.connect(self._add_device_dialog)
        device_menu.addAction(add_dev)

        eve_import = QAction("🌐 Import from EVE-NG…", self)
        eve_import.triggered.connect(self._import_from_eveng)
        device_menu.addAction(eve_import)

        device_menu.addSeparator()

        conn_all = QAction("🔗 Connect All", self)
        conn_all.triggered.connect(self._connect_all)
        device_menu.addAction(conn_all)

        disc_all = QAction("🔌 Disconnect All", self)
        disc_all.triggered.connect(self._disconnect_all)
        device_menu.addAction(disc_all)

        device_menu.addSeparator()

        send_all = QAction("📤 Send Script to All…", self)
        send_all.triggered.connect(self._send_all_dialog)
        device_menu.addAction(send_all)

        # ── Settings menu ──
        settings_menu: QMenu = menubar.addMenu("&Settings")

        whisper_action: QAction = settings_menu.addAction("🎙️ Whisper Configuration…")
        whisper_action.setShortcut("Ctrl+Shift+W")
        whisper_action.triggered.connect(self._open_whisper_settings)

        rules_action: QAction = settings_menu.addAction("📋 NLP Rules Editor…")
        rules_action.setShortcut("Ctrl+Shift+R")
        rules_action.triggered.connect(self._open_rules_editor)
        settings_menu.addSeparator()

        # 🔢 Indentation size submenu
        indent_menu: QMenu = settings_menu.addMenu("📐 Script Editor Indentation")
        self._indent_group: QActionGroup = QActionGroup(self)
        self._indent_group.setExclusive(True)

        for n in range(1, 9):  # 1..8
            label = f"{n} space" if n == 1 else f"{n} spaces"
            if n == 1:
                label += "  (Cisco default)"
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(n)
            act.setChecked(n == self._indent_size)
            act.triggered.connect(
                lambda _checked=False, val=n: self._set_indent_size(val)
            )
            self._indent_group.addAction(act)
            indent_menu.addAction(act)

        # ── Help ──
        help_menu: QMenu = menubar.addMenu("&Help")

        shortcuts_act = QAction("⌨️ Keyboard Shortcuts", self)
        shortcuts_act.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_act)

        help_menu.addSeparator()

        about_act = QAction("ℹ️ About Pyqttyai", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _setup_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 🎨 Topology viewer (left)
        self._topology = TopologyViewer()
        self._topology.device_clicked.connect(self._on_topology_device_clicked)
        self._topology.editor_deactived.connect(
            lambda: self._editor_vtool_btn.setChecked(False)
        )
        splitter.addWidget(self._topology)

        # 🧰 Vertical toolbar (middle) ──────────────────────
        vtoolbar = QWidget()
        vtoolbar.setObjectName("verticalToolbar")
        vtoolbar.setFixedWidth(58)
        vtoolbar.setStyleSheet(
            "QWidget#verticalToolbar { background-color: #181825; }"
            "QToolButton {"
            "  background-color: transparent;"
            "  color: #cdd6f4;"
            "  border: none;"
            "  padding: 8px 4px;"
            "  font-size: 18px;"
            "}"
            "QToolButton:hover { background-color: #313244; }"
            "QToolButton:pressed { background-color: #45475a; }"
            "QToolButton:checked {"
            "  background-color: #45475a;"
            "  border-left: 3px solid #89b4fa;"
            "}"
        )
        vbox = QVBoxLayout(vtoolbar)
        vbox.setContentsMargins(4, 6, 4, 6)
        vbox.setSpacing(4)

        # 🎙️ Microphone with VU at the very top
        self._toolbar_mic = MicVuButton(
            self._transcription_service,
            position=MicVuButton.Position.BOTTOM,
            shape=MicVuButton.Shape.THIN_VERTICAL,
            auto_enable=True,
            noise_level=self._whisper_config.noise_level,
            auto_transcribe_idle_seconds=self._whisper_config.delay_transcription,
        )
        self._toolbar_mic.setFixedWidth(50)
        self._toolbar_mic.transcribed.connect(self._on_transcription_done)
        self._toolbar_mic.failed.connect(self._on_transcription_failed)
        vbox.addWidget(self._toolbar_mic)

        # ── Separator ──
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #45475a;")
        vbox.addWidget(sep)

        # 🛠️ Tool buttons (replicate the previous toolbar)
        self._add_vtool_button(vbox, "💾", "Save Workspace (Ctrl+S)",
                                self._save_workspace)
        self._add_vtool_button(vbox, "📤", "Send script to all connected devices",
                                self._send_all_dialog)
        self._add_vtool_button(vbox, "🔗", "Connect all devices",
                                self._connect_all)
        self._add_vtool_button(vbox, "🔌", "Disconnect all devices",
                                self._disconnect_all)

        sep2 = QWidget()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background-color: #45475a;")
        vbox.addWidget(sep2)

        self._add_vtool_button(vbox, "➕", "Add Device",
                                self._add_device_dialog)
        self._add_vtool_button(vbox, "🌐", "Import nodes from EVE-NG lab",
                                self._import_from_eveng)

        sep3 = QWidget()
        sep3.setFixedHeight(1)
        sep3.setStyleSheet("background-color: #45475a;")
        vbox.addWidget(sep3)

        self._add_vtool_button(vbox, "🕸️", "Load Topology Image",
                                self._load_topology)
        self._add_vtool_button(vbox, "🗺️", "Load Topology Map",
                                self._load_topology_map)

        self._editor_vtool_btn = self._add_vtool_button(
            vbox, "✏️", "Toggle Map Editor (F2)",
            None, checkable=True,
        )
        self._editor_vtool_btn.toggled.connect(self._on_toggle_editor)

        self._add_vtool_button(vbox, "🔤", "Configure TTY Font",
                                self._configure_font)

        vbox.addStretch()
        splitter.addWidget(vtoolbar)

        # 📑 Tabs (right)
        self._tab_bar = _ClickableTabBar()
        self._tab_bar.icon_clicked.connect(self._on_tab_icon_clicked)
        self._tab_bar.tab_double_clicked.connect(self._on_tab_double_clicked)

        self._tabs = QTabWidget()
        self._tabs.setTabBar(self._tab_bar)
        self._tabs.setMovable(True)
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close)
        splitter.addWidget(self._tabs)

        # 🚫 prevent the toolbar column from being collapsed/resized
        splitter.setCollapsible(0, True)   # topology can collapse
        splitter.setCollapsible(1, False)  # toolbar fixed
        splitter.setCollapsible(2, True)  # tabs always visible
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 7)

        splitter.setSizes([350, 58, 850])
        self.setCentralWidget(splitter)
        self.resize(2 * sum(splitter.sizes()), self.height())

    def _add_vtool_button(self, layout, emoji: str, tooltip: str,
                        callback, checkable: bool = False):
        """🛠️ Helper to create a uniform vertical-toolbar button."""

        btn = QToolButton()
        btn.setText(emoji)
        btn.setToolTip(tooltip)
        btn.setFixedSize(48, 40)
        btn.setCheckable(checkable)
        if callback is not None:
            btn.clicked.connect(callback)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        return btn

    def _open_rules_editor(self):
        """📋 Open the voice transcription rules editor."""
        dlg = RulesEditorDialog(
            ruleset=self._voice_rules,
            shared_service=self._transcription_service,
            config=self._whisper_config,
            parent=self,
        )
        dlg.rules_saved.connect(self._on_rules_saved)
        dlg.exec()

    def _on_rules_saved(self, ruleset: RuleSet):
        """📢 Called whenever the editor saves."""
        self._voice_rules = ruleset
        self._statusbar.showMessage("✅ NLP rules saved")

    def _toggle_mic_shortcut(self):
        """🎹 Ctrl+Space — toggle the mic button programmatically."""
        new_state = not self._toolbar_mic.is_active()
        self._toolbar_mic.set_active(new_state)
        self._toolbar_mic.toggled.emit(new_state)  # 🔔 trigger same logic as click

    def _on_transcription_done(self, result: dict) -> None:
        """📝 Whisper finished — apply NLP rules and inject into the active tab."""

        # 🚫 Settings dialog open (or other modal) → suppress injection
        if self._transcription_service and \
                self._transcription_service.property("suppress_injection"):
            return

        text = (result.get("text") or "").strip()
        if not text:
            self._statusbar.showMessage("🤐 (empty transcription)", 10000)
            return

        try:
            normalized = self._voice_rules.apply(text.strip())
        except (ValueError, KeyError, AttributeError, re.error) as e:
            # 🛟 Rule failure is not fatal — fall back to raw text,
            #    but tell the user something went wrong.
            normalized = f"⚠ Rule error: {e}"
        finally:
            lang = result.get("language", "?")
            prob = result.get("language_probability", 0.0)
            self._statusbar.showMessage(
                f"📝 [{lang} {prob:.0%}] "
                f"{self._truncate(text)} → {self._truncate(normalized)}",
                10000,
            )
            if normalized.startswith('⚠'):  # error
                normalized = text.strip()

        current = self._tabs.currentWidget()
        if not isinstance(current, DeviceTab):
            current = self._create_tab_from_dict({"name": "new"})

        # 🧠 Decide whether we need a leading space:
        #    look at the character immediately BEFORE/AFTER the cursor in the editor.
        cursor = current._editor.textCursor()
        if cursor.position() > 0:
            # Peek the previous character
            probe = current._editor.textCursor()
            probe.setPosition(cursor.position() - 1)
            probe.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            prev_char = probe.selectedText()
            if prev_char and re.match(r'\w', prev_char):
                normalized = " " + normalized
            probe.setPosition(cursor.position() + 1)
            probe.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            next_char = probe.selectedText()
            if next_char and re.match(r'\w', next_char):
                normalized += " "

        current.insert_script_text(normalized)

    def _update_indent_label(self):
        """📐 Refresh the indent indicator in the status bar."""
        n = self._indent_size
        unit = "space" if n == 1 else "spaces"
        self._indent_label.setText(f"📐 {n} {unit}")

    @staticmethod
    def _truncate(s: str, n: int = 60) -> str:
        """Truncate a string for status-bar display."""
        return s if len(s) <= n else s[:n] + "…"

    def _on_transcription_failed(self, msg: str):
        """🚨 Whisper error."""
        self._statusbar.showMessage(f"🚨 Transcription failed: {msg}")

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # 📐 Indentation indicator (permanent, right side)
        self._indent_label = QLabel()
        self._indent_label.setToolTip(
            "Script editor indentation size\n"
            "Change it in: Settings → 📐 Script Editor Indentation"
        )
        self._indent_label.setStyleSheet(
            "color: #94e2d5; padding: 2px 10px; "
            "border-radius: 3px; font-weight: bold; "
            "background: #313244;"
        )
        self._statusbar.addPermanentWidget(self._indent_label)
        self._update_indent_label()

        # 🎯 Persistent backend indicator (right side)
        self._backend_label = QLabel("🏠 local")
        self._backend_label.setStyleSheet(
            "color: #a6adc8; padding: 2px 10px; "
            "border-radius: 3px; font-weight: bold;"
        )
        self._statusbar.addPermanentWidget(self._backend_label)

        self._statusbar.showMessage("Ready — Open a workspace to begin")

    # ── Tab navigation ────────────────────────────────────

    def _next_tab(self, direction):
        """Change current tab left (-1) or right (+1)."""
        count = self._tabs.count()
        if count > 1:
            new_index = self._tabs.currentIndex() + direction
            if -1 < new_index < count:
                self._tabs.setCurrentIndex(new_index)

    def _move_current_tab(self, direction: int):
        """Move the current tab left (-1) or right (+1)."""
        bar = self._tabs.tabBar()
        current = self._tabs.currentIndex()
        target = current + direction

        if 0 <= target < self._tabs.count():
            bar.moveTab(current, target)
            self._tabs.setCurrentIndex(0)
            self._tabs.setCurrentIndex(target)

    # ── Tab close ──────────────────────────────────────────

    def _on_tab_close(self, index: int):
        tab = self._tabs.widget(index)
        if not isinstance(tab, DeviceTab):
            self._tabs.removeTab(index)
            return

        if tab.device.status == DeviceStatus.CONNECTED:
            tab.disconnect_device()

        self._tabs.removeTab(index)
        tab.deleteLater()

    # ── Tab icon click → connect / disconnect ──────────────

    def _on_tab_icon_clicked(self, index: int):
        tab = self._tabs.widget(index)
        if not isinstance(tab, DeviceTab):
            return
        if tab.device.status == DeviceStatus.CONNECTED:
            tab.disconnect_device()
        elif tab.device.status == DeviceStatus.DISCONNECTED:
            tab.connect_device()

    # ── Tab double-click → edit device ─────────────────────

    def _on_tab_double_clicked(self, index: int):
        tab = self._tabs.widget(index)
        if not isinstance(tab, DeviceTab):
            return

        dev = tab.device
        dev_dict = {
            "name": dev.name,
            "host": dev.host,
            "port": dev.port,
            "protocol": dev.protocol.value,
            "username": dev.username,
            "password": dev.password,
            "description": dev.description,
        }

        dlg = DeviceDialog(dev_dict=dev_dict, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = dlg.to_dict()

        conn_changed = (
            dev.host != new_data["host"]
            or dev.port != new_data["port"]
            or dev.protocol.value != new_data["protocol"]
            or dev.username != new_data["username"]
            or dev.password != new_data["password"]
        )

        if conn_changed and dev.status == DeviceStatus.CONNECTED:
            tab.disconnect_device()

        dev.name = new_data["name"]
        dev.host = new_data["host"]
        dev.port = new_data["port"]
        dev.protocol = Protocol(new_data["protocol"])
        dev.username = new_data["username"]
        dev.password = new_data["password"]
        dev.description = new_data["description"]

        self._tabs.setTabText(index, dev.display_name)
        self._statusbar.showMessage(f"Updated device: {dev.name}")

    def _on_device_status_changed(self, device: Device):
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab) and tab.device is device:
                self._tabs.setTabIcon(i, _make_status_icon(device.status))
                status_text = {
                    DeviceStatus.DISCONNECTED: "Disconnected",
                    DeviceStatus.CONNECTING: "Connecting…",
                    DeviceStatus.CONNECTED: "Connected",
                }
                self._statusbar.showMessage(
                    f"{device.name}: {status_text.get(device.status, '?')}"
                )
                break

    # ── Topology device clicked → switch tab ───────────────

    def _on_topology_device_clicked(self, device_name: str):
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                if tab.device.name.lower() == device_name.lower():
                    self._tabs.setCurrentIndex(i)
                    self._statusbar.showMessage(f"Switched to: {tab.device.name}")
                    return

        self._statusbar.showMessage(
            f"⚠ No tab found for '{device_name}' — add the device first"
        )

    # ── Connect / Disconnect All ───────────────────────────

    def _connect_all(self):
        count = 0
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                if tab.device.status == DeviceStatus.DISCONNECTED:
                    tab.connect_device()
                    count += 1
        self._statusbar.showMessage(f"Connecting {count} device(s)...")

    def _disconnect_all(self):
        count = 0
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                if tab.device.status != DeviceStatus.DISCONNECTED:
                    tab.disconnect_device()
                    count += 1
        self._statusbar.showMessage(f"Disconnected {count} device(s)")

    # ── Send Script to All ─────────────────────────────────

    def _send_all_dialog(self):
        tabs = []
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                tabs.append(tab)

        dlg = SendAllDialog(tabs, self._send_all_scripts, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._send_all_scripts = dlg.collect_script_tabs_data()
            return

        # Persist script tabs
        self._send_all_scripts = dlg.collect_script_tabs_data()

        selected_tabs = dlg.selected_tabs()
        if not selected_tabs:
            return

        use_own = dlg.use_own_script()
        delay = dlg.active_delay_ms()

        if use_own:
            count = 0
            for tab in selected_tabs:
                if tab.device.status == DeviceStatus.CONNECTED:
                    original_delay = tab._delay_spin.value()
                    tab._delay_spin.setValue(delay)
                    tab._send_script()
                    tab._delay_spin.setValue(original_delay)
                    count += 1
        else:
            script = dlg.active_script_text()
            if not script:
                return

            count = 0
            for tab in selected_tabs:
                if tab.device.status == DeviceStatus.CONNECTED:
                    original_script = tab.get_script_text()
                    original_delay = tab._delay_spin.value()
                    tab.set_script_text(script)
                    tab._delay_spin.setValue(delay)
                    tab._send_script()
                    tab.set_script_text(original_script)
                    tab._delay_spin.setValue(original_delay)
                    count += 1

        self._statusbar.showMessage(f"Script sent to {count} device(s)")

    # ── Topology ───────────────────────────────────────────

    def _load_topology(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Topology Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.svg *.webp);;All Files (*)",
        )
        if not path:
            return
        self._topology_path = path
        self._topology.load_image(path)
        self._statusbar.showMessage(f"Topology loaded: {Path(path).name}")

    def _load_topology_map(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Topology Map",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        self._topology.load_map(path)
        self._topology_map_path = path
        self._statusbar.showMessage(f"Topology map loaded: {Path(path).name}")

    # ── Font Configuration ─────────────────────────────────

    def _configure_font(self):
        dlg = FontConfigDialog(
            current_family=self._tty_font_family,
            current_size=self._tty_font_size,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._tty_font_family = dlg.selected_family()
        self._tty_font_size = dlg.selected_size()

        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                tab._console.apply_font(self._tty_font_family, self._tty_font_size)

        self._statusbar.showMessage(
            f"Font: {self._tty_font_family} {self._tty_font_size}pt"
        )

    # ── Workspace ──────────────────────────────────────────

    def _open_workspace(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Workspace", "", "JSON Files (*.json)"
        )
        if not path:
            return
        self._workspace_path = path
        self._load_workspace(path)
        self._statusbar.showMessage(f"Loaded: {path}")

    def _load_workspace(self, path: str):
        with open(path, "r") as f:
            data = json.load(f)

        self._devices = data.get("devices", [])
        self._topology_path = data.get("topology", "")
        self._topology_map_path = data.get("topology_map", "")
        self._tty_font_family = data.get("tty_font_family", "")
        self._tty_font_size = data.get("tty_font_size", 12)
        self._send_all_scripts = data.get("send_all_scripts", [])

        if self._topology_path:
            self._topology.load_image(self._topology_path)

        if self._topology_map_path and not self._topology.current_map_path:
            self._topology.load_map(self._topology_map_path)

        self._open_device_tabs()

    def _open_device_tabs(self):
        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            w.deleteLater()

        for dev in self._devices:
            self._create_tab_from_dict(dev)

    def _create_tab_from_dict(self, dev: dict) -> DeviceTab:
        dev_obj = Device(
            name=dev.get("name", "?"),
            host=dev.get("host", ""),
            port=dev.get("port", 22),
            protocol=Protocol(dev.get("protocol", "telnet")),
            username=dev.get("username", ""),
            password=dev.get("password", ""),
            description=dev.get("description", ""),
            eve_node_id=dev.get("eve_node_id"),
        )
        tab = DeviceTab(dev_obj, self)
        tab._editor.set_indent_size(self._indent_size)
        tab._console.apply_font(self._tty_font_family, self._tty_font_size)
        tab.status_changed.connect(self._on_device_status_changed)
        tab.apply_rules_requested.connect(self._on_apply_rules_to_line)

        idx = self._tabs.addTab(tab, dev_obj.display_name)
        self._tabs.setTabIcon(idx, _make_status_icon(DeviceStatus.DISCONNECTED))

        script = dev.get("script", "")
        if script:
            tab.set_script_text(script)

        return tab

    def _on_apply_rules_to_line(self, tab: "DeviceTab", line_text: str):
        """🎯 Ctrl+Shift+A on the script editor — apply NLP rules to current line."""
        if not line_text.strip():
            self._statusbar.showMessage("🤐 (empty line — nothing to apply)", 10000)
            return

        try:
            normalized = self._voice_rules.apply(line_text)
        except (ValueError, KeyError, AttributeError, re.error) as e:
            self._statusbar.showMessage(f"⚠ Rule error: {e}", 10000)
            return

        if normalized == line_text:
            self._statusbar.showMessage(
                f"📋 No rule matched: {self._truncate(line_text)}", 10000
            )
            return

        tab._editor.replace_current_line(normalized)
        self._statusbar.showMessage(
            f"✅ Rules applied: {self._truncate(line_text)} → {self._truncate(normalized)}",
            5000,
        )

    def _save_workspace(self, new_workspace=False):
        if not self._workspace_path or new_workspace:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Workspace", "", "JSON Files (*.json)"
            )
            if not path:
                return
            self._workspace_path = path

        devices = []
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                dev = tab.device
                devices.append({
                    "name": dev.name,
                    "host": dev.host,
                    "port": dev.port,
                    "protocol": dev.protocol.value,
                    "username": dev.username,
                    "password": dev.password,
                    "description": dev.description,
                    "eve_node_id": dev.eve_node_id,
                    "script": tab.get_script_text(),
                })

        topo = self._topology.current_image_path or self._topology_path
        topo_map = self._topology.current_map_path or self._topology_map_path

        data = {
            "devices": devices,
            "topology": topo,
            "topology_map": topo_map,
            "tty_font_family": self._tty_font_family,
            "tty_font_size": self._tty_font_size,
            "send_all_scripts": self._send_all_scripts,
        }

        with open(self._workspace_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self._statusbar.showMessage(f"Saved: {self._workspace_path}")

    def _save_workspace_as(self):
        self._save_workspace(new_workspace=True)

    # ── Add Device ─────────────────────────────────────────

    def _add_device_dialog(self):
        dlg = DeviceDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        dev_dict = dlg.to_dict()
        self._devices.append(dev_dict)

        tab = self._create_tab_from_dict(dev_dict)
        self._tabs.setCurrentWidget(tab)
        self._statusbar.showMessage(f"Added device: {tab.device.name}")

    # ── Import from EVE-NG ─────────────────────────────────

    def _import_from_eveng(self):
        dlg = EveNgImportDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        nodes = dlg.selected_nodes()
        if not nodes:
            return

        count = 0
        for node in nodes:
            existing = self._find_tab_by_connection(
                "telnet", node["host"], node["port"]
            )
            if existing is not None:
                continue

            dev_dict = {
                "name": node["name"],
                "host": node["host"],
                "port": node["port"],
                "protocol": "telnet",
                "username": "",
                "password": "",
                "description": f"EVE-NG: {node['template']}",
                "eve_node_id": node["node_id"],
                "script": "",
            }
            self._devices.append(dev_dict)
            self._create_tab_from_dict(dev_dict)
            count += 1

        self._statusbar.showMessage(
            f"Imported {count} nodes from EVE-NG ({dlg.eve_host()})"
        )

    # ── Handle CLI argument ────────────────────────────────

    def handle_argument(self, arg: str):
        arg = arg.strip()

        if arg.lower().endswith(".json"):
            path = os.path.abspath(arg)
            if os.path.isfile(path):
                self._workspace_path = path
                self._load_workspace(path)
                self._statusbar.showMessage(f"Loaded: {path}")
            else:
                print(f"⚠ Workspace not found: {path}")

        elif "://" in arg:
            parsed = urlparse(arg)
            scheme = (parsed.scheme or "").lower()

            if scheme not in SUPPORTED_SCHEMES:
                print(f"⚠ Unsupported protocol: {scheme}://")
                return

            host = parsed.hostname or ""
            username = parsed.username or ""
            password = parsed.password or ""

            default_ports = {"telnet": 23, "ssh": 22}
            port = parsed.port or default_ports.get(scheme, 23)

            if not host:
                print(f"⚠ Invalid URI: {arg}")
                return

            existing_index = self._find_tab_by_connection(scheme, host, port)
            if existing_index is not None:
                self._tabs.setCurrentIndex(existing_index)
            else:
                dev_dict = {
                    "name": f"{host}:{port}",
                    "host": host,
                    "port": port,
                    "protocol": scheme,
                    "username": username,
                    "password": password,
                    "description": f"Added via {scheme}:// URI",
                    "eve_node_id": None,
                    "script": "",
                }
                self._devices.append(dev_dict)
                tab = self._create_tab_from_dict(dev_dict)
                self._tabs.setCurrentWidget(tab)

        # ── Bring window to front ──
        self._bring_to_front()

    def _on_toggle_bring_to_front(self, checked: bool):
        self._bring_to_front_enabled = checked
        state = "enabled" if checked else "disabled"
        self._statusbar.showMessage(f"Bring to Front: {state}")

    def _bring_to_front(self):
        """Force the window to the front across X11, Wayland, and Windows."""
        if self._bring_to_front_enabled:
            if platform.system() == "Windows":
                # Windows: use Win32 API to force foreground
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                hwnd = int(self.winId())

                # Get the foreground window's thread
                foreground_hwnd = user32.GetForegroundWindow()
                foreground_tid = user32.GetWindowThreadProcessId(
                    foreground_hwnd, None
                )
                current_tid = kernel32.GetCurrentThreadId()

                # Attach to foreground thread to bypass focus restriction
                if foreground_tid != current_tid:
                    user32.AttachThreadInput(foreground_tid, current_tid, True)

                # Restore if minimized
                SW_RESTORE = 9
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, SW_RESTORE)

                # Force to foreground
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                user32.SetActiveWindow(hwnd)

                # Detach thread
                if foreground_tid != current_tid:
                    user32.AttachThreadInput(foreground_tid, current_tid, False)

            else:
                # Linux/Wayland: hide + show workaround
                self.showMinimized()
                self.hide()
                self.showNormal()

        self.show()
        self.raise_()
        self.activateWindow()

    def _find_tab_by_connection(self, scheme: str, host: str, port: int) -> int | None:
        for i in range(self._tabs.count()):
            widget = self._tabs.widget(i)
            if isinstance(widget, DeviceTab):
                d = widget.device
                if (d.protocol.value == scheme
                        and d.host == host
                        and d.port == port):
                    return i
        return None

    def _on_toggle_editor(self, active: bool):
        """Toggle the map editor mode."""
        # Sync both menu and toolbar button
        self._editor_act.blockSignals(True)
        self._editor_vtool_btn.blockSignals(True)
        self._editor_act.setChecked(active)
        self._editor_vtool_btn.setChecked(active)
        self._editor_act.blockSignals(False)
        self._editor_vtool_btn.blockSignals(False)

        map_editor_active = self._topology.toggle_map_editor(active)

        if active:
            if map_editor_active:
                self._statusbar.showMessage("✏️ Map Editor active — Draw, drag, resize hotspots")
            else:
                self._editor_vtool_btn.toggle()
                self._statusbar.showMessage("✏️ Map Editor not activated — Load a topology image first.")
        else:
            self._statusbar.showMessage("Map Editor closed")

    # ── Help ───────────────────────────────────────────────

    def _show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _show_shortcuts(self):
        dlg = ShortcutsDialog(self)
        dlg.exec()

    # ── Slots ──────────────────────────────────────────────

    def _open_whisper_settings(self):
        dlg = WhisperSettingsDialog(
            self, self._whisper_config, self._transcription_service)
        dlg.config_saved.connect(self._on_whisper_config_saved)
        dlg.exec()

    def _on_whisper_config_saved(self, cfg: WhisperConfig):
        self._whisper_config = cfg
        # 🔄 Notify any active transcription components
        # e.g.: self._voice_manager.reload_config(cfg)
        if self.statusBar():
            self.statusBar().showMessage(
                f"🎙️ Whisper updated: {cfg.summary()}",
                5000,
            )

        # 🔄 Tell any active transcription components to reload
        # self._voice_manager.reload_config(cfg)  # if it have one

    def _set_indent_size(self, n: int):
        """🔢 Update indentation for all open ScriptEditors and persist."""
        n = max(1, min(8, int(n)))
        self._indent_size = n
        self._settings.setValue("editor/indent_size", n)

        # Propagate to all open DeviceTab editors
        applied = 0
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, DeviceTab):
                editor = getattr(tab, "_editor", None)
                if editor is not None and hasattr(editor, "set_indent_size"):
                    editor.set_indent_size(n)
                    applied += 1

        # 🔄 Refresh the visual indicator
        self._update_indent_label()

        unit = "space" if n == 1 else "spaces"
        self._statusbar.showMessage(
            f"📐 Indentation set to {n} {unit} (applied to {applied} editor(s))",
            4000,
        )

    # ── Convenience for transcription consumers ────────────

    @property
    def whisper_config(self) -> WhisperConfig:
        return self._whisper_config
