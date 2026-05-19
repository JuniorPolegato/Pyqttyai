#!/usr/bin/env python3
"""Pyqttyai - Python + Qt + TTY + IA for Network Lab Study."""

# Pyqttyai — Python + Qt + TTY + AI network lab companion
# Copyright (C) 2026 Claudio
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import sys
import os
import ctypes
import platform
from pathlib import Path
import time

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QIcon

from pyqttyai.single_instance import SingleInstance
from pyqttyai.widgets.main_window import MainWindow
from pyqttyai.widgets.splash_screen import PyqttyaiSplash
from pyqttyai.core.voice_rules import load_rules

# 🆕 Real loading dependencies
from pyqttyai.core.paths import ensure_all, config_dir
from pyqttyai.core.whisper_config import WhisperConfig
from pyqttyai.audio.transcription_service import TranscriptionService

# ── Base path (works for script, frozen exe, and any CWD) ──
BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"


def main():
    """Main function."""
    app_id = "Pyqttyai"

    if platform.system() == "Windows":
        # Windows Identity
        import multiprocessing
        multiprocessing.freeze_support()  # 🛡️ Required for Windows + PyInstaller
        myappid = "polegatech.pyqttyai.v01"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        QApplication.setDesktopFileName(app_id)

        from pyqttyai.core.winreg_protocols import sync_protocol_registry
        sync_protocol_registry("telnet")
        sync_protocol_registry("ssh")
    else:
        os.environ["DESKTOP_STARTUP_ID"] = app_id
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
        os.environ["QT_LOGGING_RULES"] = (
            "qt.qpa.wayland.*=false;qt.qpa.services=false"
        )

    QApplication.setApplicationName(app_id)
    QApplication.setOrganizationName("Polegatech")

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(IMAGES_DIR / "pyqttyai_256.png")))
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)

    # ── CLI arguments ──
    user_args = sys.argv[1:]

    # ── Single-instance check ──
    instance = SingleInstance()
    if not instance.try_start(user_args):
        print("↗ Forwarded to running instance.")
        sys.exit(0)

    # ═════════════════════════════════════════════════════════
    #  🎬 Splash + real loading pipeline
    # ═════════════════════════════════════════════════════════
    splash = PyqttyaiSplash()
    splash.show()

    # 🗂️ Phase 0: ensure user dirs exist
    splash.show_status("Preparing user directories...")
    ensure_all()
    time.sleep(.3)

    # 🎙️ Phase 1: load Whisper configuration
    splash.show_status("Loading Whisper configuration...")
    whisper_config = WhisperConfig.load()
    cfg_path = config_dir() / WhisperConfig.CONFIG_FILE
    if not cfg_path.exists():
        # 🆕 First run — write defaults so user has a file to inspect/edit
        whisper_config.save()
        print(f"📄 Created default config: {cfg_path}")
    else:
        print(f"📄 Loaded config: {cfg_path}")
    time.sleep(.3)

    # 📋 Phase 1b: load voice rewrite rules
    splash.show_status("Loading NLP rules...")
    voice_rules = load_rules()
    print(f"📋 Loaded {len(voice_rules.rules)} NLP rule(s)")
    time.sleep(.3)

    # 🧩 Phase 2: register plugins (transcription service)
    splash.show_status("Initializing transcription service...")
    transcription_service = TranscriptionService()
    # 🚫 Intentionally NOT calling .start() here.
    # The model (1+ GB, several seconds) loads lazily on main window.
    #transcription_service.start(whisper_config)
    time.sleep(.3)

    # 🪟 Phase 3: build main window with injected dependencies
    splash.show_status("Initializing UI...")
    window = MainWindow(
        whisper_config=whisper_config,
        transcription_service=transcription_service,
        voice_rules=voice_rules,
    )
    time.sleep(.3)

    # ✅ Phase 4: ready
    splash.show_status("Ready!")
    splash.finish(window)
    window.show()

    # ── Argument forwarding ──
    if user_args:
        window.handle_argument(user_args[0])
    instance.message_received.connect(window.handle_argument)

    # 🛑 Graceful service shutdown
    app.aboutToQuit.connect(transcription_service.stop)

    sys.exit(app.exec())


STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QSplitter::handle {
    background-color: #45475a;
    width: 3px;
    height: 3px;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    background-color: #1e1e2e;
}
QTabBar::tab {
    background-color: #313244;
    color: #cdd6f4;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #45475a;
    color: #f5c2e7;
    font-weight: bold;
}
QTabBar::tab:hover {
    background-color: #585b70;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    padding: 6px 14px;
    border-radius: 4px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #585b70;
}
QPushButton:pressed {
    background-color: #6c7086;
}
QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QPushButton#sendBtn {
    background-color: #a6e3a1;
    color: #1e1e2e;
    border: none;
}
QPushButton#sendBtn:hover {
    background-color: #94e2d5;
}
QPushButton#sendBtn:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QPushButton#connectBtn {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
}
QPushButton#disconnectBtn {
    background-color: #f38ba8;
    color: #1e1e2e;
    border: none;
}
QLineEdit, QSpinBox, QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    padding: 4px 8px;
    border-radius: 4px;
}
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
    left: 12px;
    padding: 0 6px;
}
QMenuBar {
    background-color: #181825;
    color: #cdd6f4;
}
QMenuBar::item:selected {
    background-color: #45475a;
}
QMenu {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
}
QMenu::item:selected {
    background-color: #45475a;
}
QStatusBar {
    background-color: #181825;
    color: #a6adc8;
}
QToolBar {
    background-color: #181825;
    border: none;
    spacing: 4px;
    padding: 4px;
}
"""

if __name__ == "__main__":
    main()
