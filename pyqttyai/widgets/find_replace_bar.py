import re
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QTextCursor, QTextCharFormat, QColor,
    QShortcut, QKeySequence
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QToolButton, QLabel,
    QTextEdit, QSizePolicy
)


class FindReplaceBar(QWidget):
    closed = pyqtSignal()

    # Amber highlight (VS Code-like)
    HIGHLIGHT_COLOR = QColor(255, 165, 0, 90)
    CURRENT_COLOR   = QColor(255, 140, 0, 160)

    def __init__(self, editor, parent=None, with_replace=True):
        super().__init__(parent if parent is not None else editor)
        self.editor = editor
        self.with_replace = with_replace
        self._matches: list[tuple[int, int]] = []
        self._current_index = -1
        self._selection_start = -1
        self._selection_end = -1

        self.setObjectName("FindReplaceBar")
        self.setStyleSheet("""
            QWidget#FindReplaceBar {
                background-color: #2b2b2b;
                border-bottom: 1px solid #3c3c3c;
            }
            QLineEdit {
                background-color: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3c3c3c; border-radius: 2px;
                padding: 2px 4px;
            }
            QLineEdit:focus { border: 1px solid #007acc; }
            QToolButton {
                background: transparent; border: none;
                color: #cccccc; padding: 2px 6px; border-radius: 2px;
            }
            QToolButton:hover { background-color: #3c3c3c; }
            QToolButton:checked {
                background-color: #094771;
                border: 1px solid #007acc;
            }
            QLabel { color: #999999; padding: 0 4px; }
        """)

        self._build_ui()
        self._wire_shortcuts()
        self.hide()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # Find input
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setMinimumWidth(160)
        self.find_edit.textChanged.connect(self._refresh_matches)
        self.find_edit.returnPressed.connect(self.find_next)
        layout.addWidget(self.find_edit, 2)

        # Match counter
        self.match_label = QLabel("No results")
        self.match_label.setMinimumWidth(90)
        layout.addWidget(self.match_label)

        # Toggles
        self.btn_case   = self._make_toggle("Aa",   "Case Sensitive")
        self.btn_word   = self._make_toggle("\u27E6ab\u27E7", "Whole Word")
        self.btn_regex  = self._make_toggle(".*",   "Regex")
        self.btn_in_sel = self._make_toggle("\u2282", "Find in selection")
        for btn in (self.btn_case, self.btn_word, self.btn_regex, self.btn_in_sel):
            btn.toggled.connect(self._on_toggle_changed)
            layout.addWidget(btn)

        # Navigation
        self.btn_prev = self._make_button("\u25B2", "Previous (Shift+Enter)")
        self.btn_next = self._make_button("\u25BC", "Next (Enter)")
        self.btn_prev.clicked.connect(self.find_previous)
        self.btn_next.clicked.connect(self.find_next)
        layout.addWidget(self.btn_prev)
        layout.addWidget(self.btn_next)

        # Replace section
        if self.with_replace:
            sep = QWidget()
            sep.setFixedWidth(1)
            sep.setStyleSheet("background-color: #3c3c3c;")
            layout.addWidget(sep)

            self.replace_edit = QLineEdit()
            self.replace_edit.setPlaceholderText("Replace")
            self.replace_edit.setMinimumWidth(160)
            self.replace_edit.returnPressed.connect(self.replace_current)
            layout.addWidget(self.replace_edit, 2)

            self.btn_replace     = self._make_button("\u238C", "Replace")
            self.btn_replace_all = self._make_button("\u21C4", "Replace All")
            self.btn_replace.clicked.connect(self.replace_current)
            self.btn_replace_all.clicked.connect(self.replace_all)
            layout.addWidget(self.btn_replace)
            layout.addWidget(self.btn_replace_all)

        # Close
        self.btn_close = self._make_button("\u2715", "Close (Esc)")
        self.btn_close.clicked.connect(self.close_bar)
        layout.addWidget(self.btn_close)

    def _make_toggle(self, text, tip):
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setCheckable(True)
        return btn

    def _make_button(self, text, tip):
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tip)
        return btn

    # ---------- Shortcuts ----------
    def _wire_shortcuts(self):
        sc_esc = QShortcut(QKeySequence("Esc"), self)
        sc_esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_esc.activated.connect(self.close_bar)

        sc_prev = QShortcut(QKeySequence("Shift+Return"), self.find_edit)
        sc_prev.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc_prev.activated.connect(self.find_previous)

    # ---------- Public API ----------
    def open_bar(self, preset_text: str | None = None):
        # Capture selection BEFORE we steal focus
        cur = self.editor.textCursor()
        if cur.hasSelection():
            self._selection_start = cur.selectionStart()
            self._selection_end = cur.selectionEnd()
            if preset_text is None:
                preset_text = cur.selectedText().replace("\u2029", "\n")
        else:
            self._selection_start = -1
            self._selection_end = -1

        if preset_text:
            self.find_edit.setText(preset_text)

        self.show()
        self.parent().update()
        self.parent().parent().update()
        self.parent().parent().parent().update()
        self.parent().parent().parent().parent().update()
        #self._reposition()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self._refresh_matches()

    def close_bar(self):
        self._clear_highlights()
        self.hide()
        self.editor.setFocus()
        self.closed.emit()

    # ---------- Layout ----------
    def _reposition(self):
        p = self.parentWidget()
        if p is None:
            return
        rect = p.contentsRect()
        self.resize(rect.width() - 10, self.sizeHint().height())
        self.move(rect.x() + 5, rect.y())
        self.raise_()

    # ---------- Search logic ----------
    def _on_toggle_changed(self, _checked):
        self._refresh_matches()

    def _build_pattern(self):
        text = self.find_edit.text()
        if not text:
            return None
        flags = 0 if self.btn_case.isChecked() else re.IGNORECASE
        try:
            if self.btn_regex.isChecked():
                return re.compile(text, flags)
            pattern = re.escape(text)
            if self.btn_word.isChecked():
                pattern = rf"\b{pattern}\b"
            return re.compile(pattern, flags)
        except re.error:
            return None

    def _search_range(self):
        full = self.editor.toPlainText()
        if self.btn_in_sel.isChecked() and self._selection_start >= 0:
            return (
                self._selection_start,
                self._selection_end,
                full[self._selection_start:self._selection_end],
            )
        return (0, len(full), full)

    def _all_matches(self):
        pattern = self._build_pattern()
        if pattern is None:
            return []
        offset, _end, hay = self._search_range()
        return [(m.start() + offset, m.end() + offset)
                for m in pattern.finditer(hay)]

    def _refresh_matches(self):
        self._matches.clear()
        self._current_index = -1

        pattern = self._build_pattern()
        if pattern is None:
            self._clear_highlights()
            if self.find_edit.text() and self.btn_regex.isChecked():
                self.match_label.setText("Invalid Regex")
            else:
                self.match_label.setText("No results")
            return

        self._matches = self._all_matches()
        self._highlight_all()
        if self._matches:
            self._current_index = 0
            self._goto_match(0, select=True)
        self._update_counter()

    def _highlight_all(self):
        selections: list[QTextEdit.ExtraSelection] = []

        fmt_all = QTextCharFormat()
        fmt_all.setBackground(self.HIGHLIGHT_COLOR)

        fmt_cur = QTextCharFormat()
        fmt_cur.setBackground(self.CURRENT_COLOR)

        for i, (s, e) in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt_cur if i == self._current_index else fmt_all
            cur = QTextCursor(self.editor.document())
            cur.setPosition(s)
            cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cur
            selections.append(sel)

        self.editor.setExtraSelections(selections)

    def _clear_highlights(self):
        self.editor.setExtraSelections([])

    def _update_counter(self):
        n = len(self._matches)
        if n == 0:
            self.match_label.setText("No results")
        elif self._current_index >= 0:
            self.match_label.setText(f"{self._current_index + 1} of {n}")
        else:
            self.match_label.setText(f"{n} match{'es' if n != 1 else ''}")

    def _goto_match(self, index: int, select: bool = True):
        if index < 0 or index >= len(self._matches):
            return
        s, e = self._matches[index]
        cur = self.editor.textCursor()
        cur.setPosition(s)
        if select:
            cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cur)
        self.editor.ensureCursorVisible()
        self._current_index = index
        self._highlight_all()
        self._update_counter()

    # ---------- Navigation ----------
    def find_next(self):
        if not self._matches:
            return
        self._current_index = (self._current_index + 1) % len(self._matches)
        self._goto_match(self._current_index)

    def find_previous(self):
        if not self._matches:
            return
        self._current_index = (self._current_index - 1) % len(self._matches)
        self._goto_match(self._current_index)

    # ---------- Replace ----------
    def replace_current(self):
        if not self.with_replace or self.editor.isReadOnly() or not self._matches:
            return
        if self._current_index < 0:
            return
        s, e = self._matches[self._current_index]
        cur = self.editor.textCursor()
        cur.setPosition(s)
        cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(self.replace_edit.text())
        self._refresh_matches()

    def replace_all(self):
        if not self.with_replace or self.editor.isReadOnly() or not self._matches:
            return
        pattern = self._build_pattern()
        if pattern is None:
            return

        replacement = self.replace_edit.text()

        if self.btn_in_sel.isChecked() and self._selection_start >= 0:
            full = self.editor.toPlainText()
            head = full[:self._selection_start]
            mid  = full[self._selection_start:self._selection_end]
            tail = full[self._selection_end:]
            new_mid = pattern.sub(replacement, mid)
            new_text = head + new_mid + tail
            # adjust stored selection bounds
            self._selection_end = self._selection_start + len(new_mid)
        else:
            new_text = pattern.sub(replacement, self.editor.toPlainText())

        # preserve cursor pos roughly
        cur_pos = self.editor.textCursor().position()
        self.editor.setPlainText(new_text)
        c = self.editor.textCursor()
        c.setPosition(min(cur_pos, len(new_text)))
        self.editor.setTextCursor(c)

        self._refresh_matches()

    # ---------- Auto-reposition when parent resizes ----------
    def showEvent(self, ev):
        super().showEvent(ev)
        #self._reposition()
