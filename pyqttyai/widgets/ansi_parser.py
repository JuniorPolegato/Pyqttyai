"""
ANSI Escape Code parser for terminal output.
Supports SGR, cursor movement, erase, insert sequences.
"""

import re
from PyQt6.QtGui import QColor, QTextCharFormat, QFont

# Master regex
ANSI_ESCAPE_RE = re.compile(
    "("
    r"\x1b\].*?(?:\x07|\x1b\\)"       # OSC (window title etc)
    r"|\x1b\[\?[\d;]*[A-Za-z]"        # CSI private mode
    r"|\x1b\[[\d;]*[@A-Za-z]"         # CSI sequences (including @)
    r"|\x1b[()][AB012]"               # Charset
    r"|\x1bO[A-Za-z]"                 # SS3 sequences
    r"|\x1b[>=]"                       # Keypad modes
    r"|\x1b[\x20-\x2f][\x30-\x7e]"   # 2-byte ESC
    r"|\x1b."                          # Any other ESC
    r"|\x07"                           # BEL
    r"|\x08"                           # BS
    r"|\x7f"                           # DEL
    r"|\x0f"                           # SI
    r"|\x0e"                           # SO
    r"|\r"                             # CR
    ")"
)

CSI_SGR_RE = re.compile(r"\x1b\[([\d;]*)m")
CSI_ERASE_RE = re.compile(r"\x1b\[(\d*)([JK])")
CSI_CURSOR_RE = re.compile(r"\x1b\[(\d*)([ABCDGHP@])")

ANSI_COLORS = {
    0: "#2e3436", 1: "#cc0000", 2: "#4e9a06", 3: "#c4a000",
    4: "#3465a4", 5: "#75507b", 6: "#06989a", 7: "#d3d7cf",
}
ANSI_BRIGHT_COLORS = {
    0: "#555753", 1: "#ef2929", 2: "#8ae234", 3: "#fce94f",
    4: "#729fcf", 5: "#ad7fa8", 6: "#34e2e2", 7: "#eeeeec",
}


class AnsiState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.bold = False
        self.italic = False
        self.underline = False
        self.strikethrough = False
        self.fg_color: str | None = None
        self.bg_color: str | None = None

    def to_format(self, default_fg="#d3d7cf", default_bg="#1e1e2e"):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold if self.bold else QFont.Weight.Normal)
        fmt.setFontItalic(self.italic)
        if self.underline:
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
        else:
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.NoUnderline)
        fmt.setFontStrikeOut(self.strikethrough)
        fmt.setForeground(QColor(self.fg_color or default_fg))
        if self.bg_color:
            fmt.setBackground(QColor(self.bg_color))
        return fmt

    def apply_sgr(self, params: list[int]):
        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                self.reset()
            elif p == 1:
                self.bold = True
                if self.fg_color and self.fg_color in ANSI_COLORS.values():
                    for idx, color in ANSI_COLORS.items():
                        if color == self.fg_color:
                            self.fg_color = ANSI_BRIGHT_COLORS[idx]
                            break
            elif p == 2:
                self.bold = False
            elif p == 3:
                self.italic = True
            elif p == 4:
                self.underline = True
            elif p == 7:
                self.fg_color, self.bg_color = self.bg_color, self.fg_color
            elif p == 9:
                self.strikethrough = True
            elif p == 22:
                self.bold = False
            elif p == 23:
                self.italic = False
            elif p == 24:
                self.underline = False
            elif p == 29:
                self.strikethrough = False
            elif 30 <= p <= 37:
                idx = p - 30
                self.fg_color = ANSI_BRIGHT_COLORS.get(idx) if self.bold else ANSI_COLORS.get(idx)
            elif 90 <= p <= 97:
                self.fg_color = ANSI_BRIGHT_COLORS.get(p - 90)
            elif 40 <= p <= 47:
                self.bg_color = ANSI_COLORS.get(p - 40)
            elif 100 <= p <= 107:
                self.bg_color = ANSI_BRIGHT_COLORS.get(p - 100)
            elif p == 38 and i + 2 < len(params) and params[i + 1] == 5:
                self.fg_color = _color_256(params[i + 2])
                i += 2
            elif p == 48 and i + 2 < len(params) and params[i + 1] == 5:
                self.bg_color = _color_256(params[i + 2])
                i += 2
            elif p == 38 and i + 4 < len(params) and params[i + 1] == 2:
                r, g, b = params[i + 2], params[i + 3], params[i + 4]
                self.fg_color = f"#{r:02x}{g:02x}{b:02x}"
                i += 4
            elif p == 48 and i + 4 < len(params) and params[i + 1] == 2:
                r, g, b = params[i + 2], params[i + 3], params[i + 4]
                self.bg_color = f"#{r:02x}{g:02x}{b:02x}"
                i += 4
            elif p == 39:
                self.fg_color = None
            elif p == 49:
                self.bg_color = None
            i += 1


def _color_256(n: int) -> str:
    if n < 0 or n > 255:
        return "#d3d7cf"
    if n < 8:
        return ANSI_COLORS[n]
    if n < 16:
        return ANSI_BRIGHT_COLORS[n - 8]
    if n < 232:
        n -= 16
        b = (n % 6) * 51
        g = ((n // 6) % 6) * 51
        r = (n // 36) * 51
        return f"#{r:02x}{g:02x}{b:02x}"
    v = 8 + (n - 232) * 10
    return f"#{v:02x}{v:02x}{v:02x}"


def parse_ansi_text(text: str) -> list[tuple[str, object]]:
    """
    Parse text into segments: (text, action).
    Actions: None=text, list=SGR, str=control
    """
    segments: list[tuple[str, object]] = []
    last_end = 0

    for match in ANSI_ESCAPE_RE.finditer(text):
        start, end = match.span()

        if start > last_end:
            plain = text[last_end:start]
            if plain:
                segments.append((plain, None))

        seq = match.group(0)

        # Backspace
        if seq == "\x08":
            segments.append(("", "BS"))
            last_end = end
            continue

        # DEL
        if seq == "\x7f":
            segments.append(("", "BS"))
            last_end = end
            continue

        # Carriage return
        if seq == "\r":
            segments.append(("", "CR"))
            last_end = end
            continue

        # SGR
        sgr_match = CSI_SGR_RE.fullmatch(seq)
        if sgr_match:
            param_str = sgr_match.group(1)
            if param_str:
                try:
                    params = [int(x) for x in param_str.split(";")]
                except ValueError:
                    params = [0]
            else:
                params = [0]
            segments.append(("", params))
            last_end = end
            continue

        # Erase
        erase_match = CSI_ERASE_RE.fullmatch(seq)
        if erase_match:
            n = int(erase_match.group(1)) if erase_match.group(1) else 0
            cmd = erase_match.group(2)
            if cmd == "K":
                segments.append(("", f"EL{n}"))
            elif cmd == "J":
                segments.append(("", f"ED{n}"))
            last_end = end
            continue

        # Cursor movement + ICH + DCH
        cursor_match = CSI_CURSOR_RE.fullmatch(seq)
        if cursor_match:
            n = int(cursor_match.group(1)) if cursor_match.group(1) else 1
            cmd = cursor_match.group(2)
            if cmd == "A":
                segments.append(("", f"CUU{n}"))
            elif cmd == "B":
                segments.append(("", f"CUD{n}"))
            elif cmd == "C":
                segments.append(("", f"CUF{n}"))
            elif cmd == "D":
                segments.append(("", f"CUB{n}"))
            elif cmd == "G":
                segments.append(("", f"CHA{n}"))
            elif cmd == "P":
                segments.append(("", f"DCH{n}"))
            elif cmd == "@":
                segments.append(("", f"ICH{n}"))
            elif cmd == "H":
                segments.append(("", f"CUP{n}"))
            last_end = end
            continue

        # Everything else: strip
        last_end = end

    if last_end < len(text):
        remaining = text[last_end:]
        if remaining:
            segments.append((remaining, None))

    return segments
