"""Modal spinner shown during slow async shutdowns."""

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar


class _ShutdownWorker(QThread):
    """Runs the blocking shutdown function in a thread."""
    done = pyqtSignal()

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self._fn()
        except Exception as e:  # 🛡️ never crash on shutdown
            print(f"Shutdown error: {e}")
        self.done.emit()


class ShutdownSpinner(QDialog):
    """Tiny modal that shows '🛑 Closing…' while running a blocking fn.

    Usage:
        ShutdownSpinner.run(parent, "Closing transcription service…",
                            lambda: service.stop())
    """

    def __init__(self, message: str, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setFixedSize(280, 90)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
            QLabel { color: #cdd6f4; font-size: 12px; }
            QProgressBar {
                background-color: #313244;
                border: none;
                border-radius: 3px;
                height: 6px;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        label = QLabel(message)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)

        bar = QProgressBar()
        bar.setRange(0, 0)        # ⏳ indeterminate
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        layout.addWidget(bar)

    @classmethod
    def run(cls, parent, message: str, fn, min_visible_ms: int = 200):
        """Run `fn` in a thread; show spinner if it takes longer than 100ms.

        Blocks until `fn` finishes. Safe to call from the main thread.
        """
        spinner = cls(message, parent)
        worker = _ShutdownWorker(fn, parent)

        # ⏱️ Only show the dialog if the operation is actually slow
        show_timer = QTimer()
        show_timer.setSingleShot(True)
        show_timer.timeout.connect(spinner.show)
        show_timer.start(100)

        worker.done.connect(show_timer.stop)
        worker.done.connect(spinner.accept)
        worker.start()

        # 🔒 Modal-style wait without blocking the event loop
        if worker.isRunning():
            spinner.exec()  # blocks until accept() (or instant-close)

        worker.wait(3000)  # 🛡️ ensure thread joined
