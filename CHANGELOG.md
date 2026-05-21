# 📜 Changelog

All notable changes to Pyqttyai are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.7] — 2026-05-21

### 📦 Build System Overhaul
- 🎯 New `packman.py` dispatcher replaces hand-written `.spec` files
- 🧩 Feature-flag matrix produces **8 shippable Windows builds** from a
  single template (`do-not-tell-me`, `cloud`, `fwhisper`, `fwhisper-cloud`,
  `ovgenai`, `ovgenai-cloud`, `fwhisper-ovgenai`, `fwhisper-ovgenai-cloud`)
- 📉 Significant size reductions vs. v0.5.6:
  - Cloud-only build: **230 MB → 91 MB** (60% smaller)
  - Faster-whisper + cloud: **~250 MB → 148 MB**
  - All-local power user build: 222 MB (was not separately available)
- 🛡️ **Silero VAD bundled in all transcription-capable builds** (1.2 MB
  ONNX) — eliminates hallucinations on silence/noise across every backend
- 🔇 Runtime hook silences `tqdm`, Hugging Face telemetry, and symlink
  warnings in windowed mode

### 🧰 Build Internals
- 🔧 Auto-generated `.spec` files written to `packing/generated/`
- 🚫 Smart excludes prevent accidental transitive bundling (e.g., excludes
  `torch` from any non-OpenVINO-Optimum profile)
- 🐉 Selective UPX with explicit exclusions for native DLLs
  (`onnxruntime*`, `openvino*`, `torch*`, `vcruntime140`, `python3*`)

### 📚 Documentation
- ✏️ Rewrote `README_BUILDS.md` around the 8-flavor matrix
- ✏️ Rewrote `docs/packing.md` to document `packman.py`
- 📐 Added measured sizes from real v0.5.7 builds (no more estimates)

## [0.5.6] — 2026-05-19

### ✨ Added — Voice + NLP Intelligence Layer
- 🎙️ Whisper-based voice input (`Ctrl+Space`) with live VU meter
- 🧠 Deterministic NLP rules engine (regex + fragments + replacements)
- 📋 Visual NLP Rules Editor (`Ctrl+Shift+R`)
- 🧪 Whisper Playground with backend benchmarking
- 🌍 Multilingual support (PT-BR, EN, ES + 90 more)
- ✂️ Silero VAD pre-trim (eliminates "Obrigado" hallucinations)
- 🌐 Cloud backends: Groq, Fireworks, OpenAI, Gemini
- 🎮 Local backends: CUDA (faster-whisper), OpenVINO-GenAI, CPU
- 📥 In-app model downloads with progress
- 🔑 Secure API-key storage
- 🎯 Persistent backend status indicator
- 📐 Configurable script-editor indentation
- 🔢 IPv4/IPv6/MAC separator normalization shortcuts
- 🔎 VS Code-style Find & Replace bar with regex
- 🎯 `Ctrl+Shift+A` — apply NLP rules to current line

### 📚 Documentation
- Six benchmark studies in `docs/benchmark_*.md`
- v0.5 companion docs: editor, Whisper playground, NLP rules

## [0.4.0] — Send All & Send Each
## [0.3.0] — Windows polish & protocol handler
## [0.2.0] — Image-based device mapping
## [0.1.0] — Initial release
