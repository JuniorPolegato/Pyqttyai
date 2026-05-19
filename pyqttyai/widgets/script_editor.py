"""Script editor with line numbers and Cisco IOS syntax highlighting."""

import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPlainTextEdit, QHBoxLayout, QLabel,
    QApplication
)
from PyQt6.QtGui import (
    QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QPainter, QTextFormat,
    QKeySequence, QShortcut, QTextCursor,
)
from PyQt6.QtCore import Qt, QRect, QSize, QRegularExpression, pyqtSignal

from .find_replace_bar import FindReplaceBar


class CiscoHighlighter(QSyntaxHighlighter):
    """Basic syntax highlighting for Cisco IOS/IOS-XE commands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Keywords (config mode commands)
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#cba6f7"))  # Mauve
        kw_fmt.setFontWeight(QFont.Weight.Bold)
        keywords = [
            r'\b(interface|router|ip|no|shutdown|hostname|enable|configure|terminal|'
            r'exit|end|write|copy|show|ping|traceroute|access-list|route-map|'
            r'prefix-list|neighbor|network|redistribute|area|passive-interface|'
            r'switchport|vlan|spanning-tree|channel-group|port-channel|'
            r'crypto|tunnel|eigrp|ospf|bgp|rip|isis|mpls|vrf|address-family)\b',
        ]
        for pattern in keywords:
            self._rules.append((QRegularExpression(pattern), kw_fmt))

        # IP addresses
        ip_fmt = QTextCharFormat()
        ip_fmt.setForeground(QColor("#a6e3a1"))  # Green
        self._rules.append((
            QRegularExpression(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(/\d{1,2})?\b'),
            ip_fmt,
        ))

        # Numbers
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#fab387"))  # Peach
        self._rules.append((QRegularExpression(r'\b\d+\b'), num_fmt))

        # Comments (! in IOS)
        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor("#6c7086"))  # Overlay0
        comment_fmt.setFontItalic(True)
        self._rules.append((QRegularExpression(r'!.*$'), comment_fmt))

        # Strings
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#f9e2af"))  # Yellow
        self._rules.append((QRegularExpression(r'"[^"]*"'), str_fmt))

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class LineNumberArea(QWidget):
    """Gutter widget that displays line numbers."""

    def __init__(self, editor: "ScriptEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint(event)


class ScriptEditor(QPlainTextEdit):
    """Code editor with line numbers and Cisco syntax highlighting."""

    # 📢 Emitted when user presses Ctrl+Shift+A — request to apply voice
    #    rules to the current line. Carries the raw line text.
    apply_rules_requested = pyqtSignal(str)

    _LEFT_RE = re.compile(r'(^|.*?\W)([\s.,:;a-fA-F\d-]*)$', flags=re.U)
    _RIGHT_RE = re.compile(r'^([\s.,:;a-fA-F\d-]*(?=\W|$))(.*)', flags=re.U)

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont("JetBrains Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * 4
        )
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e2e; color: #cdd6f4; "
            "selection-background-color: #45475a; border: none; }"
        )
        self.setPlaceholderText(
            "! Enter Cisco IOS commands here...\n"
            "! Example:\n"
            "enable\n"
            "configure terminal\n"
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            "  ip address 10.0.0.1 255.255.255.0\n"
            "  no shutdown\n"
            "end\n"
            "write memory"
        )

        # Syntax highlighting
        self._highlighter = CiscoHighlighter(self.document())
        self._find_replace_bar: FindReplaceBar | None = None

        # Line numbers
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_width()

        # ⌨️ Ctrl+Shift+A → apply NLP rules to current line
        self._apply_rules_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+A"), self
        )
        self._apply_rules_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._apply_rules_shortcut.activated.connect(self._emit_apply_rules)

        # ⌨️ Shortcuts to apply IPv4/IPv6/MAC formatation
        sc = QShortcut(QKeySequence("Ctrl+;"), self,
                       lambda: self._normalize_separator(":"))
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc = QShortcut(QKeySequence("Ctrl+."), self,
                       lambda: self._normalize_separator("."))
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc = QShortcut(QKeySequence("Ctrl+-"), self,
                       lambda: self._normalize_separator("-"))
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc = QShortcut(QKeySequence("Ctrl+Shift+Space"), self,
                       lambda: self._normalize_separator(" "))
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)

        self._indent_unit: str = " "  # default: 1 space (Cisco style)
        self.setTabChangesFocus(False)

    def set_indent_size(self, n: int):
        """🔧 Set indentation to `n` spaces (1-8). Called from MainWindow."""
        n = max(1, min(8, int(n)))
        self._indent_unit = " " * n

    def indent_size(self) -> int:
        """📏 Current indent size in spaces."""
        return len(self._indent_unit)

    def set_find_replace_bar(self, find_replace_bar: FindReplaceBar):
        """ 🔎 Find & Replace bar """
        self._find_replace_bar = find_replace_bar

        # ⌨️ Ctrl+Shift+F → open Find & Replace / ESC → close
        self._find_replace_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+F"), self
        )
        self._find_replace_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._find_replace_shortcut.activated.connect(self._find_replace_bar.open_bar)

        self._find_replace_close_shortcut = QShortcut(
            QKeySequence("ESC"), self
        )
        self._find_replace_close_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._find_replace_close_shortcut.activated.connect(self._find_replace_bar.hide)

        # ⌨️ F3 → Next match (opens bar if hidden)
        self._f3_next_shortcut = QShortcut(QKeySequence("F3"), self)
        self._f3_next_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._f3_next_shortcut.activated.connect(self._on_f3_next)

        # ⌨️ Shift+F3 → Previous match (opens bar if hidden)
        self._f3_prev_shortcut = QShortcut(QKeySequence("Shift+F3"), self)
        self._f3_prev_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._f3_prev_shortcut.activated.connect(self._on_f3_prev)

    def _on_f3_next(self):
        if not self._find_replace_bar.isVisible():
            self._find_replace_bar.open_bar()
        self.setFocus()
        self._find_replace_bar.find_next()

    def _on_f3_prev(self):
        if not self._find_replace_bar.isVisible():
            self._find_replace_bar.open_bar()
        self.setFocus()
        self._find_replace_bar.find_previous()

    def line_number_area_width(self) -> int:
        digits = max(1, len(str(self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_width(self):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#181825"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#6c7086"))
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

        painter.end()

    def _emit_apply_rules(self):
        """🎯 Emit current line text so an external handler can apply NLP rules."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        line_text = cursor.selectedText()
        print('_' * 100)
        print(repr(line_text))
        print('‾' * 100)
        self.apply_rules_requested.emit(line_text)

    def replace_current_line(self, new_text: str):
        """♻️ Replace the line where the cursor currently sits with `new_text`.

        Preserves undo/redo (single edit block) and leaves the cursor at the
        end of the inserted text.
        """
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.insertText(new_text)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _get_hextets_at_cursor_position(self, line: str, position: int) -> tuple[int, int, str]:
        """ Return start, end, selection """
        left = line[:position]
        right = line[position:]
        left_groups = self._LEFT_RE.match(left)
        right_groups = self._RIGHT_RE.match(right)

        try:
            if position == 0:
                left_part = ''
                selection = right_groups.group(1)
                right_part = right_groups.group(2)
            elif position == len(line):
                left_part = left_groups.group(1)
                selection = left_groups.group(2)
                right_part = ''
            else:
                left_part = left_groups.group(1)
                selection = left_groups.group(2) + right_groups.group(1)
                right_part = right_groups.group(2)
        except Exception:
            return position, position, ''

        return len(left_part), len(line) - len(right_part), selection

    def _normalize_hextets(self, text: str, sep: str) -> str:
        result = re.sub(r'(\w)\s+(\w)', r'\1:\2', text)
        result = re.sub(r'[^\w\s:]', r':', result)
        if sep == '.':
            result = re.sub(r'\s|[^\d:]', r'', result)
        else:
            result = re.sub(r'\s|[^\da-fA-F:]', r'', result)
        if sep == ':':
            result = re.sub(r'::+', r'::', result)
        else:
            result = re.sub(r':+', sep, result)
        return result

    def _normalize_separator(self, sep: str):
        cursor = self.textCursor()

        # Selection mode: respect the user's range exactly.
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end   = cursor.selectionEnd()
            original = cursor.selectedText().replace("\u2029", "\n")
        else:
            block       = cursor.block()
            block_text  = block.text()
            block_start = block.position()
            col         = cursor.positionInBlock()
            seh = self._get_hextets_at_cursor_position(block_text, col)
            start, end, original = seh
            start += block_start
            end += block_start

        stripped = original.strip()
        if not stripped:
            return
        normalized = self._normalize_hextets(stripped, sep)
        if normalized == stripped:
            return
        lead  = original[:len(original) - len(original.lstrip())]
        trail = original[len(original.rstrip()):]
        self._replace_range(start, end, lead + normalized + trail,
                            cursor_at=None)  # start + len(lead) + len(normalized))

    def _replace_range(self, start: int, end: int, text: str, cursor_at: int | None = None):
        c = self.textCursor()
        c.beginEditBlock()
        c.setPosition(start)
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        c.insertText(text)
        c.endEditBlock()
        if cursor_at is not None:
            final = self.textCursor()
            final.setPosition(cursor_at)
            self.setTextCursor(final)
            self.ensureCursorVisible()

    def keyPressEvent(self, event):
        """⌨️ Ctrl+C/X without selection acts on the whole line (with trailing \\n)."""
        cursor = self.textCursor()

        if not cursor.hasSelection():
            if event.matches(QKeySequence.StandardKey.Copy):
                line_text = self._select_full_line(cursor) + "\n"
                QApplication.clipboard().setText(line_text)
                return

            if event.matches(QKeySequence.StandardKey.Cut):
                cursor.beginEditBlock()
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.Down,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                # If it was the last line (no \n after), select to end instead
                if not cursor.selectedText():
                    cursor.movePosition(
                        QTextCursor.MoveOperation.EndOfBlock,
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    line_text = cursor.selectedText().replace("\u2029", "\n") + "\n"
                else:
                    line_text = cursor.selectedText().replace("\u2029", "\n")
                QApplication.clipboard().setText(line_text)
                cursor.removeSelectedText()
                cursor.endEditBlock()
                return

        # Tab / Shift+Tab → indent / dedent
        if event.key() == Qt.Key.Key_Tab:
            self._indent_selection()
            return
        if event.key() == Qt.Key.Key_Backtab:  # Shift+Tab
            self._dedent_selection()
            return

        super().keyPressEvent(event)

    def _select_full_line(self, cursor: QTextCursor) -> str:
        """Return the text of the line where the cursor sits (no mutation)."""
        c = QTextCursor(cursor)
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        c.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        return c.selectedText().replace("\u2029", "\n")

    def _indent_selection(self):
        """➡️ Insert `indent` at the start of every line touched by the selection
        (or the current line if no selection). Preserves cursor/selection logically.
        """
        cursor = self.textCursor()
        doc = self.document()
        indent = self._indent_unit

        # Remember anchor and position to restore selection after edit
        had_selection = cursor.hasSelection()
        anchor = cursor.anchor()
        pos = cursor.position()

        # Determine block range
        sel_start = min(anchor, pos)
        sel_end = max(anchor, pos)
        start_block = doc.findBlock(sel_start)
        end_block = doc.findBlock(sel_end)

        # Edge case: if selection ends exactly at the start of a block,
        # don't include that block (matches VS Code behavior).
        if had_selection and sel_end == end_block.position() and end_block != start_block:
            end_block = end_block.previous()

        indent_len = len(indent)
        blocks_before_anchor = 0
        blocks_before_pos = 0

        cursor.beginEditBlock()
        block = start_block
        while block.isValid():
            edit = QTextCursor(block)
            edit.setPosition(block.position())
            edit.insertText(indent)

            # Count how many indents happen before anchor/pos (for offset shift)
            if block.position() <= anchor:
                blocks_before_anchor += 1
            if block.position() <= pos:
                blocks_before_pos += 1

            if block == end_block:
                break
            block = block.next()
        cursor.endEditBlock()

        # Restore selection/cursor shifted by the inserted chars
        new_anchor = anchor + blocks_before_anchor * indent_len
        new_pos = pos + blocks_before_pos * indent_len

        restored = self.textCursor()
        restored.setPosition(new_anchor)
        restored.setPosition(new_pos, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(restored)

    def _dedent_selection(self):
        """⬅️ Remove up to `len(indent)` leading whitespace chars from every line
        touched by the selection (or the current line). Preserves cursor logically.
        """
        cursor = self.textCursor()
        doc = self.document()
        indent = self._indent_unit

        had_selection = cursor.hasSelection()
        anchor = cursor.anchor()
        pos = cursor.position()

        sel_start = min(anchor, pos)
        sel_end = max(anchor, pos)
        start_block = doc.findBlock(sel_start)
        end_block = doc.findBlock(sel_end)

        if had_selection and sel_end == end_block.position() and end_block != start_block:
            end_block = end_block.previous()

        indent_len = len(indent)
        removed_before_anchor = 0
        removed_before_pos = 0

        cursor.beginEditBlock()
        block = start_block
        while block.isValid():
            text = block.text()
            # Count how many leading whitespace chars to remove (up to indent_len)
            to_remove = 0
            for i in range(min(indent_len, len(text))):
                if text[i] in (" ", "\t"):
                    to_remove += 1
                else:
                    break

            if to_remove > 0:
                edit = QTextCursor(block)
                edit.setPosition(block.position())
                edit.setPosition(block.position() + to_remove,
                                QTextCursor.MoveMode.KeepAnchor)
                edit.removeSelectedText()

                # Count removed chars that were before anchor/pos
                block_start = block.position()
                if anchor > block_start:
                    removed_before_anchor += min(to_remove, anchor - block_start)
                if pos > block_start:
                    removed_before_pos += min(to_remove, pos - block_start)

            if block == end_block:
                break
            block = block.next()
        cursor.endEditBlock()

        new_anchor = max(0, anchor - removed_before_anchor)
        new_pos = max(0, pos - removed_before_pos)

        restored = self.textCursor()
        restored.setPosition(new_anchor)
        restored.setPosition(new_pos, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(restored)
