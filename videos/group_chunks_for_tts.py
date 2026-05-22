import re
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================
INPUT_SBV   = "v0.5_captions_en-us.sbv"
OUTPUT_SBV  = "v0.5_captions_en-us_sentences.sbv"

XTTS_LIMIT       = 240    # safety margin below XTTS's 250-char hard limit
MIN_PIECE        = 30     # don't create absurdly tiny text pieces
MIN_DURATION_MS  = 2000   # merge anything shorter than 2 seconds
MERGE_MAX_CHARS  = XTTS_LIMIT  # don't let merging exceed XTTS limit

# Sentence-ending punctuation (for end-of-text detection)
SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*\s*$")

# Mid-text sentence boundary: terminator + space + capital/opening quote
SENTENCE_SPLIT = re.compile(r'([.!?]+["\')\]]*)\s+(?=[A-Z"\'(])')

# Abbreviations ending in "." that are NOT sentence ends
ABBREV = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "st.", "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.",
    "u.s.", "u.k.", "no.", "fig.", "inc.", "ltd.",
}

# Punctuation we can split long sentences on (strongest pause first)
SPLIT_PUNCT = [";", ":", " — ", " – ", ",", " and ", " but ", " or ", " so "]

# ============================================================
# TTS text normalizer (units + abbreviations)
# ============================================================

# Units that REQUIRE a preceding number (avoid English collisions)
NUM_UNIT_MAP = {
    r"(\d)\s*ms\b":   r"\1 milliseconds",
    r"(\d)\s*s\b":    r"\1 seconds",
    r"(\d)\s*min\b":  r"\1 minutes",
    r"(\d)\s*hrs?\b": r"\1 hours",
    r"(\d)\s*kg\b":   r"\1 kilograms",
    r"(\d)\s*mg\b":   r"\1 milligrams",
    r"(\d)\s*g\b":    r"\1 grams",
    r"(\d)\s*km/h\b": r"\1 kilometers per hour",
    r"(\d)\s*km\b":   r"\1 kilometers",
    r"(\d)\s*cm\b":   r"\1 centimeters",
    r"(\d)\s*mm\b":   r"\1 millimeters",
    r"(\d)\s*m\b":    r"\1 meters",
    r"(\d)\s*ft\b":   r"\1 feet",
    r"(\d)\s*in\b":   r"\1 inches",
    r"(\d)\s*mph\b":  r"\1 miles per hour",
    r"(\d)\s*kph\b":  r"\1 kilometers per hour",
}

# Units that are safe as standalone tokens (uppercase/mixed-case)
UNIT_MAP = {
    r"\bkHz\b":  "kilohertz",
    r"\bMHz\b":  "megahertz",
    r"\bGHz\b":  "gigahertz",
    r"\bHz\b":   "hertz",
    r"\bKB\b":   "kilobytes",
    r"\bMB\b":   "megabytes",
    r"\bGB\b":   "gigabytes",
    r"\bTB\b":   "terabytes",
    r"%":        " percent",
}

ABBREV_MAP = {
    r"\bMr\.":   "Mister",
    r"\bMrs\.":  "Missus",
    r"\bMs\.":   "Miss",
    r"\bDr\.":   "Doctor",
    r"\bProf\.": "Professor",
    r"\bSt\.":   "Saint",
    r"\bvs\.":   "versus",
    r"\betc\.":  "etcetera",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\ba\.m\.": "A M",
    r"\bp\.m\.": "P M",
    r"\bU\.S\.": "United States",
    r"\bU\.K\.": "United Kingdom",
    r"\bNo\.":   "Number",
    r"&":        " and ",
}

def normalize_for_tts(text: str) -> str:
    out = text

    # 1) Abbreviations (Mr., Dr., U.S., etc.)
    for pat, rep in ABBREV_MAP.items():
        out = re.sub(pat, rep, out)

    # 2) Digit-anchored units FIRST (safe against "That's", "in the", etc.)
    for pat, rep in NUM_UNIT_MAP.items():
        out = re.sub(pat, rep, out)

    # 3) Standalone case-sensitive units (Hz, MB, %, ...)
    for pat, rep in UNIT_MAP.items():
        out = re.sub(pat, rep, out)

    # 4) Collapse double spaces
    out = re.sub(r"\s+", " ", out).strip()
    return out

# ============================================================
# SBV time helpers
# ============================================================
def sbv_time_to_ms(t: str) -> int:
    h, m, s = t.split(":")
    sec, ms = s.split(".")
    return (int(h)*3600 + int(m)*60 + int(sec))*1000 + int(ms)

def ms_to_sbv_time(ms: int) -> str:
    if ms < 0: ms = 0
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms3 = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{ms3:03d}"

# ============================================================
# Parse SBV → list of caption blocks
# ============================================================
def parse_sbv(path: str):
    raw = Path(path).read_text(encoding="utf-8").strip()
    blocks = re.split(r"\n\s*\n", raw)
    caps = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = re.match(
            r"(\d+:\d{2}:\d{2}\.\d{3})\s*,\s*(\d+:\d{2}:\d{2}\.\d{3})",
            lines[0],
        )
        if not m:
            continue
        text = re.sub(r"\s+", " ", " ".join(lines[1:])).strip()
        caps.append({
            "start_ms": sbv_time_to_ms(m.group(1)),
            "end_ms":   sbv_time_to_ms(m.group(2)),
            "text":     text,
        })
    return caps

# ============================================================
# Sentence-end detection (skips abbreviations)
# ============================================================
def ends_sentence(text: str) -> bool:
    if not SENTENCE_END.search(text):
        return False
    last_token = text.strip().split()[-1].lower()
    last_token_clean = re.sub(r"[\"')\]]+$", "", last_token)
    if last_token_clean in ABBREV:
        return False
    return True

# ============================================================
# Phase 0 — split caption blocks that contain multiple sentences
# (handles input SBVs where one block holds several full sentences)
# ============================================================
def split_caption_into_sentences(cap: dict) -> list:
    """
    Split a single caption block whose text contains multiple sentences
    into multiple caption blocks, distributing the time window by
    character density. Respects abbreviations (Mr., e.g., U.S., ...).
    """
    text = cap["text"].strip()

    # Find all candidate split points (positions right after `.`/`!`/`?`)
    candidates = [m.end() for m in SENTENCE_SPLIT.finditer(text)]

    # Filter out splits that fall right after an abbreviation
    valid_cuts = []
    for pos in candidates:
        left = text[:pos].rstrip()
        tokens = left.split()
        if not tokens:
            continue
        last_token = tokens[-1].lower()
        last_token_clean = re.sub(r'["\')\]]+$', "", last_token)
        if last_token_clean in ABBREV:
            continue
        valid_cuts.append(pos)

    if not valid_cuts:
        return [cap]  # nothing to split

    # Build the sentence pieces
    pieces = []
    prev = 0
    for cut in valid_cuts:
        pieces.append(text[prev:cut].strip())
        prev = cut
    if prev < len(text):
        pieces.append(text[prev:].strip())
    pieces = [p for p in pieces if p]

    if len(pieces) == 1:
        return [cap]

    # Distribute the original time window by character density
    total_chars = sum(len(p) for p in pieces)
    duration    = cap["end_ms"] - cap["start_ms"]
    if total_chars == 0 or duration <= 0:
        return [cap]

    out = []
    cursor = 0
    for i, p in enumerate(pieces):
        st = cap["start_ms"] + round(cursor / total_chars * duration)
        cursor += len(p)
        en = (cap["end_ms"]
              if i == len(pieces) - 1
              else cap["start_ms"] + round(cursor / total_chars * duration))
        out.append({"start_ms": st, "end_ms": en, "text": p})
    return out

# ============================================================
# Phase 2 — split a long sentence at natural pause points
# Returns: list of text pieces (in order)
# ============================================================
def split_long_text(text: str, limit: int = XTTS_LIMIT) -> list:
    text = text.strip()
    if len(text) <= limit:
        return [text]

    pieces = []
    remaining = text

    while len(remaining) > limit:
        window = remaining[:limit]
        cut = -1
        for punct in SPLIT_PUNCT:
            idx = window.rfind(punct)
            if idx > limit * 0.4:
                cut = idx + len(punct)
                break
        if cut == -1:
            cut = window.rfind(" ")
            if cut == -1:
                cut = limit  # hard cut (very rare)

        piece = remaining[:cut].strip()
        if len(piece) >= MIN_PIECE or not pieces:
            pieces.append(piece)
        else:
            # merge tiny piece into previous one
            pieces[-1] = (pieces[-1] + " " + piece).strip()
        remaining = remaining[cut:].strip()

    if remaining:
        if len(remaining) < MIN_PIECE and pieces:
            pieces[-1] = (pieces[-1] + " " + remaining).strip()
        else:
            pieces.append(remaining)

    return pieces

# ============================================================
# Distribute a sentence's [start_ms, end_ms] across its pieces
# by character density (assumes constant speaking rate).
# ============================================================
def distribute_timing(pieces, start_ms, end_ms):
    total_chars = sum(len(p) for p in pieces)
    duration    = end_ms - start_ms
    if total_chars == 0 or duration <= 0:
        return [(start_ms, end_ms, p) for p in pieces]

    out = []
    cursor_chars = 0
    for i, p in enumerate(pieces):
        piece_start = start_ms + round(cursor_chars / total_chars * duration)
        cursor_chars += len(p)
        if i == len(pieces) - 1:
            piece_end = end_ms          # snap last piece to true end
        else:
            piece_end = start_ms + round(cursor_chars / total_chars * duration)
        out.append((piece_start, piece_end, p))
    return out

# ============================================================
# MAIN
# ============================================================
caps = parse_sbv(INPUT_SBV)
print(f"📥 Loaded {len(caps)} EN caption blocks")

# ------------------------------------------------------------
# Phase 0 — pre-split captions that already contain multiple
# sentences inside a single block.
# ------------------------------------------------------------
expanded = []
for c in caps:
    expanded.extend(split_caption_into_sentences(c))

split_count = len(expanded) - len(caps)
print(f"🔸 Phase 0: pre-split {split_count} mid-sentence breaks "
      f"→ {len(expanded)} caption blocks")
caps = expanded

# ------------------------------------------------------------
# Phase 1 — group fragment captions into full sentences
# ------------------------------------------------------------
raw_sentences = []
buf_text, buf_start, buf_end = [], None, None

for cap in caps:
    if buf_start is None:
        buf_start = cap["start_ms"]
    buf_end = cap["end_ms"]
    buf_text.append(cap["text"])

    if ends_sentence(cap["text"]):
        full = re.sub(r"\s+", " ", " ".join(buf_text)).strip()
        raw_sentences.append({"start_ms": buf_start, "end_ms": buf_end, "text": full})
        buf_text, buf_start, buf_end = [], None, None

if buf_text:
    full = re.sub(r"\s+", " ", " ".join(buf_text)).strip()
    raw_sentences.append({"start_ms": buf_start, "end_ms": buf_end, "text": full})

print(f"🔹 Phase 1: {len(raw_sentences)} raw sentences")

# ------------------------------------------------------------
# Phase 2 — normalize + split long ones + redistribute timing
# ------------------------------------------------------------
final_sentences = []
stats = {"short": 0, "split": 0, "total_pieces": 0}

for s in raw_sentences:
    normalized = normalize_for_tts(s["text"])
    pieces = split_long_text(normalized, limit=XTTS_LIMIT)

    if len(pieces) == 1:
        stats["short"] += 1
    else:
        stats["split"] += 1
    stats["total_pieces"] += len(pieces)

    timed = distribute_timing(pieces, s["start_ms"], s["end_ms"])
    for st, en, txt in timed:
        final_sentences.append({"start_ms": st, "end_ms": en, "text": txt})

print(f"🔹 Phase 2: {stats['short']} kept whole, "
      f"{stats['split']} split → {stats['total_pieces']} pieces total")

# ------------------------------------------------------------
# Phase 3 — merge chunks shorter than MIN_DURATION_MS into the
# previous chunk (avoids tiny TTS fragments that sound choppy).
# ------------------------------------------------------------
merged = []
merge_count = 0
for s in final_sentences:
    duration = s["end_ms"] - s["start_ms"]

    can_merge = (
        merged
        and duration < MIN_DURATION_MS
        and len(merged[-1]["text"]) + 1 + len(s["text"]) <= MERGE_MAX_CHARS
    )

    if can_merge:
        prev = merged[-1]
        prev["text"]   = (prev["text"].rstrip() + " " + s["text"].lstrip()).strip()
        prev["end_ms"] = s["end_ms"]
        merge_count   += 1
    else:
        merged.append(dict(s))

print(f"🔹 Phase 3: merged {merge_count} tiny chunks "
      f"(< {MIN_DURATION_MS}ms) → {len(merged)} final blocks")
final_sentences = merged

print(f"📤 Produced {len(final_sentences)} final TTS-ready blocks")

# ============================================================
# Write the new SBV
# ============================================================
out_lines = []
for s in final_sentences:
    out_lines.append(f"{ms_to_sbv_time(s['start_ms'])},{ms_to_sbv_time(s['end_ms'])}")
    out_lines.append(s["text"])
    out_lines.append("")

Path(OUTPUT_SBV).write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
print(f"✅ Wrote: {OUTPUT_SBV}")

# ============================================================
# Diagnostics — duration distribution + previews
# ============================================================
durations = [(s["end_ms"] - s["start_ms"]) / 1000 for s in final_sentences]
if durations:
    print(f"\n📊 Duration stats (seconds):")
    print(f"   min={min(durations):.2f}  "
          f"max={max(durations):.2f}  "
          f"avg={sum(durations)/len(durations):.2f}")

    short_blocks = [(i, d) for i, d in enumerate(durations) if d < 2.0]
    long_blocks  = [(i, d) for i, d in enumerate(durations) if d > 20.0]
    if short_blocks:
        print(f"   ⚠️  {len(short_blocks)} block(s) still under 2s "
              f"(couldn't merge — likely text too long):")
        for i, d in short_blocks[:5]:
            print(f"      #{i+1} {d:.2f}s — {final_sentences[i]['text'][:60]}...")
    if long_blocks:
        print(f"   ⚠️  {len(long_blocks)} block(s) over 20s "
              f"(might need manual review):")
        for i, d in long_blocks[:5]:
            print(f"      #{i+1} {d:.2f}s — {final_sentences[i]['text'][:60]}...")

# Preview
print("\n--- preview (first 5 blocks) ---")
for s in final_sentences[:5]:
    dur = (s["end_ms"] - s["start_ms"]) / 1000
    print(f"{ms_to_sbv_time(s['start_ms'])} → {ms_to_sbv_time(s['end_ms'])}  "
          f"({dur:.2f}s, {len(s['text'])} chars)")
    print(f"  {s['text']}\n")
