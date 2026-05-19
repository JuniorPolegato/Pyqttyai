"""🔑 Quick dialog for prompting an API key with env-var hint."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QDialogButtonBox,
)


class ApiKeyDialog(QDialog):
    """🔑 Prompt user for an API key + offer to remember it for the session."""

    def __init__(self, provider: str, env_var: str, message: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"🔑 {provider.title()} API Key Required")
        self.setMinimumWidth(480)
        self.setModal(True)

        self._provider = provider
        self._env_var = env_var
        self._key: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        header = QLabel(f"<b>🔑 {provider.title()} requires an API key</b>")
        header.setStyleSheet("color: #89b4fa; font-size: 13px;")
        layout.addWidget(header)

        if message:
            note = QLabel(message)
            note.setWordWrap(True)
            note.setStyleSheet("color: #a6adc8; font-size: 11px;")
            layout.addWidget(note)

        tip = QLabel(
            f"💡 <b>Tip:</b> for permanent storage, set the environment "
            f"variable <code>{env_var}</code> in your shell profile "
            f"(<code>~/.zshrc</code>, <code>~/.bashrc</code>) or Windows "
            f"<i>Environment Variables</i>.<br>"
            f"This dialog only stores it for the current session."
        )
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.TextFormat.RichText)
        tip.setStyleSheet(
            "color: #f9e2af; font-size: 11px; "
            "background:#313244; padding:8px 10px; "
            "border-left: 3px solid #f9e2af; border-radius: 3px;"
        )
        layout.addWidget(tip)

        layout.addWidget(QLabel("Paste your API key:"))
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText(f"{env_var}=…")
        layout.addWidget(self._key_edit)

        show_row = QHBoxLayout()
        self._show_cb = QCheckBox("👁 Show key")
        self._show_cb.toggled.connect(self._toggle_echo)
        show_row.addWidget(self._show_cb)

        self._session_cb = QCheckBox("Set as env var for this session")
        self._session_cb.setChecked(True)
        self._session_cb.setToolTip(
            f"Sets {env_var} so child processes (worker) inherit it."
        )
        show_row.addWidget(self._session_cb)
        show_row.addStretch(1)
        layout.addLayout(show_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _toggle_echo(self, on: bool):
        self._key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        )

    def _on_accept(self):
        key = self._key_edit.text().strip()
        if not key:
            self._key_edit.setFocus()
            return
        self._key = key
        if self._session_cb.isChecked():
            os.environ[self._env_var] = key
        self.accept()

    def api_key(self) -> str:
        return self._key
