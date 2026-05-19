"""Runs editor scripts line-by-line to a device session."""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class ScriptRunner(QObject):
    """Sends script lines one at a time with configurable delay."""
    line_sent = pyqtSignal(int, str)       # line_number, text
    finished = pyqtSignal()
    progress = pyqtSignal(int, int)        # current, total

    def __init__(self, send_func, parent=None):
        super().__init__(parent)
        self._send = send_func
        self._lines: list[str] = []
        self._current = 0
        self._delay_ms = 500
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._send_next)
        self._running = False

    @property
    def delay_ms(self) -> int:
        return self._delay_ms

    @delay_ms.setter
    def delay_ms(self, value: int):
        self._delay_ms = max(50, value)

    def start(self, script_text: str, delay_ms: int = 500):
        """Begin sending script."""
        self._lines = [l for l in script_text.splitlines()]
        self._current = 0
        self._delay_ms = max(50, delay_ms)
        self._running = True
        self._send_next()
        self._timer.start(self._delay_ms)

    def stop(self):
        self._running = False
        self._timer.stop()
        self.finished.emit()

    def _send_next(self):
        if self._current >= len(self._lines) or not self._running:
            self.stop()
            return

        line = self._lines[self._current]
        print(repr(line))
        self._send(line + "\r")
        self.line_sent.emit(self._current, line)
        self.progress.emit(self._current + 1, len(self._lines))
        self._current += 1
