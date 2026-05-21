"""📋 Voice transcription rewrite rules — visual editor."""

import copy
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QBrush, QColor, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QLineEdit, QPlainTextEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QWidget, QDialogButtonBox, QMessageBox,
    QGroupBox, QFormLayout, QCheckBox, QTextEdit, QPlainTextEdit,
    QTextBrowser, QSizePolicy
)

from pyqttyai.core.whisper_config import WhisperConfig
from pyqttyai.audio.transcription_service import TranscriptionService
from pyqttyai.core.rules_engine import Rule, RuleSet, _HANDLERS  # type: ignore
from pyqttyai.widgets.mic_vu_button import MicVuButton
from pyqttyai.widgets.api_key_dialog import ApiKeyDialog

# ═══════════════════════════════════════════════════════════════════
#  🧩 Editor Dialog
# ═══════════════════════════════════════════════════════════════════

class RulesEditorDialog(QDialog):
    """Edit the user's voice-transcription rewrite rules."""

    rules_saved = pyqtSignal(object)   # 📢 emits the saved RuleSet

    # 🎨 Soft palette (Catppuccin Mocha)
    _OK_BG      = "#1e3a2a"   # 🟢 dark green
    _OK_FG      = "#a6e3a1"
    _FAIL_BG    = "#3a1e25"   # 🔴 dark red
    _FAIL_FG    = "#f38ba8"
    _NEUTRAL_BG = "#11111b"
    _NEUTRAL_FG = "#cdd6f4"

    def __init__(
            self,
            ruleset:RuleSet,
            shared_service: TranscriptionService | None = None,
            config: WhisperConfig | None = None,
            parent=None,
        ):
        super().__init__(parent)

        self.setWindowTitle("📋 NLP Rules")
        self.setMinimumSize(1100, 700)

        # 🔑 Server and listen for API-key requests from any cloud backend
        self._service = shared_service
        self._config = config
        if self._service is not None:
            self._service.api_key_required.connect(self._on_api_key_required)
            # 🚫 Suppress main-window injection while this dialog is open
            self._service.setProperty("suppress_injection", True)

        # 🧬 Work on a deep copy — only commit on Save
        self._ruleset: RuleSet = RuleSet(rules=[
            self._clone_rule(r) for r in ruleset.rules
        ])
        # 📸 Baseline snapshot for dirty-checking
        self._baseline: RuleSet = RuleSet(rules=[
            self._clone_rule(r) for r in ruleset.rules
        ])

        self._current_index: int = -1
        self._loading: bool = False  # ⛔ prevent edit-handlers during refresh

        self._build_ui()
        self._apply_button_style()

        self._rule_list.installEventFilter(self)
        self._tests_table.installEventFilter(self)
        self._frag_table.installEventFilter(self)
        self._rep_table.installEventFilter(self)

        self._reload_rule_list()
        if self._ruleset.rules:
            self._rule_list.setCurrentRow(0)

    def _on_api_key_required(self, provider: str, env_var: str, message: str):
        """🔑 Cloud backend asked for credentials — prompt user."""

        dlg = ApiKeyDialog(provider, env_var, message, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # 🚀 Retry with the same config — env var is now set
        if self._service is not None:
            self._service.restart(self._config)

    # ═══════════════════════════════════════════════════════
    #  ⌨️  Enter → edit selected cell
    # ═══════════════════════════════════════════════════════

    def eventFilter(self, obj, event):
        """🎣 Catch Enter on our tables and turn it into 'edit current cell'."""

        if event.type() == QEvent.Type.KeyPress and isinstance(obj, QTableWidget):
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # 🛡️ If a cell editor is already open, let Enter commit it.
                #    QTableWidget exposes the active editor via state().
                if obj.state() == QAbstractItemView.State.EditingState:
                    return False  # 🚪 pass through to the editor

                # 🎯 Otherwise: open the editor on the current cell
                item = obj.currentItem()
                if item is not None and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    obj.editItem(item)
                    return True  # ✅ consumed — don't bubble up to the dialog

                return True  # 🤐 swallow even if no editable cell

        return super().eventFilter(obj, event)

    # ── Cloning helper ─────────────────────────────────────

    @staticmethod
    def _clone_rule(r: Rule) -> Rule:
        """🧬 Deep-copy a Rule (resetting compiled cache)."""
        return Rule(
            name=r.name,
            enabled=r.enabled,
            fragments=copy.deepcopy(r.fragments),
            pattern_template=r.pattern_template,
            pattern=r.pattern,
            flags=list(r.flags),
            handler=r.handler,
            handler_config=copy.deepcopy(r.handler_config),
            tests=copy.deepcopy(r.tests),
        )

    # ═══════════════════════════════════════════════════════
    #  UI construction
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ── Main horizontal splitter (left=list, right=editor) ──
        main_split = QSplitter(Qt.Orientation.Horizontal)

        main_split.addWidget(self._build_rule_list_pane())
        main_split.addWidget(self._build_editor_pane())

        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 4)
        main_split.setSizes([260, 800])
        outer.addWidget(main_split, stretch=1)

        # ── Test playground at the bottom ──
        outer.addWidget(self._build_test_pane())

        # ── Buttons ──
        outer.addLayout(self._build_buttons())

    # ── Left pane: rule list + add/remove/duplicate ───────
    # ── Left pane: test list + run all/add/remove ─────────

    def _build_rule_list_pane(self) -> QWidget:
        """Left pane: rule list (top) + tests grid (bottom)."""
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self._build_rule_list_section())
        split.addWidget(self._build_tests_section())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([280, 320])
        return split

    def _build_rule_list_section(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        header = QLabel("📋 Rules")
        header.setFont(QFont("Sans", 11, QFont.Weight.Bold))
        header.setStyleSheet("color: #89b4fa; padding: 4px;")
        v.addWidget(header)

        self._rule_list = QListWidget()
        self._rule_list.currentRowChanged.connect(self._on_rule_selected)
        self._rule_list.itemChanged.connect(self._on_rule_item_changed)
        v.addWidget(self._rule_list, stretch=1)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        for icon, tip, slot in [
            ("➕", "Add new rule",        self._on_add_rule),
            ("➖", "Delete selected",     self._on_delete_rule),
            ("⎘",  "Duplicate selected", self._on_duplicate_rule),
            ("↑", "Move up",             lambda: self._move_rule(-1)),
            ("↓", "Move down",           lambda: self._move_rule(+1)),
        ]:
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setMaximumWidth(36)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        return w

    def _build_tests_section(self) -> QWidget:
        box = QGroupBox("🧪 Tests for selected rule")
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 12, 6, 6)

        self._tests_table = QTableWidget(0, 4)
        self._tests_table.setHorizontalHeaderLabels(
            ["", "Input", "Expected", "Actual"]
        )
        h = self._tests_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._tests_table.verticalHeader().setVisible(False)
        self._tests_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._tests_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._tests_table.itemChanged.connect(self._on_tests_changed)
        self._tests_table.itemSelectionChanged.connect(
            self._on_test_row_selected
        )
        v.addWidget(self._tests_table, stretch=1)

        bar = QHBoxLayout()
        run = QPushButton("▶ Run All")
        run.setToolTip("Run every test for this rule and show a report")
        run.clicked.connect(self._on_run_all_tests)
        bar.addWidget(run)

        rem = QPushButton("➖")
        rem.setToolTip("Remove selected test")
        rem.setMaximumWidth(36)
        rem.clicked.connect(self._on_remove_test)
        bar.addWidget(rem)

        up = QPushButton("↑")
        up.setMaximumWidth(36)
        up.clicked.connect(lambda: self._move_test(-1))
        bar.addWidget(up)

        dn = QPushButton("↓")
        dn.setMaximumWidth(36)
        dn.clicked.connect(lambda: self._move_test(+1))
        bar.addWidget(dn)

        bar.addStretch()
        v.addLayout(bar)
        return box

    # ── Right pane: 3-section vertical splitter ───────────

    def _build_editor_pane(self) -> QWidget:
        v_split = QSplitter(Qt.Orientation.Vertical)

        v_split.addWidget(self._build_fragments_section())
        v_split.addWidget(self._build_pattern_section())
        v_split.addWidget(self._build_replacements_section())

        v_split.setStretchFactor(0, 3)
        v_split.setStretchFactor(1, 1)
        v_split.setStretchFactor(2, 3)
        v_split.setSizes([260, 130, 260])
        return v_split

    # ── 1. Fragments table ─────────────────────────────────

    def _build_fragments_section(self) -> QGroupBox:
        box = QGroupBox("🧩 Fragments")
        v = QVBoxLayout(box)

        self._frag_table = QTableWidget(0, 2)
        self._frag_table.setHorizontalHeaderLabels(["Name", "Pattern"])
        self._frag_table.horizontalHeader().setStretchLastSection(True)
        self._frag_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._frag_table.verticalHeader().setVisible(False)
        self._frag_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._frag_table.itemChanged.connect(self._on_fragments_changed)
        v.addWidget(self._frag_table)

        bar = QHBoxLayout()
        add = QPushButton("➕ Fragment")
        add.clicked.connect(self._on_add_fragment)
        bar.addWidget(add)

        rem = QPushButton("➖ Remove")
        rem.clicked.connect(self._on_remove_fragment)
        bar.addWidget(rem)

        bar.addStretch()
        v.addLayout(bar)
        return box

    # ── 2. Pattern + handler ───────────────────────────────

    def _build_pattern_section(self) -> QGroupBox:
        box = QGroupBox("🎯 Pattern && Handler")
        form = QFormLayout(box)

        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)
        form.addRow("Name:", self._name_edit)

        self._template_edit = QPlainTextEdit()
        self._template_edit.setFixedHeight(60)
        self._template_edit.setFont(QFont("Monospace", 10))
        self._template_edit.textChanged.connect(self._on_template_changed)
        form.addRow("Template:", self._template_edit)

        self._handler_combo = QComboBox()
        self._handler_combo.addItems(sorted(_HANDLERS.keys()))
        self._handler_combo.currentTextChanged.connect(self._on_handler_changed)
        form.addRow("Handler:", self._handler_combo)

        self._post_combo = QComboBox()
        self._post_combo.addItems(["", "upper", "lower", "title"])
        self._post_combo.currentTextChanged.connect(self._on_post_changed)
        form.addRow("Post-process:", self._post_combo)

        return box

    # ── 3. Replacements table ──────────────────────────────

    def _build_replacements_section(self) -> QGroupBox:
        box = QGroupBox("🔧 Replacements")
        v = QVBoxLayout(box)

        self._rep_table = QTableWidget(0, 3)
        self._rep_table.setHorizontalHeaderLabels(
            ["Kind", "Fragment / Pattern", "With"]
        )
        self._rep_table.horizontalHeader().setStretchLastSection(True)
        self._rep_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._rep_table.verticalHeader().setVisible(False)
        self._rep_table.itemChanged.connect(self._on_replacements_changed)
        v.addWidget(self._rep_table)

        bar = QHBoxLayout()
        add = QPushButton("➕ Replacement")
        add.clicked.connect(self._on_add_replacement)
        bar.addWidget(add)

        rem = QPushButton("➖ Remove")
        rem.clicked.connect(self._on_remove_replacement)
        bar.addWidget(rem)

        up = QPushButton("↑")
        up.clicked.connect(lambda: self._move_replacement(-1))
        bar.addWidget(up)

        dn = QPushButton("↓")
        dn.clicked.connect(lambda: self._move_replacement(+1))
        bar.addWidget(dn)

        bar.addStretch()
        v.addLayout(bar)
        return box

    # ── Test pane (bottom) ─────────────────────────────────

    def _build_test_pane(self) -> QWidget:
        box = QGroupBox("🧪 Quick Test")
        h = QHBoxLayout(box)
        v = QVBoxLayout(box)
        h.addLayout(v)

        self._add_test_btn = QPushButton("⬆ Upload")
        self._add_test_btn.setToolTip("Promote this case to the tests grid")
        self._add_test_btn.clicked.connect(self._on_promote_to_tests)
        v.addWidget(self._add_test_btn)

        self._test_all_rules_btn = QPushButton("▶ Run Rules")
        self._test_all_rules_btn.setToolTip("Run every enabled rule over this test text")
        self._test_all_rules_btn.clicked.connect(self._on_run_all_rules)
        v.addWidget(self._test_all_rules_btn)

        self._test_input = QPlainTextEdit()
        self._test_input.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # 🚫 no soft-wrap
        self._test_input.setTabChangesFocus(True)  # ⌨️ Tab moves focus, doesn't insert tab
        self._test_input.setFixedHeight(100)
        self._test_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._test_input.setPlaceholderText("Type a phrase to test…")
        self._test_input.textChanged.connect(self._update_test_output)
        run_sc = QShortcut(QKeySequence("Ctrl+Return"), self._test_input)
        run_sc.activated.connect(self._update_test_output)
        h.addWidget(self._test_input, stretch=2)

        mic = MicVuButton(
            self._service,
            position=MicVuButton.Position.BOTTOM,
            shape=MicVuButton.Shape.THIN_VERTICAL,
        )
        mic.text_ready.connect(self._test_input.insertPlainText)
        h.addWidget(mic)

        h.addWidget(QLabel("→"))

        self._test_output = QPlainTextEdit()
        self._test_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # 🚫 no soft-wrap
        self._test_output.setTabChangesFocus(True)  # ⌨️ Tab moves focus, doesn't insert tab
        self._test_output.setFixedHeight(100)
        self._test_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._test_output.setReadOnly(True)
        self._test_output.setPlaceholderText("(actual result)")
        h.addWidget(self._test_output, stretch=2)

        h.addWidget(QLabel("="))

        self._test_expected = QPlainTextEdit()
        self._test_expected.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # 🚫 no soft-wrap
        self._test_expected.setTabChangesFocus(True)  # ⌨️ Tab moves focus, doesn't insert tab
        self._test_expected.setFixedHeight(100)
        self._test_expected.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._test_expected.setPlaceholderText("(expected result)")
        self._test_expected.textChanged.connect(self._update_test_output)
        h.addWidget(self._test_expected, stretch=2)

        return box

    # ═══════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════

    def _current_rule(self) -> Optional[Rule]:
        if 0 <= self._current_index < len(self._ruleset.rules):
            return self._ruleset.rules[self._current_index]
        return None

    def _invalidate_compiled(self):
        """🧹 Drop compiled regex so changes take effect on next apply()."""
        r = self._current_rule()
        if r is not None:
            r._compiled = None

    # ═══════════════════════════════════════════════════════
    #  Rule list
    # ═══════════════════════════════════════════════════════

    def _reload_rule_list(self):
        self._loading = True
        self._rule_list.clear()
        for r in self._ruleset.rules:
            item = QListWidgetItem(r.name or "(unnamed)")
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            item.setCheckState(
                Qt.CheckState.Checked if r.enabled else Qt.CheckState.Unchecked
            )
            self._rule_list.addItem(item)
        self._loading = False

    def _on_rule_selected(self, row: int):
        self._current_index = row
        self._load_current_into_editor()

    def _on_rule_item_changed(self, item: QListWidgetItem):
        if self._loading:
            return
        row = self._rule_list.row(item)
        if 0 <= row < len(self._ruleset.rules):
            r = self._ruleset.rules[row]
            r.enabled = item.checkState() == Qt.CheckState.Checked
            new_name = item.text().strip()
            if new_name and new_name != r.name:
                r.name = new_name
                if row == self._current_index:
                    self._loading = True
                    self._name_edit.setText(new_name)
                    self._loading = False
        self._refresh_test_results()

    def _on_add_rule(self):
        r = Rule(name="New Rule", pattern_template="", handler="compose_replace")
        self._ruleset.rules.append(r)
        self._reload_rule_list()
        self._rule_list.setCurrentRow(len(self._ruleset.rules) - 1)

    def _on_delete_rule(self):
        if self._current_index < 0:
            return
        if QMessageBox.question(
            self, "Delete Rule",
            f"Delete rule '{self._current_rule().name}'?"
        ) != QMessageBox.StandardButton.Yes:
            return
        del self._ruleset.rules[self._current_index]
        self._reload_rule_list()
        if self._ruleset.rules:
            self._rule_list.setCurrentRow(
                min(self._current_index, len(self._ruleset.rules) - 1)
            )
        else:
            self._current_index = -1
            self._clear_editor()

    def _on_duplicate_rule(self):
        r = self._current_rule()
        if r is None:
            return
        clone = self._clone_rule(r)
        clone.name = f"{r.name} (copy)"
        self._ruleset.rules.insert(self._current_index + 1, clone)
        self._reload_rule_list()
        self._rule_list.setCurrentRow(self._current_index + 1)

    def _move_rule(self, direction: int):
        i = self._current_index
        j = i + direction
        if i < 0 or not (0 <= j < len(self._ruleset.rules)):
            return
        rules = self._ruleset.rules
        rules[i], rules[j] = rules[j], rules[i]
        self._reload_rule_list()
        self._rule_list.setCurrentRow(j)

    # ═══════════════════════════════════════════════════════
    #  Tests
    # ═══════════════════════════════════════════════════════

    def _qline_style(self, bg: str, fg: str) -> str:
        """Full QLineEdit style — overrides global rules cleanly."""
        return (
            #f"QLineEdit {{"
            f"  background-color: {bg};"
            f"  color: {fg};"
            #f"  border: 1px solid #45475a;"
            #f"  border-radius: 4px;"
            #f"  padding: 4px;"
            #f"}}"
        )

    def _update_test_output(self, *_):
        r = self._current_rule()
        text = self._test_input.toPlainText()
        expected = self._test_expected.toPlainText()

        neutral = (
            f"background-color: {self._NEUTRAL_BG};"
            f"color: {self._NEUTRAL_FG};"
        )
        fail = (
            f"background-color: {self._FAIL_BG};"
            f"color: {self._FAIL_FG};"
        )
        ok_style = (
            f"background-color: {self._OK_BG};"
            f"color: {self._OK_FG};"
        )
        if r is None or not text:
            self._test_output.clear()
            self._test_output.setStyleSheet(neutral)
            self._test_expected.setStyleSheet(neutral)
            return

        try:
            actual = r.apply(text)
            self._test_output.setPlainText(actual)
            self._test_output.setStyleSheet(neutral)
        except Exception as e:
            self._test_output.setPlainText(f"⚠ {e}")
            self._test_output.setStyleSheet(fail)
            self._test_expected.setStyleSheet(neutral)
            return

        # 🎯 Match check
        if not expected:
            self._test_expected.setStyleSheet(neutral)
        elif actual == expected:
            ok_style = self._qline_style(self._OK_BG, self._OK_FG)
            self._test_output.setStyleSheet(ok_style)
            self._test_expected.setStyleSheet(ok_style)
        else:
            self._test_output.setStyleSheet(neutral)
            self._test_expected.setStyleSheet(fail)

    def _on_run_all_tests(self):
        """▶ Run every test of the current rule, show summary window."""
        r = self._current_rule()
        if r is None:
            return
        self._refresh_test_results()  # also sync grid colors

        results = r.run_tests()
        passed = sum(1 for ok, *_ in results if ok)
        total = len(results)

        lines = [f"# 🧪 Test report — {r.name}",
                f"**{passed}/{total} passed**", ""]
        for ok, inp, exp, act in results:
            icon = "✅" if ok else "❌"
            lines.append(f"### {icon} `{inp}`")
            if not ok:
                lines.append(f"- expected: `{exp}`")
                lines.append(f"- actual:&nbsp;&nbsp; `{act}`")
            else:
                lines.append(f"- result:&nbsp;&nbsp;&nbsp; `{act}`")
            lines.append("")

        dlg = QDialog(self)
        dlg.setWindowTitle(f"🧪 Test Report — {r.name}")
        dlg.resize(720, 520)
        v = QVBoxLayout(dlg)

        summary = QLabel(
            f"<b style='color:{'#a6e3a1' if passed == total else '#f38ba8'};'>"
            f"{passed}/{total} passed</b>"
        )
        summary.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        v.addWidget(summary)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setMarkdown("\n".join(lines))
        view.setFont(QFont("Monospace", 10))
        v.addWidget(view, stretch=1)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(dlg.reject)
        btn.accepted.connect(dlg.accept)
        v.addWidget(btn)
        dlg.exec()

    # ── Load tests for current rule ────────────────────────

    def _reload_tests_table(self):
        self._loading = True
        self._tests_table.setRowCount(0)
        r = self._current_rule()
        if r is None:
            self._loading = False
            return
        for t in r.tests:
            self._append_test_row(
                t.get("input", ""),
                t.get("expected", ""),
            )
        self._loading = False
        self._refresh_test_results()

    def _append_test_row(self, inp: str, exp: str):
        row = self._tests_table.rowCount()
        self._tests_table.insertRow(row)
        status = QTableWidgetItem("")
        status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
        status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tests_table.setItem(row, 0, status)
        self._tests_table.setItem(row, 1, QTableWidgetItem(inp))
        self._tests_table.setItem(row, 2, QTableWidgetItem(exp))
        actual = QTableWidgetItem("")
        actual.setFlags(actual.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._tests_table.setItem(row, 3, actual)

    def _refresh_test_results(self):
        """🚦 Recompute pass/fail for every row & color it."""
        r = self._current_rule()
        if r is None:
            return
        ok_brush   = QBrush(QColor(self._OK_BG))
        fail_brush = QBrush(QColor(self._FAIL_BG))
        ok_fg      = QBrush(QColor(self._OK_FG))
        fail_fg    = QBrush(QColor(self._FAIL_FG))

        for row in range(self._tests_table.rowCount()):
            # 🛡️ Ensure all 4 columns have items (defensive)
            for col in range(4):
                if self._tests_table.item(row, col) is None:
                    item = QTableWidgetItem("")
                    if col in (0, 3):  # status + actual are read-only
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 0:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._tests_table.setItem(row, col, item)

            inp = self._tests_table.item(row, 1).text()
            exp = self._tests_table.item(row, 2).text()
            try:
                actual = r.apply(inp)
            except Exception as e:
                actual = f"⚠ {e}"
            ok = (actual == exp)

            self._tests_table.item(row, 0).setText("✅" if ok else "❌")
            self._tests_table.item(row, 3).setText(actual)

            bg = ok_brush if ok else fail_brush
            fg = ok_fg    if ok else fail_fg
            for col in range(4):
                cell = self._tests_table.item(row, col)
                cell.setBackground(bg)
                cell.setForeground(fg)


    # ── Edits / selection ─────────────────────────────────

    def _on_tests_changed(self, *_):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        new_tests = []
        for row in range(self._tests_table.rowCount()):
            inp = self._tests_table.item(row, 1)
            exp = self._tests_table.item(row, 2)
            new_tests.append({
                "input":    inp.text() if inp else "",
                "expected": exp.text() if exp else "",
            })
        r.tests = new_tests
        self._refresh_test_results()

    def _on_test_row_selected(self):
        """🖱️ Click a test row → populate quick test playground."""
        row = self._tests_table.currentRow()
        if row < 0:
            return
        inp = self._tests_table.item(row, 1)
        exp = self._tests_table.item(row, 2)
        self._loading = True   # avoid retriggering anything weird
        self._test_input.setPlainText(inp.text() if inp else "")
        self._test_expected.setPlainText(exp.text() if exp else "")
        self._loading = False
        self._update_test_output()

    # ── Promote, remove, reorder ──────────────────────────

    def _on_promote_to_tests(self):
        """⬆ Add the current playground case to the tests grid."""
        r = self._current_rule()
        if r is None:
            return
        inp = self._test_input.toPlainText()
        exp = self._test_expected.toPlainText()
        if not inp:
            return
        self._append_test_row(inp, exp)
        self._on_tests_changed()
        # 👁 Scroll to & select the new row
        last = self._tests_table.rowCount() - 1
        self._tests_table.selectRow(last)
        self._tests_table.scrollToItem(self._tests_table.item(last, 1))

    def _on_remove_test(self):
        row = self._tests_table.currentRow()
        if row < 0:
            return
        self._tests_table.removeRow(row)
        self._on_tests_changed()

    def _move_test(self, direction: int):
        row = self._tests_table.currentRow()
        target = row + direction
        if row < 0 or not (0 <= target < self._tests_table.rowCount()):
            return
        a_in  = self._tests_table.item(row, 1).text()
        a_exp = self._tests_table.item(row, 2).text()
        b_in  = self._tests_table.item(target, 1).text()
        b_exp = self._tests_table.item(target, 2).text()
        self._loading = True
        self._tests_table.item(row, 1).setText(b_in)
        self._tests_table.item(row, 2).setText(b_exp)
        self._tests_table.item(target, 1).setText(a_in)
        self._tests_table.item(target, 2).setText(a_exp)
        self._loading = False
        self._tests_table.selectRow(target)
        self._on_tests_changed()

    def _on_run_all_rules(self):
        try:
            normalized = self._ruleset.apply(self._test_input.toPlainText())
        except (ValueError, KeyError, AttributeError, re.error) as e:
            # 🛟 Rule failure is not fatal — fall back to raw text,
            #    but tell the user something went wrong.
            normalized = f"⚠ Rule error: {e}"
        finally:
            self._test_output.setPlainText(normalized)

    # ═══════════════════════════════════════════════════════
    #  Editor load/clear
    # ═══════════════════════════════════════════════════════

    def _clear_editor(self):
        self._loading = True
        self._name_edit.clear()
        self._template_edit.clear()
        self._tests_table.setRowCount(0)
        self._frag_table.setRowCount(0)
        self._rep_table.setRowCount(0)
        self._post_combo.setCurrentIndex(0)
        self._loading = False

    def _load_current_into_editor(self):
        r = self._current_rule()
        if r is None:
            self._clear_editor()
            return

        self._loading = True

        self._name_edit.setText(r.name)
        self._template_edit.setPlainText(r.pattern_template or r.pattern)

        # handler
        idx = self._handler_combo.findText(r.handler)
        self._handler_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # post-process
        post = (r.handler_config.get("post_process") or "")
        idx = self._post_combo.findText(post)
        self._post_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # fragments
        self._frag_table.setRowCount(0)
        for name, pat in r.fragments.items():
            self._append_fragment_row(name, pat)

        # replacements
        self._rep_table.setRowCount(0)
        for rep in r.handler_config.get("replacements", []):
            kind = "fragment" if "fragment" in rep else "pattern"
            key = rep.get(kind, "")
            self._append_replacement_row(kind, key, rep.get("with", ""))

        self._loading = False
        self._update_test_output()
        self._reload_tests_table()

    # ═══════════════════════════════════════════════════════
    #  Fragments
    # ═══════════════════════════════════════════════════════

    def _append_fragment_row(self, name: str, pattern: str):
        row = self._frag_table.rowCount()
        self._frag_table.insertRow(row)
        self._frag_table.setItem(row, 0, QTableWidgetItem(name))
        self._frag_table.setItem(row, 1, QTableWidgetItem(pattern))

    def _on_add_fragment(self):
        if self._current_rule() is None:
            return
        self._append_fragment_row("new_fragment", "")
        self._on_fragments_changed()

    def _on_remove_fragment(self):
        row = self._frag_table.currentRow()
        if row < 0:
            return
        self._frag_table.removeRow(row)
        self._on_fragments_changed()

    def _on_fragments_changed(self, *_):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        new_fragments: dict[str, str] = {}
        for row in range(self._frag_table.rowCount()):
            n = self._frag_table.item(row, 0)
            p = self._frag_table.item(row, 1)
            name = (n.text() if n else "").strip()
            if not name:
                continue
            new_fragments[name] = p.text() if p else ""
        r.fragments = new_fragments
        self._invalidate_compiled()
        self._update_test_output()
        self._refresh_test_results()

    # ═══════════════════════════════════════════════════════
    #  Pattern / handler / post-process
    # ═══════════════════════════════════════════════════════

    def _on_name_changed(self):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        new_name = self._name_edit.text().strip()
        if not new_name:
            return
        r.name = new_name
        item = self._rule_list.item(self._current_index)
        if item is not None:
            self._loading = True
            item.setText(new_name)
            self._loading = False

    def _on_template_changed(self):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        r.pattern_template = self._template_edit.toPlainText()
        r.pattern = ""
        self._invalidate_compiled()
        try:
            r.compile()
            self._template_edit.setStyleSheet("")
            self._template_edit.setToolTip("")
        except Exception as e:
            self._template_edit.setStyleSheet(
                "border: 2px solid #f38ba8;"
            )
            self._template_edit.setToolTip(f"⚠ Invalid regex:\n{e}")
        self._update_test_output()
        self._refresh_test_results()

    def _on_handler_changed(self, name: str):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        r.handler = name
        self._update_test_output()
        self._refresh_test_results()

    def _on_post_changed(self, value: str):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        if value:
            r.handler_config["post_process"] = value
        else:
            r.handler_config.pop("post_process", None)
        self._update_test_output()
        self._refresh_test_results()

    # ═══════════════════════════════════════════════════════
    #  Replacements
    # ═══════════════════════════════════════════════════════

    def _append_replacement_row(self, kind: str, key: str, with_: str):
        row = self._rep_table.rowCount()
        self._rep_table.insertRow(row)

        # Kind: editable combo? for simplicity, use a QComboBox cell widget
        combo = QComboBox()
        combo.addItems(["fragment", "pattern", "none"])
        combo.setCurrentText(kind)
        combo.currentTextChanged.connect(
            lambda *_: self._on_replacements_changed()
        )
        self._rep_table.setCellWidget(row, 0, combo)

        self._rep_table.setItem(row, 1, QTableWidgetItem(key))
        self._rep_table.setItem(row, 2, QTableWidgetItem(with_))

    def _on_add_replacement(self):
        if self._current_rule() is None:
            return
        self._append_replacement_row("fragment", "", "")
        self._on_replacements_changed()

    def _on_remove_replacement(self):
        row = self._rep_table.currentRow()
        if row < 0:
            return
        self._rep_table.removeRow(row)
        self._on_replacements_changed()

    def _move_replacement(self, direction: int):
        row = self._rep_table.currentRow()
        target = row + direction
        if row < 0 or not (0 <= target < self._rep_table.rowCount()):
            return
        # 🔄 swap by reading + rewriting (cell widgets can't be moved directly)
        a = self._read_replacement_row(row)
        b = self._read_replacement_row(target)
        self._write_replacement_row(row, *b)
        self._write_replacement_row(target, *a)
        self._rep_table.setCurrentCell(target, 0)
        self._on_replacements_changed()

    def _read_replacement_row(self, row: int) -> tuple[str, str, str]:
        combo = self._rep_table.cellWidget(row, 0)
        kind = combo.currentText() if combo else "fragment"
        key = self._rep_table.item(row, 1)
        wit = self._rep_table.item(row, 2)
        return (kind, key.text() if key else "", wit.text() if wit else "")

    def _write_replacement_row(self, row: int, kind: str, key: str, wit: str):
        combo = self._rep_table.cellWidget(row, 0)
        if combo:
            combo.setCurrentText(kind)
        self._rep_table.setItem(row, 1, QTableWidgetItem(key))
        self._rep_table.setItem(row, 2, QTableWidgetItem(wit))

    def _on_replacements_changed(self, *_):
        if self._loading:
            return
        r = self._current_rule()
        if r is None:
            return
        reps = []
        for row in range(self._rep_table.rowCount()):
            kind, key, wit = self._read_replacement_row(row)
            if not key.strip():
                continue
            reps.append({kind: key, "with": wit})
        r.handler_config["replacements"] = reps
        self._update_test_output()
        self._refresh_test_results()

    # ═══════════════════════════════════════════════════════
    #  💾 Save / Close (Whisper-style UX)
    # ═══════════════════════════════════════════════════════

    def _build_buttons(self) -> QHBoxLayout:
        """🔘 Help (left) + Save / Close (right)."""
        row = QHBoxLayout()

        # ❓ Help button — bottom-left
        self._help_btn = QPushButton("❓ Help")
        self._help_btn.setObjectName("helpBtn")
        self._help_btn.setAutoDefault(False)
        self._help_btn.setDefault(False)
        self._help_btn.setToolTip("Show usage instructions (F1)")
        self._help_btn.clicked.connect(self._show_help)
        row.addWidget(self._help_btn)

        row.addStretch(1)  # 🪄 push the rest to the right

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close
        )
        save_btn = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setObjectName("saveBtn")
        save_btn.setAutoDefault(False)
        save_btn.setDefault(False)

        close_btn = self._buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)

        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self._on_close)
        row.addWidget(self._buttons)
        return row

    def _apply_button_style(self):
        """🎨 Highlight the Save button in green (Catppuccin Mocha)."""
        self.setStyleSheet(self.styleSheet() + """
            QPushButton#saveBtn {
                background-color: #a6e3a1;
                color: #1e1e2e;
                border: none;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton#saveBtn:hover {
                background-color: #94e2d5;
            }
        """)

    def _snapshot(self, rs: RuleSet) -> list[dict]:
        """🧮 Stable comparable representation for dirty-checking."""
        return [
            {
                "name":             r.name,
                "enabled":          r.enabled,
                "fragments":        dict(r.fragments),
                "pattern_template": r.pattern_template,
                "pattern":          r.pattern,
                "flags":            list(r.flags),
                "handler":          r.handler,
                "handler_config":   copy.deepcopy(r.handler_config),
                "tests":            copy.deepcopy(r.tests),
            }
            for r in rs.rules
        ]

    def _is_dirty(self) -> bool:
        """🔍 Has the user changed anything since open / last save?"""
        return self._snapshot(self._ruleset) != self._snapshot(self._baseline)

    def _on_save(self):
        """💾 Validate, persist, stay open (Whisper-style)."""
        self.setFocus()  # 🪄 flush any in-progress cell edit

        errors = self._ruleset.validate()
        if errors:
            QMessageBox.critical(
                self,
                "Save",
                "❌ Configuration wasn't saved.\n\n"
                "⚠ Invalid rules:\n" + "\n".join(f"• {e}" for e in errors),
            )
            return

        if not self._ruleset.save():
            QMessageBox.critical(
                self, "Save", "❌ Configuration wasn't saved."
            )
            return

        # 📸 Refresh baseline so dirty-check resets
        self._baseline = RuleSet(rules=[
            self._clone_rule(r) for r in self._ruleset.rules
        ])
        self.rules_saved.emit(self._ruleset)
        QMessageBox.information(
            self, "Save", "💾 Rules saved successfully!"
        )
        # 🚪 Stay open — user may want to keep editing

    def _confirm_discard_or_save(self) -> bool:
        """🤔 If dirty, ask Yes/No/Cancel. Returns True if it's OK to close."""
        if not self._is_dirty():
            return True

        resp = QMessageBox.question(
            self,
            "Save",
            "Do you want to save the current rules?",
            buttons=(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel
            ),
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._on_save()
            # If save failed, we're still dirty → block close
            return not self._is_dirty()
        return resp == QMessageBox.StandardButton.No  # No = discard, Cancel = stay

    def _on_close(self):
        """🚪 Close button → ask if dirty, then reject."""
        if self._confirm_discard_or_save():
            self.close()

    def keyPressEvent(self, event):
        """⌨️ Escape → use our Close logic, not plain reject()."""
        if event.key() == Qt.Key.Key_Escape:
            self._on_close()
            return
        if event.key() == Qt.Key.Key_F1:
            self._show_help()
            return
        super().keyPressEvent(event)

    def reject(self):
        """Ensure cleanup runs even if reject() is called directly."""
        self._cleanup_resources()
        super().reject()

    def accept(self):
        """Ensure cleanup runs even if accept() is called directly."""
        self._cleanup_resources()
        super().accept()

    def closeEvent(self, event):
        """Ensure cleanup runs even if close() is called directly."""
        """🪟 Window 'X' → same flow."""
        if self._confirm_discard_or_save():
            self._cleanup_resources()
            super().closeEvent(event)
        else:
            event.ignore()

    def _cleanup_resources(self):
        # 🔓 Re-enable main-window injection
        if getattr(self, "_service", None) is not None:
            try:
                self._service.setProperty("suppress_injection", False)
            except Exception:
                pass

        """🧹 Idempotent cleanup — safe to call multiple times."""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True

        # 🔌 Drop our borrowed reference — service lives on for main.py
        if getattr(self, "_service", None) is not None:
            try:
                self._service.api_key_required.disconnect(self._on_api_key_required)
            except (TypeError, RuntimeError):
                pass
            self._service = None

    # ═══════════════════════════════════════════════════════
    #  📖  Help dialog
    # ═══════════════════════════════════════════════════════

    def _show_help(self) -> None:
        """❓ Show a friendly help dialog explaining the editor."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Rules Editor — Help")
        dlg.resize(720, 600)

        layout = QVBoxLayout(dlg)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(self._help_html())
        layout.addWidget(browser)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton("Close")
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.exec()

    @staticmethod
    def _help_html() -> str:
        """📚 Help content in HTML (rendered by QTextBrowser)."""
        return """
        <style>
        body { font-family: sans-serif; line-height: 1.5; }
        h2   { color: #4ea1ff; margin-top: 18px; }
        h3   { color: #9bd0ff; margin-top: 14px; }
        code { background: #2a2a2a; padding: 1px 5px; border-radius: 3px;
                color: #ffd479; }
        table { border-collapse: collapse; margin: 8px 0; }
        th, td { border: 1px solid #555; padding: 4px 10px; text-align: left; }
        th  { background: #333; }
        .tip { background: #1f3a1f; padding: 8px 12px; border-left: 3px solid #6c6;
                margin: 10px 0; }
        </style>

        <h1>📚 Rules Editor — Quick Guide</h1>

        <p>This editor lets you build <b>text-rewriting rules</b> made of
        fragments (regex patterns) and replacements, then test them live
        against sample input.</p>

        <h2>🗂️ Layout</h2>
        <ul>
        <li><b>Left panel — Rules list:</b> all rules in the current ruleset.
            Use the toolbar to add, duplicate, rename, delete, or reorder.</li>
        <li><b>Right panel — Rule editor:</b> shows the selected rule's
            fragments, replacements, and tests.</li>
        </ul>

        <h2>🧩 Fragments grid</h2>
        <p>Each row is a <b>regex pattern</b> that must match the input for the
        rule to fire. All fragments are combined (AND).</p>
        <table>
        <tr><th>Column</th><th>Meaning</th></tr>
        <tr><td><b>Pattern</b></td><td>Python regex (e.g. <code>name\\s+(\\S+)</code>)</td></tr>
        <tr><td><b>Flags</b></td><td><code>i</code> = ignore case, <code>m</code> = multiline, <code>s</code> = dotall</td></tr>
        </table>

        <h2>🔁 Replacements grid</h2>
        <p>Each row defines a <b>find → replace</b> step applied in order.</p>
        <table>
        <tr><th>Column</th><th>Meaning</th></tr>
        <tr><td><b>Find</b></td><td>Regex pattern to search</td></tr>
        <tr><td><b>With</b></td><td>Replacement template (supports backreferences)</td></tr>
        <tr><td><b>Flags</b></td><td>Same as fragments</td></tr>
        </table>

        <h3>✨ Backreferences in <i>With</i></h3>
        <table>
        <tr><th>Syntax</th><th>Meaning</th></tr>
        <tr><td><code>\\1</code>, <code>\\12</code></td><td>Numeric group</td></tr>
        <tr><td><code>\\g&lt;name&gt;</code></td><td>Named group</td></tr>
        <tr><td><code>\\U1</code> / <code>\\U&lt;name&gt;</code></td><td>🔠 UPPERCASE</td></tr>
        <tr><td><code>\\L1</code> / <code>\\L&lt;name&gt;</code></td><td>🔡 lowercase</td></tr>
        <tr><td><code>\\T1</code> / <code>\\T&lt;name&gt;</code></td><td>🔤 Title Case</td></tr>
        <tr><td><code>\\n</code>, <code>\\t</code>, <code>\\r</code>, <code>\\\\</code></td><td>Escape sequences</td></tr>
        </table>

        <div class="tip">
        💡 <b>Example:</b><br>
        Pattern: <code>name\\s+(\\S+).*password\\s+(\\S+)</code><br>
        With: <code>hostname \\U1\\nenable secret @\\2!\\n</code><br>
        Input: <code>the name router1 has password firefox</code><br>
        Output:
        <pre>hostname ROUTER1
    enable secret @firefox!</pre>
        </div>

        <h2>🧪 Tests grid</h2>
        <p>Each row is a <b>named scenario</b> with expected output. Use the
        <i>Run</i> action to verify all tests at once — green = pass, red = fail.</p>

        <h2>📝 Quick test fields (bottom)</h2>
        <ul>
        <li><b>Input</b> — paste any sample (multi-line OK).</li>
        <li><b>Output</b> — read-only, shows the rule's result.</li>
        <li><kbd>Ctrl</kbd>+<kbd>Enter</kbd> in <i>Input</i> runs the test.</li>
        </ul>

        <h2>⌨️ Keyboard shortcuts</h2>
        <table>
        <tr><th>Key</th><th>Action</th></tr>
        <tr><td><kbd>Enter</kbd> / <kbd>F2</kbd></td><td>Edit selected cell</td></tr>
        <tr><td><kbd>Ctrl</kbd>+<kbd>Enter</kbd></td><td>Run quick test (in Input field)</td></tr>
        <tr><td><kbd>F1</kbd></td><td>Show this help</td></tr>
        <tr><td><kbd>Esc</kbd></td><td>Close (asks if unsaved)</td></tr>
        </table>

        <h2>💾 Saving</h2>
        <p>Click <b>Save</b> to persist changes (dialog stays open). Click
        <b>Close</b> to exit — you'll be prompted if there are unsaved edits.</p>
        """

    # ═══════════════════════════════════════════════════════
    #  Public: get the edited ruleset
    # ═══════════════════════════════════════════════════════

    def result_ruleset(self) -> RuleSet:
        return self._ruleset
