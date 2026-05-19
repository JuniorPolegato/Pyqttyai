from __future__ import annotations
import re
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ClassVar, Optional

from pyqttyai.core.paths import config_dir

log = logging.getLogger(__name__)
log.setLevel(level=logging.DEBUG)

# ═══════════════════════════════════════════════════════════════════
#  🧩 Fragment composition
# ═══════════════════════════════════════════════════════════════════

# 🎯 Matches {fragment_name} placeholders in templates
#_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PLACEHOLDER_RE = re.compile(r"\{([^\d][^\s]*?)\}")

# 🛡️ Safety limit: prevent runaway recursion if user makes A→B→A
_MAX_EXPANSION_DEPTH = 16

# ═══════════════════════════════════════════════════════════════════
#  🪄 Case-aware backreference expansion
#     Supports: \1   \12   \g<name>   \g<1>
#               \U1  \L2   \T3        ← case modifiers, numeric groups
#               \U<name>  \L<name>  \T<name>   ← case modifiers, named
#               \\  \n  \r  \t                 ← passthrough escapes
# ═══════════════════════════════════════════════════════════════════

_BACKREF_RE = re.compile(
    r"""
    \\                          # leading backslash
    (?:
        ([ULT])<([^>]+)>        # 1,2: case modifier + named/numbered  \U<name>
      | ([ULT])(\d+)            # 3,4: case modifier + bare digits     \U1
      | g<([^>]+)>              # 5:   plain named/numbered            \g<name>
      | (\d+)                   # 6:   plain digits                    \1
      | ([\\nrt])               # 7:   escape passthrough              \\ \n \r \t
    )
    """,
    re.VERBOSE,
)

_CASE_FN = {
    "U": str.upper,
    "L": str.lower,
    "T": str.title,
}

_ESCAPE_MAP = {"\\": "\\", "n": "\n", "r": "\r", "t": "\t"}


def _resolve_group(match: re.Match, ref: str) -> str:
    """🔍 Look up a group by number or by name; return '' if missing."""
    try:
        # 🔢 numeric reference (e.g. "1", "12")
        return match.group(int(ref)) or ""
    except ValueError:
        log.debug("ValueError: %s", ref)  # , exc_info=True)
        # 🏷️ named reference (e.g. "host", "user")
        try:
            return match.group(ref) or ""
        except (IndexError, re.error):
            log.debug("IndexError, re.error", exc_info=True)
            return ""
    except IndexError:
        log.debug("IndexError", exc_info=True)
        return ""


def expand_case_backrefs(template: str, match: re.Match) -> str:
    """🪄 Expand backreferences with optional case modifiers.

    Examples (given groups: 1='router1', 'host'='router1'):
        \\1          → 'router1'
        \\U1         → 'ROUTER1'
        \\U<host>    → 'ROUTER1'
        \\L<host>    → 'router1'
        \\T<host>    → 'Router1'
        \\g<host>    → 'router1'
        \\n          → newline
    """
    def _sub(m: re.Match) -> str:
        (case_n, name_n,
         case_d, digits_d,
         plain_named,
         plain_digits,
         escape) = m.groups()

        # 🔡 Passthrough escape sequence
        if escape:
            return _ESCAPE_MAP[escape]

        # 🔠 Case modifier + named/numbered group:  \U<host>  \L<1>
        if case_n:
            return _CASE_FN[case_n](_resolve_group(match, name_n))

        # 🔠 Case modifier + bare digits:  \U1  \L12
        if case_d:
            return _CASE_FN[case_d](_resolve_group(match, digits_d))

        # 🏷️ Plain \g<...>
        if plain_named:
            return _resolve_group(match, plain_named)

        # 🔢 Plain \1, \12
        if plain_digits:
            return _resolve_group(match, plain_digits)

        return m.group(0)  # 🛡️ unreachable

    return _BACKREF_RE.sub(_sub, template)


def expand_fragments(template: str, fragments: dict[str, str]) -> str:
    """Recursively replace {name} placeholders with fragment values.

    Each fragment is wrapped in (?:...) to keep alternation safe under
    composition. Detects circular references.
    """
    seen_chain: list[str] = []

    def _expand(text: str, depth: int) -> str:
        if depth > _MAX_EXPANSION_DEPTH:
            raise ValueError(
                f"Fragment expansion too deep (>{_MAX_EXPANSION_DEPTH}); "
                f"possible circular reference in chain: {' -> '.join(seen_chain)}"
            )

        def _sub(match: re.Match) -> str:
            name = match.group(1)
            logging.debug('name: %s', name)
            if name not in fragments:
                raise KeyError(f"Unknown fragment '{{{name}}}'")
            if name in seen_chain:
                raise ValueError(
                    f"Circular fragment reference: "
                    f"{' -> '.join(seen_chain)} -> {name}"
                )
            seen_chain.append(name)
            try:
                logging.debug(fragments[name])
                expanded = _expand(fragments[name], depth + 1)
            finally:
                seen_chain.pop()
            # 🛡️ Wrap to keep alternation precedence safe
            return f"(?:{expanded})"

        return _PLACEHOLDER_RE.sub(_sub, text)

    return _expand(template, 0)


# ═══════════════════════════════════════════════════════════════════
#  🔧 Handler registry (for power users / built-in transforms)
# ═══════════════════════════════════════════════════════════════════

HandlerFn = Callable[[str, dict], str]
_HANDLERS: dict[str, HandlerFn] = {}


def register_handler(name: str):
    """Decorator to register a custom handler callable."""
    def _wrap(fn: HandlerFn) -> HandlerFn:
        _HANDLERS[name] = fn
        log.debug("registered handler '%s'", name)
        return fn
    return _wrap


def get_handler(name: str) -> Optional[HandlerFn]:
    return _HANDLERS.get(name)


# ═══════════════════════════════════════════════════════════════════
#  🎨 Built-in handlers
# ═══════════════════════════════════════════════════════════════════

@register_handler("literal")
def _h_literal(matched: str, cfg: dict) -> str:
    """Replace match with a literal string (supports \\U1, \\L2, \\T3)."""
    template = cfg.get("replacement", "")
    # 🪄 Re-match to get groups (cfg has no Match object directly)
    pattern = cfg.get("_match_pattern")
    if pattern:
        m = re.match(pattern, matched)
        if m:
            return expand_case_backrefs(template, m)
    return template


@register_handler("none")
def _h_none(matched: str, cfg: dict) -> str:
    """Do nothing."""
    return matched


@register_handler("compose_replace")
def _h_compose_replace(matched: str, cfg: dict) -> str:
    """Apply a sequence of fragment-based substitutions to the match.

    cfg requires:
        fragments:    dict[str, str]
        replacements: list of {"fragment": name, "with": str}
                      OR        {"pattern":  raw,  "with": str}
    cfg optional:
        post_process: "upper" | "lower" | "title" | ""
        flags:        list of "IGNORECASE" | "DOTALL" | ...
    """
    fragments = cfg.get("fragments", {})
    replacements = cfg.get("replacements", [])
    post = cfg.get("post_process", "")
    flags = _parse_flags(cfg.get("flags", ["IGNORECASE"]))

    text = matched
    log.debug(fragments)
    for rep in replacements:
        log.debug("\n\n===>%s<===\n [%s]", text, rep)
        if "fragment" in rep:
            frag_name = rep["fragment"]
            log.debug('frag_name: %s %s', frag_name, frag_name not in fragments)
            if frag_name not in fragments:
                log.warning("replacement refers to unknown fragment '%s'", frag_name)
                continue
            frag_re = expand_fragments(f"{{{frag_name}}}", fragments)
        elif "pattern" in rep:
            frag_re = expand_fragments(rep["pattern"], fragments)
        elif "none" in rep:
            log.warning("Skiping: %s", rep["none"])
        else:
            log.warning("replacement missing 'fragment' or 'pattern': %r", rep)
            continue

        replacement = rep.get("with", "")
        def _replace(m: re.Match, _r=replacement) -> str:
            return expand_case_backrefs(_r, m)

        text = re.sub(frag_re, _replace, text, flags=flags)
        log.debug("%s <= %s %s (%s)", text, frag_re, rep, replacement)

    if post == "upper":
        text = text.upper()
    elif post == "lower":
        text = text.lower()
    elif post == "title":
        text = text.title()

    return text


def _parse_flags(names: list[str]) -> int:
    """Convert list of flag names to combined re flag int."""
    out = 0
    for n in names:
        f = getattr(re, n.upper(), None)
        if isinstance(f, int):
            out |= f
        else:
            log.warning("unknown re flag: %s", n)
    return out


# ═══════════════════════════════════════════════════════════════════
#  📋 Rule data class
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Rule:
    """A single text-rewrite rule."""
    name: str
    enabled: bool = True

    # 🆕 Fragment-based mode (preferred)
    fragments: dict[str, str] = field(default_factory=dict)
    pattern_template: str = ""

    # 🔙 Legacy mode (raw pattern, no fragments)
    pattern: str = ""

    # 🎯 Match flags
    flags: list[str] = field(default_factory=lambda: ["IGNORECASE"])

    # 🔧 Transformation
    handler: str = "compose_replace"
    handler_config: dict = field(default_factory=dict)

    # 🧪 Tests embedded in the rule (optional but encouraged)
    tests: list[dict] = field(default_factory=list)

    # ─── computed ─────────────────────────────────────────────────
    _compiled: Optional[re.Pattern] = field(default=None, init=False, repr=False)

    # ───────────────────────────────────────────────────────────────
    def compile(self) -> re.Pattern:
        """Compile the pattern, expanding fragments if needed."""
        if self._compiled is not None:
            return self._compiled

        if self.pattern_template:
            raw = expand_fragments(self.pattern_template, self.fragments)
        elif self.pattern:
            raw = self.pattern
        else:
            raise ValueError(f"rule '{self.name}' has no pattern")

        flags = _parse_flags(self.flags)
        try:
            self._compiled = re.compile(raw, flags)
        except re.error as e:
            raise ValueError(
                f"rule '{self.name}' has invalid regex: {e}\n"
                f"expanded pattern: {raw}"
            ) from e
        return self._compiled

    # ───────────────────────────────────────────────────────────────
    def apply(self, text: str) -> str:
        """Apply this rule to `text`, replacing all matches."""
        if not self.enabled:
            return text

        regex = self.compile()
        handler = get_handler(self.handler)
        if handler is None:
            log.error("rule '%s' uses unknown handler '%s'", self.name, self.handler)
            return text

        # 🧩 Build the config passed to the handler
        cfg = dict(self.handler_config)
        cfg.setdefault("fragments", self.fragments)
        cfg.setdefault("flags", self.flags)

        def _replace(m: re.Match) -> str:
            try:
                return handler(m.group(0), cfg)
            except Exception:
                log.exception("handler '%s' failed on rule '%s'", self.handler, self.name)
                return m.group(0)  # 🛡️ on error, leave text unchanged

        return regex.sub(_replace, text)

    # ───────────────────────────────────────────────────────────────
    def run_tests(self) -> list[tuple[bool, str, str, str]]:
        """Run embedded tests. Returns list of (ok, input, expected, actual)."""
        results = []
        for t in self.tests:
            inp = t.get("input", "")
            exp = t.get("expected", "")
            act = self.apply(inp)
            results.append((act == exp, inp, exp, act))
        return results

# ═══════════════════════════════════════════════════════════════════
#  📚 Rule set (collection + persistence)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RuleSet:
    """A collection of voice-transcription rewrite rules."""

    rules: list[Rule] = field(default_factory=list)

    CONFIG_FILE: ClassVar[str] = "voice_rules.json"

    # ───────────────────────────────────────────────────────────────
    #  🚀 Application
    # ───────────────────────────────────────────────────────────────
    def apply(self, text: str) -> str:
        """Apply all enabled rules in order."""
        for r in self.rules:
            try:
                text = r.apply(text)
            except Exception:
                log.exception("rule '%s' raised; skipping", r.name)
        return text

    # ───────────────────────────────────────────────────────────────
    #  🔄 Serialization
    # ───────────────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, data: dict) -> "RuleSet":
        known_rule_fields = {
            "name", "enabled", "fragments", "pattern_template",
            "pattern", "flags", "handler", "handler_config", "tests",
        }
        rules = []
        for raw in data.get("rules", []):
            filtered = {k: v for k, v in raw.items() if k in known_rule_fields}
            rules.append(Rule(**filtered))
        return cls(rules=rules)

    def to_dict(self) -> dict:
        return {
            "rules": [
                {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
                for r in self.rules
            ]
        }

    # ───────────────────────────────────────────────────────────────
    #  🛡️ Validation
    # ───────────────────────────────────────────────────────────────
    def validate(self) -> list[str]:
        """Return a list of human-readable error messages (empty = OK)."""
        errors: list[str] = []
        seen_names: set[str] = set()

        for i, r in enumerate(self.rules):
            label = f"rule[{i}] {r.name!r}"

            # 🏷️ Name
            if not r.name or not r.name.strip():
                errors.append(f"{label}: name is empty")
            elif r.name in seen_names:
                errors.append(f"{label}: duplicate name")
            else:
                seen_names.add(r.name)

            # 🎯 Must have either a template or a raw pattern
            if not r.pattern_template and not r.pattern:
                errors.append(f"{label}: no pattern_template or pattern")

            # 🔧 Handler must be registered
            if r.handler not in _HANDLERS:
                errors.append(
                    f"{label}: unknown handler {r.handler!r} "
                    f"(known: {sorted(_HANDLERS)})"
                )

            # 🚦 Try compiling — catches invalid regex & circular fragments
            try:
                # 🧹 force fresh compile for validation
                r._compiled = None
                r.compile()
            except Exception as e:
                errors.append(f"{label}: {e}")

        return errors

    # ───────────────────────────────────────────────────────────────
    #  🛡️ Migration (stub for future schema changes)
    # ───────────────────────────────────────────────────────────────
    @staticmethod
    def _migrate(data: dict) -> dict:
        """Migrate legacy on-disk schemas. Currently a no-op."""
        # 🌱 Example for future:
        # if data.get("schema_version", 1) < 2:
        #     for r in data.get("rules", []):
        #         r["flags"] = r.pop("regex_flags", ["IGNORECASE"])
        return data

    # ───────────────────────────────────────────────────────────────
    #  💾 Persistence
    # ───────────────────────────────────────────────────────────────
    @classmethod
    def _path(cls) -> Path:
        return config_dir() / cls.CONFIG_FILE

    @classmethod
    def load(cls) -> "RuleSet":
        """Load from default config path. Returns empty set on any error."""
        path = cls._path()
        if not path.exists():
            log.info("no rules file at %s; starting empty", path)
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 🛡️ Migrate legacy schemas
            data = cls._migrate(data)

            # 🧹 Filter to known top-level keys (forward-compat)
            known = {"rules"}
            filtered = {k: v for k, v in data.items() if k in known}

            rs = cls.from_dict(filtered)

            errors = rs.validate()
            if errors:
                print(
                    f"⚠ Invalid rules config ({len(errors)} issue(s)); "
                    f"using empty set:\n  - " + "\n  - ".join(errors)
                )
                return cls()
            return rs

        except (OSError, json.JSONDecodeError, TypeError) as e:
            print(f"⚠ Failed to load rules: {e}")
            return cls()

    def save(self) -> bool:
        """Persist to default path. Returns True on success."""
        try:
            path = self._path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except OSError as e:
            print(f"⚠ Failed to save rules: {e}")
            return False

    # ───────────────────────────────────────────────────────────────
    #  📊 Summary
    # ───────────────────────────────────────────────────────────────
    def summary(self) -> str:
        enabled = sum(1 for r in self.rules if r.enabled)
        return f"{len(self.rules)} rule(s), {enabled} enabled"
