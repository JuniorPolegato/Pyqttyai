"""Animated splash screen for Pyqttyai."""

import time
from pathlib import Path

from PyQt6.QtWidgets import QSplashScreen, QWidget
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient, QPen
from PyQt6.QtCore import Qt, QRectF, QEvent


from .. import __version__

# ── Resolve images directory relative to THIS file ──
IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "images"


class PyqttyaiSplash(QSplashScreen):
    """Dark-themed splash screen with logo and loading status."""

    def __init__(self):  # , parent):
        # ── Load logo ──
        logo_path = IMAGES_DIR / "pyqttyai_1024.png"
        if logo_path.exists():
            logo = QPixmap(str(logo_path))
        else:
            logo = QPixmap(512, 512)
            logo.fill(QColor("#1e1e2e"))

        # ── Build splash pixmap ──
        splash_w, splash_h = 520, 380
        pixmap = QPixmap(splash_w, splash_h)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Background with rounded corners
        bg_rect = QRectF(0, 0, splash_w, splash_h)
        gradient = QLinearGradient(0, 0, 0, splash_h)
        gradient.setColorAt(0.0, QColor("#1e1e2e"))
        gradient.setColorAt(1.0, QColor("#11111b"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#313244"), 2))
        painter.drawRoundedRect(bg_rect, 16, 16)

        # Border accent (top line)
        painter.setPen(QPen(QColor("#89b4fa"), 3))
        painter.drawLine(20, 2, splash_w - 20, 2)

        # Logo (centered, scaled)
        logo_size = 180
        scaled = logo.scaled(
            logo_size, logo_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        logo_x = (splash_w - scaled.width()) // 2
        painter.drawPixmap(logo_x, 30, scaled)

        # App name
        font_title = QFont("sans-serif", 26, QFont.Weight.Bold)
        painter.setFont(font_title)
        painter.setPen(QColor("#89b4fa"))
        title_rect = QRectF(0, 220, splash_w, 40)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, "Pyqttyai")

        # Subtitle
        font_sub = QFont("sans-serif", 10)
        painter.setFont(font_sub)
        painter.setPen(QColor("#a6adc8"))
        sub_rect = QRectF(0, 258, splash_w, 24)
        painter.drawText(
            sub_rect, Qt.AlignmentFlag.AlignCenter,
            "Network Lab Management Terminal",
        )

        # Version
        font_ver = QFont("monospace", 9)
        painter.setFont(font_ver)
        painter.setPen(QColor("#585b70"))
        ver_rect = QRectF(0, 282, splash_w, 20)
        painter.drawText(ver_rect, Qt.AlignmentFlag.AlignCenter, __version__)

        # Bottom area reserved for status message
        painter.setPen(QColor("#313244"))
        painter.drawLine(30, 320, splash_w - 30, 320)

        painter.end()

        super().__init__(pixmap)
        #self.setParent(parent)
        #self.setWindowModality(Qt.WindowModality.WindowModal)
        # self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

        # Style the status message
        self.setStyleSheet(
            "QSplashScreen {"
            "  color: #a6e3a1;"
            "  font-size: 11px;"
            "  font-weight: bold;"
            "}"
        )

        # center_over_parent(self):
        #child_geo = self.frameGeometry()
        #parent_center = self.parent().frameGeometry().center()
        #child_geo.moveCenter(parent_center)
        #self.move(child_geo.topLeft())

    def show_status(self, message: str):
        """Update the loading status message."""
        self.showMessage(
            f"  {message}",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            QColor("#a6e3a1"),
        )

    def event(self, e):
        """Skip QSplashScreen's blocking waitForWidgetMapped()"""
        if e.type() == QEvent.Type.Show:
            # 🆕 Skip QSplashScreen's blocking waitForWidgetMapped()
            # by routing directly to QWidget.event()
            return QWidget.event(self, e)
        return super().event(e)
