# 🎙️ TTS Dubbing Pipeline

End-to-end workflow for translating and dubbing a video using Groq (timestamps), XTTS v2 (voice synthesis), and ffmpeg (assembly).

---

## 🎤 Stage 0 — Transcription (PT-BR → EN-US SBV)

The TTS pipeline assumes you already have a well-timed English SBV
file. Here's how that file is produced:

### 1. Extract audio from the video

```bash
ffmpeg -i Protected_Pyqttyai_v0.4_10fps_hevc.mp4 \
    -vn -c:a copy audio_output_4.m4a
```

### 2. Transcribe with Whisper (via Pyqttyai)

Configure model and hardware in **Pyqttyai → Whisper Settings**.

- Default: **Groq `whisper-large-v3-turbo`** (cloud, fastest)
- Alternative: **`faster_whisper`** (local, configurable model size)

Adjust `language` and `initial_prompt` inside
`tests/test_word_timestamp_srt.py` to match your audio's domain
(language, technical terms, jargon).

```bash
python ../tests/test_word_timestamp_srt.py audio_output_4.m4a \
    | tee v0.1_groq.log
```

### 3. Strip log headers/footers → clean SRT

```bash
sed '1,/^=====================/d;/^\[/d;/^============/,$d' \
    v0.1_groq.log | tee v0.1_groq_pt-br.srt
```

### 4. Human-in-the-loop alignment (PT-BR)

- Upload `v0.1_groq_pt-br.srt` to YouTube as PT-BR captions
- Use YouTube's caption editor to fine-tune timings against the video
- Download as `v0.1_captions_pt-br.sbv`

### 5. AI translation (PT-BR → EN-US)

Prompt an LLM (Claude, GPT, etc.) with:

> Translate this SBV file from PT-BR to EN-US.
> **Do not change** the timestamps or the chunk boundaries.
> Output the same SBV structure with English text only.

Save as `v0.1_ai_captions_en-us.sbv`.

### 6. Human-in-the-loop alignment (EN-US)

- Upload `v0.1_ai_captions_en-us.sbv` to YouTube as EN captions
- Adjust timings (English may need different pacing than PT-BR)
- Download as `v0.1_captions_en-us.sbv`

✅ This file is the input to the sentence-grouping stage
(`group_chunks_for_tts.py`).

---

## 🧠 Why this hybrid pipeline works

Each stage uses the right tool for the right job:

| Stage | Best tool | Why |
|---|---|---|
| Word-level transcription | Groq Whisper / faster_whisper | Fastest + most accurate ASR available |
| Timeline alignment | YouTube caption editor | Visual forced-alignment against video |
| Semantic translation | LLM (Claude/GPT) | Preserves meaning while keeping SBV structure |
| Re-alignment after translation | YouTube caption editor | EN word lengths differ from PT-BR |
| Sentence reshaping | `group_chunks_for_tts.py` | TTS needs full sentences, not word chunks |
| Voice cloning | Coqui XTTS v2 | Natural prosody at sentence granularity |
| Audio assembly | `pydub` overlay | Precise timestamp placement, no time-stretching |

The combination of **automated tools + targeted human checkpoints** is
exactly how production dubbing pipelines work.

---

## 📋 Updated Pipeline Summary

| Stage | Where | Tool | Output |
|---|---|---|---|
| 0a. Audio for transcription | local | `ffmpeg` | `audio_output_*.m4a` |
| 0b. Whisper transcription | local/cloud | Pyqttyai + Groq/faster_whisper | `v0.1_groq_pt-br.srt` |
| 0c. PT-BR alignment | YouTube web | manual | `v0.1_captions_pt-br.sbv` |
| 0d. Translation | AI chat | LLM | `v0.1_ai_captions_en-us.sbv` |
| 0e. EN alignment | YouTube web | manual | `v0.1_captions_en-us.sbv` |
| 1. Voice sample extraction | local | `ffmpeg` | `voice_sample.wav` |
| 2. Sentence grouping | local | `group_chunks_for_tts.py` | `v0.1_captions_en-us_sentences.sbv` |
| 3. Voice synthesis | Colab T4 GPU | Coqui XTTS v2 | `chunks/chunk_*.wav` |
| 4. Track assembly | Colab T4 GPU | `pydub` | `final_dub.wav` / `.mp3` |
| 5. Video muxing | Colab T4 / local | `ffmpeg` | `dubbed_video[_mixed].mp4` |

---

## 🧠 The Logic

```
YouTube auto/upload captions
(EN, word/phrase level + timestamps)
        ↓
Manual fine-tuning of translation against the video
        ↓
group_chunks_for_tts.py  →  sentence-level SBV
        ↓
XTTS v2 (voice cloning) → one .wav per sentence
        ↓
pydub overlay at each start_ms → final_dub.wav
        ↓
ffmpeg mux with original video → dubbed_video.mp4
```

---

## 🎧 Audio Extraction

Extract the audio track without re-encoding:

```bash
ffmpeg -i Protected_Pyqttyai_v0.1_10fps_hevc.mp4 -vn -c:a copy audio_output_1.m4a
```

Extract the voice sample audio from track:

```bash
ffmpeg -i Protected_Pyqttyai_v0.1_10fps_hevc.mp4 -ss 00:00:05 -t 00:00:25 -vn -acodec pcm_s16le -ar 22050 -ac 1 voice_sample.wav
```

---

## 🧩 The Grouping Algorithm

```
SBV captions (timed text)
        ↓
Phase 0:  split blocks containing multiple sentences
        ↓
Phase 1:  group fragments → full sentences (close on .!?)
        ↓
Phase 2:  normalize text + split sentences > 240 chars
        ↓
Phase 3:  merge chunks shorter than 2s into previous
        ↓
TTS-ready SBV (one sentence per block, timed)
```

### `group_chunks_for_tts.py`

```python
import re
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================
INPUT_SBV   = "v0.1_captions_en-us.sbv.txt"
OUTPUT_SBV  = "v0.1_captions_en-us_sentences.sbv"

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
```

---

## ☁️ Google Colab (T4 GPU)

### 📋 Before Running — Quick Checklist

    1. In Colab: Runtime → Change runtime type → T4 GPU
    2. Upload your voice_sample.wav via the left sidebar 📁
    3. Upload also your v0.1_captions_en-us_sentences.sbv and video 📁
    4. If Colab suggests auto-installing a different TTS package, decline — you need coqui-tts specifically.

### Cell 1 — Install dependencies

```bash
!pip install coqui-tts pydub
!apt-get install -y ffmpeg
```

### Cell 2 — Accept license + imports

```python
import os
os.environ["COQUI_TOS_AGREED"] = "1"

import re
import torch
from TTS.api import TTS
from pydub import AudioSegment
from pathlib import Path
```

### Cell 3 — Parse the `.sbv` file

```python
def parse_sbv(path):
    """Parse .sbv → list of dicts: [{start_ms, end_ms, text}, ...]"""
    def time_to_ms(t):
        # Format: H:MM:SS.mmm
        h, m, s = t.split(":")
        sec, ms = s.split(".")
        return (int(h)*3600 + int(m)*60 + int(sec))*1000 + int(ms)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    blocks = re.split(r"\n\s*\n", content)
    captions = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        times = lines[0].split(",")
        if len(times) != 2:
            continue
        captions.append({
            "start_ms": time_to_ms(times[0].strip()),
            "end_ms":   time_to_ms(times[1].strip()),
            "text":     " ".join(lines[1:]).strip()
        })
    return captions

# Test it
captions = parse_sbv("v0.1_captions_en-us_sentences.sbv")
print(f"Loaded {len(captions)} captions")
print(captions[0])
```

### Cell 4 — Generate audio per caption

```python
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using: {device}")

tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

OUT_DIR = Path("chunks")
OUT_DIR.mkdir(exist_ok=True)

for i, cap in enumerate(captions):
    out_path = OUT_DIR / f"chunk_{i:04d}.wav"
    print(f"[{i+1}/{len(captions)}] {cap['text'][:60]}...")
    tts.tts_to_file(
        text=cap["text"],
        speaker_wav="voice_sample.wav",
        speed=0.92,
        language="en",
        file_path=str(out_path)
    )
```

### Cell 5 — Assemble the final track with correct timing

```python
from pydub import AudioSegment
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================
CHUNKS_DIR    = Path("chunks")
OUTPUT_WAV    = "final_dub.wav"
OUTPUT_MP3    = "final_dub.mp3"
TAIL_SILENCE  = 2000   # ms appended at the very end
MIN_GAP_MS    = 80     # minimum breathing room between consecutive lines

# ============================================================
# Build the final track — NO time-stretching, ever.
# Strategy: each chunk starts exactly at cap["start_ms"]; if it
# overflows, it eats into the silence before the next chunk.
# Only if it would collide with the NEXT chunk do we shift the
# next chunk later (creating a cascade we accept gracefully).
# ============================================================

# First pass: load all chunks and compute their natural durations
loaded = []
for i, cap in enumerate(captions):
    path = CHUNKS_DIR / f"chunk_{i:04d}.wav"
    if not path.exists():
        print(f"⚠️  missing {path.name}")
        loaded.append(None)
        continue
    loaded.append(AudioSegment.from_wav(path))

# Second pass: compute actual placement positions
placements = []          # list of (position_ms, AudioSegment)
cursor_ms  = 0           # earliest time the next chunk can start

for i, (cap, audio) in enumerate(zip(captions, loaded)):
    if audio is None:
        continue

    # Ideal start = caption's scheduled time
    # Real start  = max(ideal, cursor) → never overlap previous chunk
    start_ms = max(cap["start_ms"], cursor_ms)
    placements.append((start_ms, audio))
    cursor_ms = start_ms + len(audio) + MIN_GAP_MS

    drift = start_ms - cap["start_ms"]
    if drift > 0:
        print(f"[{i+1}] shifted +{drift}ms (audio={len(audio)}ms, "
              f"slot={cap['end_ms']-cap['start_ms']}ms)")

# Build the final track sized to whatever we actually need
total_ms = max(p[0] + len(p[1]) for p in placements) + TAIL_SILENCE
final    = AudioSegment.silent(duration=total_ms)

for pos, audio in placements:
    final = final.overlay(audio, position=pos)

final.export(OUTPUT_WAV, format="wav")
final.export(OUTPUT_MP3, format="mp3", bitrate="192k")
print(f"\n✅ Done! Total: {total_ms/1000:.1f}s → {OUTPUT_WAV}")
```

### Cell 6 — (Optional) Mux audio with your video

Replace the original audio with the dubbed track:

```bash
!ffmpeg -y -i original_video.mp4 -i final_dub.wav \
    -map 0:v -map 1:a -c:v copy -shortest dubbed_video.mp4
```

Or keep ambient/music at low volume in the background:

```bash
!ffmpeg -y -i original_video.mp4 -i final_dub.wav -filter_complex \
    "[0:a]volume=0.1[bg];[1:a]volume=1.0[dub];[bg][dub]amix=inputs=2:duration=longest[a]" \
    -map 0:v -map "[a]" -c:v copy dubbed_video_mixed.mp4
```

---

## 📋 Pipeline Summary

| Stage | Where | Tool | Output |
|---|---|---|---|
| 1. Audio extraction | local machine | `ffmpeg` | `audio_output_1.m4a` |
| 2. Voice sample | local machine | `ffmpeg` | `voice_sample.wav` |
| 3. Sentence grouping | local machine | `group_chunks_for_tts.py` | `v0.1_captions_en-us_sentences.sbv` |
| 4. Voice synthesis | Google Colab T4 GPU | Coqui XTTS v2 | `chunks/chunk_*.wav` |
| 5. Track assembly | Google Colab T4 GPU | `pydub` + `ffmpeg` | `final_dub.wav` / `.mp3` |
| 6. Video muxing | Google Colab T4 GPU | `ffmpeg` | `dubbed_video[_mixed].mp4` |

*Note: it's needed to upload the local files to Google Colab, or just upload the video and English subtiles, and run all on Google Colab.*

---

## 🛠️ Troubleshooting

- **TTS sounds too fast** → lower `speed=0.92` to `0.88` in Cell 4
- **Chunks sound choppy / cut mid-sentence** → check Phase 0 ran; verify
  input SBV doesn't already contain multi-sentence blocks
- **Final dub drifts later than the video** → expected when natural speech
  is longer than original; lower `MIN_GAP_MS` or accept the drift
- **XTTS crashes with "text too long"** → lower `XTTS_LIMIT` to 220

---

---

## 🎓 The Real Win — Knowledge Acquired

What started as *"let me add subtitles to my Pyqttyai documentation
videos"* turned into building a complete AI dubbing pipeline. The
auto-captions from YouTube were poor quality, so the rabbit hole began
— and the knowledge gained along the way became the real reward.

### Skills and concepts mastered

- **ASR (Automatic Speech Recognition) internals**
  Word-level timestamps, VAD (Voice Activity Detection), initial
  prompts for domain adaptation, language hints, model trade-offs
  (Groq cloud vs. faster_whisper local).

- **Subtitle formats and time math**
  SRT vs. SBV structure, timestamp parsing, chunk boundaries,
  millisecond-precision arithmetic for audio placement.

- **Forced alignment**
  Why YouTube's caption editor is secretly an excellent
  forced-alignment tool, and how to leverage human-in-the-loop
  checkpoints in an otherwise automated pipeline.

- **TTS (Text-to-Speech) constraints**
  Character limits per inference, sentence-level prosody for natural
  speech, voice cloning with reference samples, why sentence
  granularity beats word/phrase granularity.

- **Audio engineering**
  Overlay vs. time-stretch trade-offs, gap management between chunks,
  avoiding cascade drift, mixing dubbed track with original ambience.

- **Pipeline design**
  When to use cloud resources (Groq for ASR, Colab T4 for TTS) vs.
  local execution, where to insert human checkpoints, how to make
  each stage reusable and debuggable in isolation.

### Why this compounds

Perfectionism gets a bad rap, but in engineering it's often what
separates *"works on my machine once"* from *"works for everyone,
repeatably, with documentation"*. The time invested here pays
dividends:

1. ✅ Every future Pyqttyai video dubs in a fraction of the time
2. ✅ The pipeline is **documented** — future-me doesn't re-learn it
3. ✅ `group_chunks_for_tts.py` is reusable for any future project
4. ✅ End-to-end AI pipeline thinking is now part of the toolkit
5. ✅ Pyqttyai gets professional-quality multilingual reach 🌎

### The quiet reward

When viewers watch the next Pyqttyai video with a crisp English dub
in a cloned voice, they won't have any idea how much engineering is
behind those few minutes of audio.

But **I'll** know. And that's the perfectionist's quiet reward. 🏆

> *"Time spent learning is never time wasted — it's time invested."*
