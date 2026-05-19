"""TTY Console widget — terminal output with ANSI support."""

import re
from PyQt6.QtWidgets import QPlainTextEdit, QMenu, QApplication
from PyQt6.QtGui import (
    QFont, QTextCursor, QKeyEvent, QAction, QShortcut, QKeySequence,
)
from PyQt6.QtCore import Qt, pyqtSignal

from .ansi_parser import AnsiState, parse_ansi_text
from .find_replace_bar import FindReplaceBar

# Regex to detect an incomplete escape sequence at the END of a chunk.
# Matches:  \x1b (alone)
#         | \x1b] ... (OSC started, no \x07 or ST yet)
#         | \x1b[ ... (CSI started, no final letter yet)
_INCOMPLETE_ESC_RE = re.compile(
    r"("
    r"\x1b\][^\x07]*$"            # OSC without terminator
    r"|\x1b\[[\d;]*$"             # CSI without final letter
    r"|\x1b$"                      # bare ESC at end
    r")"
)


class TTYConsole(QPlainTextEdit):
    """
    Terminal emulator widget with ANSI color and cursor support.

    Editing is blocked by intercepting all input events.
    Only PTY output (append_ansi) can modify the buffer.
    The cursor remains visible because we do NOT use setReadOnly.
    """
    key_pressed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ansi_state = AnsiState()
        self._pty_writing = False  # guard: only PTY can edit
        self._pending_esc = ""     # buffer for incomplete escape sequences

        # Default font — can be overridden via apply_font()
        self.apply_font()
        self.setCursorWidth(2)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(10000)
        self.setStyleSheet(
            "QPlainTextEdit { background-color: #11111b; color: #a6e3a1; "
            "selection-background-color: #45475a; border: none; }"
        )
        self._input_enabled = True
        self._debug = False
        self._term_cursor_pos = -1
        self._find_bar: FindReplaceBar | None = None

    def set_find_bar(self, find_bar: FindReplaceBar):
        """ 🔎 Find bar """
        self._find_bar = find_bar

    # ── Block direct editing ─────────────────

    def insertFromMimeData(self, source):
        """Block paste into widget. Ctrl+Shift+V pastes to PTY instead."""
        if self._pty_writing:
            super().insertFromMimeData(source)

    def canInsertFromMimeData(self, source):
        if self._pty_writing:
            return super().canInsertFromMimeData(source)
        return False

    def mouseMoveEvent(self, event):
        """Allow selection but prevent drag of selected text."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Restore full interaction flags after mouse release."""
        super().mouseReleaseEvent(event)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.TextEditorInteraction
        )

    def dragEnterEvent(self, event):
        if event.source() is self:
            event.ignore()
        elif event.mimeData().hasText():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.source() is self:
            event.ignore()
        elif event.mimeData().hasText():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.source() is self:
            event.ignore()
            return
        text = event.mimeData().text()
        if text:
            self.key_pressed.emit(text)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def startDrag(self, supportedActions):
        pass

    # ── Context menu: only Copy + Select All ────

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_action = QAction("Copy", self)
        copy_action.setShortcut("Ctrl+Shift+C")
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)

        select_all_action = QAction("Select All", self)
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)

        menu.exec(event.globalPos())

    # ── Terminal cursor tracking ──────────────

    def _restore_term_cursor(self):
        if self._term_cursor_pos >= 0:
            doc_length = self.document().characterCount()
            if self._term_cursor_pos < doc_length:
                cursor = self.textCursor()
                cursor.setPosition(self._term_cursor_pos)
                self.setTextCursor(cursor)

    def _get_term_cursor(self) -> QTextCursor:
        cursor = self.textCursor()
        if self._term_cursor_pos >= 0:
            doc_length = self.document().characterCount()
            if self._term_cursor_pos < doc_length:
                cursor.setPosition(self._term_cursor_pos)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.End)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor

    # ── Output ───────────────────────────

    def append_output(self, text: str):
        """Append plain text (no ANSI parsing)."""
        self._pty_writing = True
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._term_cursor_pos = cursor.position()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self._pty_writing = False

    def append_ansi(self, text: str):
        """Append text with full ANSI color + cursor control support."""
        # Prepend any buffered incomplete escape sequence
        if self._pending_esc:
            text = self._pending_esc + text
            self._pending_esc = ""

        # Check if text ends with an incomplete escape sequence
        m = _INCOMPLETE_ESC_RE.search(text)
        if m:
            self._pending_esc = m.group(0)
            text = text[:m.start()]
            if not text:
                return  # entire chunk is an incomplete sequence, wait for more

        if self._debug:
            import sys
            has_ctrl = any(
                ord(c) < 32 or ord(c) == 127 or c == "\x1b" for c in text
            )
            if has_ctrl:
                sys.stderr.write(f"[ANSI-IN] {repr(text)}\n")
                sys.stderr.flush()

        self._pty_writing = True
        cursor = self._get_term_cursor()
        segments = parse_ansi_text(text)

        if self._debug:
            actions = [(t, a) for t, a in segments if a is not None]
            if actions:
                import sys
                sys.stderr.write(f"[SEGMENTS] {segments}\n")
                sys.stderr.flush()

        for segment_text, action in segments:

            # Plain text — overwrite mode
            if action is None:
                if segment_text:
                    fmt = self._ansi_state.to_format()
                    for ch in segment_text:
                        if ch == "\n":
                            cursor.movePosition(
                                QTextCursor.MoveOperation.EndOfBlock
                            )
                            cursor.insertText("\n")
                        else:
                            if not cursor.atBlockEnd():
                                cursor.deleteChar()
                            cursor.insertText(ch, fmt)

            # SGR color/style
            elif isinstance(action, list):
                self._ansi_state.apply_sgr(action)

            elif not isinstance(action, str):
                pass

            # Backspace
            elif action == "BS":
                if cursor.positionInBlock() > 0:
                    cursor.movePosition(QTextCursor.MoveOperation.Left)

            # Carriage return
            elif action == "CR":
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

            # Cursor back
            elif action.startswith("CUB"):
                n = int(action[3:])
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Left)

            # Cursor forward
            elif action.startswith("CUF"):
                n = int(action[3:])
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Right)

            # Cursor up
            elif action.startswith("CUU"):
                n = int(action[3:])
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Up)

            # Cursor down
            elif action.startswith("CUD"):
                n = int(action[3:])
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Down)

            # Cursor horizontal absolute (1-based)
            elif action.startswith("CHA"):
                col = int(action[3:]) - 1
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                for _ in range(col):
                    if not cursor.atBlockEnd():
                        cursor.movePosition(QTextCursor.MoveOperation.Right)

            # ICH — Insert Character
            elif action.startswith("ICH"):
                n = int(action[3:])
                pos = cursor.position()
                cursor.insertText(" " * n)
                cursor.setPosition(pos)

            # DCH — Delete Characters
            elif action.startswith("DCH"):
                n = int(action[3:])
                for _ in range(n):
                    if not cursor.atBlockEnd():
                        cursor.deleteChar()

            # Erase in Line
            elif action == "EL0":
                cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.removeSelectedText()

            elif action == "EL1":
                cursor.movePosition(
                    QTextCursor.MoveOperation.StartOfBlock,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.removeSelectedText()

            elif action == "EL2":
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.removeSelectedText()

            # Erase in Display
            elif action == "ED0":
                cursor.movePosition(
                    QTextCursor.MoveOperation.End,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.removeSelectedText()

            elif action == "ED2":
                self.clear()
                cursor = self.textCursor()

        # Save terminal cursor and restore widget
        self._term_cursor_pos = cursor.position()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self._pty_writing = False

    # ── Keyboard ────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        if not self._input_enabled:
            return

        key = event.key()
        modifiers = event.modifiers()

        # 🔎 Ctrl+Shift+F → open Find bar ONLY if there is a selection
        if (modifiers == (Qt.KeyboardModifier.ControlModifier |
                          Qt.KeyboardModifier.ShiftModifier)
                and key == Qt.Key.Key_F):
            if self.textCursor().selectedText():
                self._find_bar.open_bar()
                event.accept()
                return

        # Ignore bare modifier keys
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift,
                   Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            event.accept()
            return

        # --- Cisco break: Ctrl+Shift+6 → 0x1e ---
        if (modifiers == (Qt.KeyboardModifier.ControlModifier |
                          Qt.KeyboardModifier.ShiftModifier)
                and key == Qt.Key.Key_6):
            self.key_pressed.emit("\x1e")
            event.accept()
            return

        # --- Clipboard shortcuts (preserve selection) ---

        # Ctrl+Shift+C → copy selection
        if (modifiers == (Qt.KeyboardModifier.ControlModifier |
                          Qt.KeyboardModifier.ShiftModifier)
                and key == Qt.Key.Key_C):
            if self.textCursor().hasSelection():
                self.copy()
                event.accept()
                return

        # Ctrl+Shift+V → paste into PTY
        if (modifiers == (Qt.KeyboardModifier.ControlModifier |
                          Qt.KeyboardModifier.ShiftModifier)
                and key == Qt.Key.Key_V):
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            if text:
                self.key_pressed.emit(text)
            event.accept()
            return

        # --- Any other key clears selection and restores term cursor ---
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self.setTextCursor(cursor)

        self._restore_term_cursor()

        if modifiers == Qt.KeyboardModifier.ControlModifier:
            ctrl_map = {
                Qt.Key.Key_A: "\x01",  # Move to start of line
                Qt.Key.Key_B: "\x02",  # Backward one char
                Qt.Key.Key_C: "\x03",  # Interrupt / break
                Qt.Key.Key_D: "\x04",  # Delete char / logout
                Qt.Key.Key_E: "\x05",  # Move to end of line
                Qt.Key.Key_F: "\x06",  # Forward one char
                Qt.Key.Key_K: "\x0b",  # Kill to end of line
                Qt.Key.Key_L: "\x0c",  # Redisplay line / Clear screen
                Qt.Key.Key_N: "\x0e",  # Next command (history)
                Qt.Key.Key_P: "\x10",  # Previous command (history)
                Qt.Key.Key_R: "\x12",  # Redisplay line
                Qt.Key.Key_U: "\x15",  # Clear entire line
                Qt.Key.Key_W: "\x17",  # Delete word left
                Qt.Key.Key_Z: "\x1a",  # Exit to exec mode
                Qt.Key.Key_6: "\x1e",  # Cisco break
            }
            if key in ctrl_map:
                self.key_pressed.emit(ctrl_map[key])
                return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.key_pressed.emit("\r")
            return

        if key == Qt.Key.Key_Backspace:
            self.key_pressed.emit("\x7f")
            return

        if key == Qt.Key.Key_Delete:
            # "\x1b[3~" just for bash
            # "\x04" for Cisco / logout on bash
            # For both: \x06 + \x08 if cursor is not at end, prevents logout
            prompt, pos = self._get_current_line_and_col()
            if pos < len(prompt.rstrip()):
                self.key_pressed.emit("\x06\x08")
            return

        if key == Qt.Key.Key_Tab:
            self.key_pressed.emit("\t")
            return

        if key == Qt.Key.Key_Escape:
            self.key_pressed.emit("\x1b")
            return

        # ── Ctrl+Arrow: jump between words (Cisco/Junos compatible) ──
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Right:
                self._jump_word_right()
                event.accept()
                return
            elif key == Qt.Key.Key_Left:
                self._jump_word_left()
                event.accept()
                return

        arrow_map = {
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Left: "\x1b[D",
        }

        if key in arrow_map:
            self.key_pressed.emit(arrow_map[key])
            return

        if key == Qt.Key.Key_Home:
            # self.key_pressed.emit("\x1bOH")
            self.key_pressed.emit("\x01")
            return
        if key == Qt.Key.Key_End:
            # self.key_pressed.emit("\x1bOF")
            self.key_pressed.emit("\x05")
            return

        if key == Qt.Key.Key_PageUp:
            self.key_pressed.emit("\x1b[5~")
            return
        if key == Qt.Key.Key_PageDown:
            self.key_pressed.emit("\x1b[6~")
            return

        text = event.text()
        if text:
            self.key_pressed.emit(text)

    # ── Font management ─────────────────

    def apply_font(self, family: str = "", size: int = 12):
        """Apply a monospaced font. Empty family = system default mono."""
        if family:
            font = QFont(family, size)
        else:
            font = QFont()
            font.setFamily("")
            font.setPointSize(size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)

    # ── Utilities ───────────────────────

    def set_input_enabled(self, enabled: bool):
        self._input_enabled = enabled

    def clear_console(self):
        self._ansi_state.reset()
        self._pending_esc = ""
        self._term_cursor_pos = -1
        self.clear()

    # ── Word jump (Ctrl+Arrow) — sends multiple arrow keys ──

    def _get_current_line_and_col(self) -> tuple[str, int]:
        """Return (line_text, cursor_column) from the terminal cursor."""
        cursor = self._get_term_cursor()
        block = cursor.block()
        line = block.text()
        col = cursor.positionInBlock()
        return line, col

    def _jump_word_right(self):
        """Send arrow-right keys to jump to the next word boundary."""
        line, col = self._get_current_line_and_col()

        if col >= len(line):
            return

        pattern = re.compile(r'\w\W')
        match = pattern.search(line.replace('_', ' '), col)
        if match:
            i = match.start() + 1
        else:
            i = len(line)

        arrows = i - col
        if arrows > 0:
            self.key_pressed.emit("\x1b[C" * arrows)

    def _jump_word_left(self):
        """Send arrow-left keys to jump to the previous word boundary."""
        line, col = self._get_current_line_and_col()

        if col <= 0:
            return

        i = len(line)
        pattern = re.compile(r'\w\W')
        match = pattern.search(line[::-1].replace('_', ' '), i - col)
        if match:
            i -= match.start() + 1
        else:
            i = 0

        arrows = col - i
        if arrows > 0:
            self.key_pressed.emit("\x1b[D" * arrows)
