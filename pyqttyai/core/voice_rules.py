"""📋 Voice transcription rewrite rules — load/save helpers."""

from .rules_engine import Rule, RuleSet


def load_rules() -> RuleSet:
    """🔓 Load the user's rule set, seeding defaults on first run."""
    rs = RuleSet.load()
    if not rs.rules:
        rs.rules.append(_default_ipv6_rule())
        rs.save()        # 💾 persist seed
    return rs


def save_rules(rs: RuleSet) -> bool:
    """💾 Persist the rule set (returns True on success)."""
    return rs.save()

# ═══════════════════════════════════════════════════════════════════
#  🎁 Built-in defaults (seeded on first run)
# ═══════════════════════════════════════════════════════════════════

def _default_ipv6_rule() -> Rule:
    """🌐 The working IPv6 rule from your tests."""
    return Rule(
        name="IPv6 with CIDR",
        fragments={
            "key_word":  r"[,\.\s-]*ipv6[,\s-]*",
            "word_sep":  r"[,\s-]",
            "bar":       r"barra|bar|slash|\\|\||/",
            "colon":     r"colon|dot|dois\s+pontos?|\b2\s+pontos?|\b2\.|\.(?!\Z)|:",
            "hex":       r"[0-9a-f]+",
            ",+space":   r"(?<=\w)\s*,\s*(?=\w)",
            "hyphen":    r"-",
            "hex4":      r"([0-9a-f]{4})(?!:)(?!\Z)",
            "sentinel":  r"_",
        },
        pattern_template=r"{key_word}(?:{word_sep}*(?:{bar}|{colon}|{hex}))+",
        handler="compose_replace",
        handler_config={
            "replacements": [
                {"fragment": "key_word", "with": "_"},
                {"fragment": "hyphen",   "with": ""},
                {"fragment": "bar",      "with": "/"},
                {"fragment": "colon",    "with": ":"},
                {"fragment": ",+space",  "with": ":"},
                {"fragment": "word_sep", "with": ""},
                {"fragment": "hex4",     "with": r"\1:"},
                {"fragment": "sentinel", "with": " "},
            ],
            "post_process": "upper",
        },
    )
