"""Send All Dialog — persistent script tabs sent to multiple devices."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTabBar,
    QListWidget, QListWidgetItem, QAbstractItemView, QCheckBox,
    QSpinBox, QDialogButtonBox, QLabel, QWidget,
    QPushButton, QInputDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QMouseEvent

from .device_tab import DeviceTab
from .script_editor import ScriptEditor
from ..core.device import DeviceStatus, Protocol


# ── Double-click tab bar to rename ────────────────────────

class _RenamableTabBar(QTabBar):
    """Tab bar that allows renaming tabs via double-click."""

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.tabAt(event.position().toPoint())
            if index >= 0:
                self._rename_tab(index)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _rename_tab(self, index: int):
        current_name = self.tabText(index)
        new_name, ok = QInputDialog.getText(
            self, "Rename Script Tab", "Tab name:", text=current_name,
        )
        if ok and new_name.strip():
            self.setTabText(index, new_name.strip())


# ── Script Tab (reuses ScriptEditor from device tabs) ────

class _ScriptTab(QWidget):
    """A single script editor tab using the same ScriptEditor as device tabs."""

    def __init__(self, text: str = "", delay: int = 500, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Same ScriptEditor used in DeviceTab ──
        self._editor = ScriptEditor()
        if text:
            self._editor.setPlainText(text)
        layout.addWidget(self._editor, stretch=1)

        # ── Bottom row: delay + line count ──
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 2, 0, 0)

        delay_label = QLabel("Delay between lines:")
        delay_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        bottom.addWidget(delay_label)

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(50, 10000)
        self._delay_spin.setValue(delay)
        self._delay_spin.setSingleStep(100)
        self._delay_spin.setSuffix(" ms")
        bottom.addWidget(self._delay_spin)

        bottom.addStretch()

        self._line_count = QLabel("Lines: 0")
        self._line_count.setStyleSheet("color: #6c7086; font-size: 11px;")
        bottom.addWidget(self._line_count)

        layout.addLayout(bottom)

        self._editor.textChanged.connect(self._update_line_count)
        self._update_line_count()

    def _update_line_count(self):
        text = self._editor.toPlainText()
        lines = len([l for l in text.splitlines() if l.strip()]) if text.strip() else 0
        self._line_count.setText(f"Lines: {lines}")

    def get_text(self) -> str:
        return self._editor.toPlainText()

    def set_text(self, text: str):
        self._editor.setPlainText(text)

    def get_delay(self) -> int:
        return self._delay_spin.value()

    def set_delay(self, delay: int):
        self._delay_spin.setValue(delay)


# ── Send All Dialog ───────────────────────────────────────

class SendAllDialog(QDialog):
    """Dialog with persistent script tabs and device selection."""

    def __init__(
        self,
        device_tabs: list[DeviceTab],
        script_tabs_data: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Send Script to All Devices")
        self.setMinimumSize(640, 640)

        self._has_connected = any(
            t.device.status == DeviceStatus.CONNECTED for t in device_tabs
        )

        layout = QVBoxLayout(self)

        # ── Device list ──
        dev_label = QLabel("Select target devices:")
        dev_label.setStyleSheet("font-weight: bold; margin-bottom: 4px;")
        layout.addWidget(dev_label)

        self._device_list = QListWidget()
        self._device_list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        self._device_list.setMaximumHeight(160)
        self._device_list.setStyleSheet(
            "QListWidget { background-color: #313244; border: 1px solid #45475a; "
            "border-radius: 4px; }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:selected { background-color: #45475a; color: #a6e3a1; }"
        )

        for tab in device_tabs:
            dev = tab.device
            connected = dev.status == DeviceStatus.CONNECTED
            proto_icon = "🔒" if dev.protocol == Protocol.SSH else "📡"
            status_icon = "🟢" if connected else "🔴"
            label = f"{status_icon} {proto_icon} {dev.name} ({dev.host}:{dev.port})"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, tab)
            self._device_list.addItem(item)

            if not connected:
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsSelectable
                    & ~Qt.ItemFlag.ItemIsEnabled
                )
                item.setForeground(QColor("#6c7086"))
            else:
                item.setSelected(True)

        layout.addWidget(self._device_list)

        # ── Select All devices ──
        self._select_all_cb = QCheckBox("Select All")
        self._select_all_cb.setChecked(True)
        self._select_all_cb.toggled.connect(self._toggle_select_all)
        layout.addWidget(self._select_all_cb)

        # ── Use each device's own script ──
        self._use_own_script_cb = QCheckBox("Use each device's own script")
        self._use_own_script_cb.setToolTip(
            "When checked, each device will send its own script\n"
            "instead of the active script tab below."
        )
        self._use_own_script_cb.toggled.connect(self._on_toggle_own_script)
        layout.addWidget(self._use_own_script_cb)

        # ── Script tabs container (hideable) ──
        self._script_container = QWidget()
        script_layout = QVBoxLayout(self._script_container)
        script_layout.setContentsMargins(0, 4, 0, 0)

        # Tab bar + buttons row
        tabs_header = QHBoxLayout()

        script_label = QLabel("Script tabs:")
        script_label.setStyleSheet("font-weight: bold;")
        tabs_header.addWidget(script_label)
        tabs_header.addStretch()

        add_btn = QPushButton("➕ Add")
        add_btn.setToolTip("Add new script tab")
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(
            "QPushButton { background-color: #313244; color: #a6e3a1; "
            "border: 1px solid #45475a; border-radius: 4px; "
            "padding: 2px 10px; font-size: 12px; }"
            "QPushButton:hover { background-color: #45475a; }"
        )
        add_btn.clicked.connect(self._add_script_tab)
        tabs_header.addWidget(add_btn)

        remove_btn = QPushButton("🗑️ Remove")
        remove_btn.setToolTip("Remove current script tab")
        remove_btn.setFixedHeight(28)
        remove_btn.setStyleSheet(
            "QPushButton { background-color: #313244; color: #f38ba8; "
            "border: 1px solid #45475a; border-radius: 4px; "
            "padding: 2px 10px; font-size: 12px; }"
            "QPushButton:hover { background-color: #45475a; }"
        )
        remove_btn.clicked.connect(self._remove_current_script_tab)
        tabs_header.addWidget(remove_btn)

        script_layout.addLayout(tabs_header)

        # Script QTabWidget with renamable tab bar
        self._script_tab_bar = _RenamableTabBar()
        self._script_tabs = QTabWidget()
        self._script_tabs.setTabBar(self._script_tab_bar)
        self._script_tabs.setMovable(True)
        script_layout.addWidget(self._script_tabs, stretch=1)

        layout.addWidget(self._script_container, stretch=1)

        # ── Load persistent tabs ──
        self._load_script_tabs(script_tabs_data)

        # ── Buttons ──
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._send_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self._send_btn.setText("📤 Send to Selected")
        self._send_btn.setEnabled(self._has_connected)

        cancel_btn = btns.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("✖ Cancel")

        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── Script tab management ──────────────────────────────

    def _load_script_tabs(self, tabs_data: list[dict]):
        """Load script tabs from workspace data."""
        if not tabs_data:
            tabs_data = [{"name": "Script 1", "script": "", "delay": 500}]

        for tab_data in tabs_data:
            name = tab_data.get("name", "Script")
            script = tab_data.get("script", "")
            delay = tab_data.get("delay", 500)
            tab = _ScriptTab(text=script, delay=delay)
            self._script_tabs.addTab(tab, name)

    def _add_script_tab(self):
        """Add a new empty script tab."""
        name, ok = QInputDialog.getText(
            self,
            "New Script Tab",
            "Tab name:",
            text=f"Script {self._script_tabs.count() + 1}",
        )
        if ok and name.strip():
            tab = _ScriptTab()
            idx = self._script_tabs.addTab(tab, name.strip())
            self._script_tabs.setCurrentIndex(idx)

    def _remove_current_script_tab(self):
        """Remove the current script tab (keep at least one)."""
        if self._script_tabs.count() <= 1:
            QMessageBox.information(
                self, "Remove Tab", "At least one script tab is required."
            )
            return

        index = self._script_tabs.currentIndex()
        name = self._script_tabs.tabText(index)
        reply = QMessageBox.question(
            self,
            "Remove Script Tab",
            f"Remove tab \"{name}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            widget = self._script_tabs.widget(index)
            self._script_tabs.removeTab(index)
            widget.deleteLater()

    # ── Device selection ───────────────────────────────────

    def _toggle_select_all(self, checked: bool):
        for i in range(self._device_list.count()):
            item = self._device_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setSelected(checked)

    def _on_toggle_own_script(self, checked: bool):
        self._script_container.setVisible(not checked)

    # ── Public API ─────────────────────────────────────────

    def use_own_script(self) -> bool:
        return self._use_own_script_cb.isChecked()

    def selected_tabs(self) -> list[DeviceTab]:
        result = []
        for item in self._device_list.selectedItems():
            tab = item.data(Qt.ItemDataRole.UserRole)
            if tab:
                result.append(tab)
        return result

    def active_script_text(self) -> str:
        """Return the text from the currently active script tab."""
        tab = self._script_tabs.currentWidget()
        if isinstance(tab, _ScriptTab):
            return tab.get_text()
        return ""

    def active_delay_ms(self) -> int:
        """Return the delay from the currently active script tab."""
        tab = self._script_tabs.currentWidget()
        if isinstance(tab, _ScriptTab):
            return tab.get_delay()
        return 500

    def collect_script_tabs_data(self) -> list[dict]:
        """Collect all script tabs data for workspace persistence."""
        result = []
        for i in range(self._script_tabs.count()):
            tab = self._script_tabs.widget(i)
            name = self._script_tabs.tabText(i)
            if isinstance(tab, _ScriptTab):
                result.append({
                    "name": name,
                    "script": tab.get_text(),
                    "delay": tab.get_delay(),
                })
        return result
