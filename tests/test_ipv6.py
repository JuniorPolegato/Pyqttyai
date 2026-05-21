import logging
from pyqttyai.core.rules_engine import Rule, RuleSet

#logging.getLogger("rules_engine").setLevel(level=logging.DEBUG)

ipv6_rule = Rule(
    name="IPv6 with CIDR",
    fragments={
        "key_word":   r"[,\.\s-]*ipv6[,\s-]*",
        "word_sep":   r"[,\s-]",
        "bar":        r"barra|bar|slash|\\|\||/",
        "colon":      r"colon|dot|dois\s+pontos?|\b2\s+pontos?|\b2\.|\.(?!\Z)|:",
        "hex":        r"[0-9a-f]+",
        ",+space":    r"(?<=\w)\s*,\s*(?=\w)",
        "hyphen":     r"-",
        "hex4":       r"([0-9a-f]{4})(?!:)(?!\Z)",
        "sentinel":   r"_",
    },
    pattern_template=r"{key_word}(?:{word_sep}*(?:{bar}|{colon}|{hex}))+",
    handler="compose_replace",
    handler_config={
        "replacements": [
            {"fragment": "key_word",  "with": "_"},  # sentinel
            {"fragment": "hyphen",    "with": ""},
            {"fragment": "bar",       "with": "/"},
            {"fragment": "colon",     "with": ":"},
            {"fragment": ",+space",   "with": ":"},
            {"fragment": "word_sep",  "with": ""},
            {"fragment": "hex4",      "with": r"\1:"},
            {"fragment": "sentinel",  "with": " "},
        ],
        "post_process": "upper",
    },
    tests=[
        {
            "input":    "O servidor é ipv6 2002 2 pontos, CAFE, 2 pontos, A B C 2. 2. 1, barra, 64 ok",
            "expected": "O servidor é 2002:CAFE:ABC::1/64 ok",
        },
        {
            "input":    "Local is ipv6 fe80 colon colon 1",
            "expected": "Local is FE80::1",
        },
        {
            "input":    "The network is ipv6 2002 colon, ACAD: CAFE, colon, A B C 2. 2. slash 64, okay?",
            "expected": "The network is 2002:ACAD:CAFE:ABC::/64, ok?",
        },
        {
            "input":    "O IPv6 é IPv6 2008, ACAD, CAFE, DB8, 2.2.1.64",
            "expected": "O IPv6 é 2008:ACAD:CAFE:DB8::1:64",
        },
        {
            "input":    "My IPv6 is IPv6 202. ACAD C-A-F-E 1, 10, 20.",
            "expected": "My IPv6 is 202:ACAD:CAFE:1:10:20.",
        },
        {
            "input":    "IPv6, IPv6, 2008, ACAD, CAFE 10, 20, 2.2.1.",
            "expected": "IPv6 2008:ACAD:CAFE:10:20::1.",
        },

    ],
)

# 🧪 Run embedded tests
for ok, inp, exp, act in ipv6_rule.run_tests():
    icon = "✅" if ok else "❌"
    print(f"\n{icon} {inp!r}")
    if not ok:
        print(f"   expected: {exp!r}")
        print(f"   actual:   {act!r}")
    else:
        print(f"{icon} {act!r}")

# 🚀 Use in a RuleSet
rs = RuleSet(rules=[ipv6_rule])
print(rs.apply("O servidor é ipv6 2002 2 pontos, ACAD : CAFE, 2 pontos, A B C 2. 2. 1, barra, 64 ok"))
print(rs.apply("O IPv6 é ipv62008, ACAD, CAFE, DB8, 2.2.1.64"))
