import os
from groq import Groq

# Initialize the Groq client (Make sure your GROQ_API_KEY environment variable is set)
client = Groq()

AUDIO_FILE = "output_audio.mp3"
SRT_FILE = "output_subtitles.srt"
MAX_CHARS = 42

print("Sending audio to Groq Whisper API...")

# 1. Request word-level timestamps from Groq
transcription = client.audio.transcriptions.create(
    file=(AUDIO_FILE, open(AUDIO_FILE, "rb").read()),
    model="whisper-large-v3-turbo",
    response_format="verbose_json",
    timestamp_granularities=["word"]
)

def format_srt_time(seconds):
    """Converts seconds into standard SRT time format (HH:MM:SS,mmm)"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def generate_srt(words, max_chars=42):
    """Groups words into sentences and wraps lines to max_chars."""
    chunks = []
    current_chunk = []

    # Group words into sentence blocks based on punctuation
    for w in words:
        current_chunk.append(w)
        if any(char in w['word'] for char in ['.', '!', '?']):
            chunks.append(current_chunk)
            current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    srt_entries = []
    entry_index = 1

    for chunk in chunks:
        if not chunk:
            continue

        # Get start of first word and end of last word in the sentence
        start_time = format_srt_time(chunk[0]['start'])
        end_time = format_srt_time(chunk[-1]['end'])

        # Build lines ensuring none exceed max_chars
        lines = []
        current_line = []
        current_len = 0

        for w in chunk:
            word_text = w['word'].strip()
            if not word_text:
                continue

            # +1 accounts for the space before the word
            word_len = len(word_text) + (1 if current_line else 0)

            if current_len + word_len > max_chars and current_line:
                lines.append(" ".join(current_line))
                current_line = [word_text]
                current_len = len(word_text)
            else:
                current_line.append(word_text)
                current_len += word_len

        if current_line:
            lines.append(" ".join(current_line))

        block_text = "\n".join(lines)

        # Append standard SRT block format
        srt_entries.append(f"{entry_index}\n{start_time} --> {end_time}\n{block_text}\n")
        entry_index += 1

    return "\n".join(srt_entries)

print("Processing timestamps and generating SRT...")
# transcription.words returns a list of dictionaries containing 'word', 'start', and 'end'
srt_content = generate_srt(transcription.words, max_chars=MAX_CHARS)

# Save the final SRT file
with open(SRT_FILE, "w", encoding="utf-8") as f:
    f.write(srt_content)

print(f"Success! Your file has been saved to: {SRT_FILE}")
