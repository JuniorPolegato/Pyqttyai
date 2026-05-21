"""About dialog for Pyqttyai."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QWidget,
)
from PyQt6.QtGui import QPixmap, QFont, QColor, QDesktopServices
from PyQt6.QtCore import Qt, QUrl

from .. import __version__

# ── Resolve images directory relative to THIS file ──
IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "images"


class AboutDialog(QDialog):
    """About Pyqttyai dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Pyqttyai")
        self.setFixedSize(520, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Logo ──
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = IMAGES_DIR / "pyqttyai_1024.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path)).scaled(
                140, 140,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(pixmap)
        else:
            logo_label.setText("🕸️")
            logo_label.setStyleSheet("font-size: 64px;")
        layout.addWidget(logo_label)

        # ── Banner ──
        banner = QLabel("Pyqttyai")
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setFont(QFont("Sans", 26, QFont.Weight.Bold))
        banner.setStyleSheet(
            "QLabel {"
            "  background-color: #181825; padding: 24px;"
            "  color: #89b4fa;"
            "  border-bottom: 3px solid #45475a;"
            "}"
        )
        layout.addWidget(banner)

        subtitle = QLabel(
            f"v{__version__}  —  Python + Qt + TTY + IA for Network Lab Study"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont("Sans", 9))
        subtitle.setStyleSheet(
            "QLabel { background-color: #181825; padding: 0 0 14px 0; color: #a6adc8; }"
        )
        layout.addWidget(subtitle)

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
        content_layout.setContentsMargins(28, 20, 28, 16)
        content_layout.setSpacing(14)

        description = QLabel(
            "Pyqttyai is a software tool designed to help network administrators "
            "connect to their devices via Telnet/SSH. It supports independent "
            "scripting for Cisco, EVE-NG, Linux, and more."
        )
        description.setWordWrap(True)
        description.setFont(QFont("Sans", 10))
        description.setStyleSheet("QLabel { color: #cdd6f4; background: transparent; }")
        content_layout.addWidget(description)

        # Cards
        content_layout.addWidget(self._make_card(
            "AUTHOR",
            [("Claudio Polegato Junior", True), ("2026 - All rights reserved", False)],
            "#f5c2e7",
        ))
        content_layout.addWidget(self._make_card(
            "LICENSE",
            [
                ("GPL v3", True),
                (
                    "This program is free software: you can redistribute it "
                    "and/or modify it under the terms of the GNU General "
                    "Public License v3 as published by the Free Software "
                    "Foundation.",
                    False,
                ),
            ],
            "#a6e3a1",
        ))
        content_layout.addWidget(self._make_card(
            "THANKS & LAB CREDITS",
            [
                ("Thiago G. Figueiredo", True),
                (
                    "EVE-NG labs, topology images, router configurations, "
                    "and testing across every release.",
                    False,
                ),
            ],
            "#fab387",
        ))

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # ── Footer ──
        footer = QWidget()
        footer.setStyleSheet(
            "QWidget { background-color: #181825; border-top: 1px solid #45475a; }"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 10, 20, 10)

        tech_label = QLabel("Python  |  PyQt6  |  Catppuccin Mocha")
        tech_label.setFont(QFont("Sans", 9))
        tech_label.setStyleSheet("QLabel { color: #6c7086; background: transparent; }")
        footer_layout.addWidget(tech_label)
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

    @staticmethod
    def _make_card(title: str, lines: list[tuple[str, bool]],
                   accent_color: str) -> QFrame:
        """Create a styled info card.

        Args:
            title: Small uppercase section title.
            lines: List of (text, is_bold) tuples.
            accent_color: Hex color for the accent.
        """
        card = QFrame()
        card.setStyleSheet(
            "QFrame {"
            "  background-color: #313244;"
            "  border-radius: 8px;"
            "  border: 1px solid #45475a;"
            "}"
            "QLabel { background: transparent; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 10, 16, 10)
        card_layout.setSpacing(2)

        # Section title (small, uppercase)
        title_label = QLabel(title)
        title_label.setFont(QFont("Sans", 8))
        title_label.setStyleSheet(f"QLabel {{ color: #6c7086; letter-spacing: 1px; }}")
        card_layout.addWidget(title_label)

        for text, is_bold in lines:
            label = QLabel(text)
            label.setWordWrap(True)
            if is_bold:
                label.setFont(QFont("Sans", 11, QFont.Weight.DemiBold))
                label.setStyleSheet(f"QLabel {{ color: {accent_color}; }}")
            else:
                label.setFont(QFont("Sans", 9))
                label.setStyleSheet("QLabel { color: #a6adc8; }")
            card_layout.addWidget(label)

        return card
