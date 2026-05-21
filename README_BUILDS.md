# 📦 Pyqttyai — Which Build Should I Download?

Pyqttyai ships in **8 flavors** so you only download what you'll actually use.
Each build is a **single `.exe`** — no installer, no extraction headaches. 🚀

> 🛠️ Building from source? See [`docs/packing.md`](docs/packing.md) for the
> PyInstaller dispatcher (`packman.py`) that produces all flavors from a single
> template.

---

## 🎯 Quick Decision Tree

```
Which transcription backend will you use?
│
├─ ☁️  Cloud only (Groq is free + blazing fast!)
│     └──► 3️⃣ cloud           — 91 MB    ⭐ recommended for most users
│
├─ 💻 Local CPU/CUDA (faster-whisper)
│     ├─ Offline-only?     ──► 1️⃣ fwhisper         — 142 MB
│     └─ + cloud fallback? ──► 5️⃣ fwhisper-cloud   — 148 MB
│
├─ 🧊 Intel iGPU / Arc / NPU (OpenVINO-GenAI)
│     ├─ Offline-only?     ──► 2️⃣ ovgenai          — 166 MB
│     └─ + cloud fallback? ──► 7️⃣ ovgenai-cloud    — 173 MB
│
├─ 🦾 Everything local (CUDA + OpenVINO)
│     ├─ Offline-only?     ──► 4️⃣ fwhisper-ovgenai       — 215 MB
│     └─ + cloud fallback? ──► 6️⃣ fwhisper-ovgenai-cloud — 222 MB ⭐ power users
│
└─ 🪶 None — I just want the editor / NLP features
      └──► 0️⃣ do-not-tell-me  — 59 MB
```

---

## 📊 Full Comparison Table

| # | Build | Size | 💻 Local Whisper<br>(CPU/CUDA) | 🧊 OpenVINO<br>(Intel GPU/NPU) | ☁️ Cloud STT<br>(Groq/OpenAI) | 🛡️ Silero VAD |
|:-:|---|---:|:-:|:-:|:-:|:-:|
| 0 | **do-not-tell-me** | 59 MB | ❌ | ❌ | ❌ | ❌ |
| 3 | **cloud** ⭐ | 91 MB | ❌ | ❌ | ✅ | ✅ |
| 1 | **fwhisper** | 142 MB | ✅ | ❌ | ❌ | ✅ |
| 5 | **fwhisper-cloud** | 148 MB | ✅ | ❌ | ✅ | ✅ |
| 2 | **ovgenai** | 166 MB | ❌ | ✅ | ❌ | ✅ |
| 7 | **ovgenai-cloud** | 173 MB | ❌ | ✅ | ✅ | ✅ |
| 4 | **fwhisper-ovgenai** | 215 MB | ✅ | ✅ | ❌ | ✅ |
| 6 | **fwhisper-ovgenai-cloud** ⭐ | 222 MB | ✅ | ✅ | ✅ | ✅ |

> 🛡️ **Silero VAD** (1.2 MB ONNX model) is bundled in every build except
> `do-not-tell-me`. It eliminates Whisper hallucinations on silence/noise
> (no more random "Obrigado" or "Thanks for watching!" in your transcripts).

---

## 📥 Download Links

Grab the latest release from the
[**Releases page**](https://github.com/YOUR_USER/pyqttyai/releases/latest):

| Tier | File | Best for |
|---|---|---|
| ⭐ **Recommended** | `Pyqttyai-v0.5.7-cloud-win64.zip` | Most users (free Groq tier is excellent) |
| 🪶 **Tiny** | `Pyqttyai-v0.5.7-do-not-tell-me-win64.zip` | Editor + NLP only, no transcription |
| 💻 **Local CPU/CUDA** | `Pyqttyai-v0.5.7-fwhisper-cloud-win64.zip` | Laptops with NVIDIA GPU |
| 🧊 **Intel hardware** | `Pyqttyai-v0.5.7-ovgenai-cloud-win64.zip` | Intel Arc / iGPU / Meteor Lake NPU |
| 🦾 **Power users** | `Pyqttyai-v0.5.7-fwhisper-ovgenai-cloud-win64.zip` | Everything — choose your backend at runtime |

> 💡 The other variants (`fwhisper`, `ovgenai`, `fwhisper-ovgenai`) are
> "offline-only" twins of the cloud-enabled ones above. Pick them if you
> want the smallest possible build for a specific hardware target and
> **never** want to send audio to a cloud API.

---

## 🚀 Installation

1. **Download** the `.zip` matching your needs
2. **Extract** it anywhere (e.g., `C:\Tools\Pyqttyai\`)
3. **Run** `Pyqttyai_<flavor>.exe` — no installer needed! 🎉

> 💡 **Pro tip:** Pin the `.exe` to your taskbar for one-click access.

---

## 🔑 Setting Up Cloud Keys (any build with `cloud` in the name)

### 🆓 Groq (recommended — free + blazing fast)

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. In Pyqttyai → **Settings → STT → Groq → API Key**

### 💳 OpenAI (paid)

1. Get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. In Pyqttyai → **Settings → STT → OpenAI → API Key**

---

## 🧊 OpenVINO Setup (any build with `ovgenai` in the name)

OpenVINO-GenAI supports **Intel hardware acceleration** out of the box:

| Hardware | Device tag |
|---|---|
| Intel CPU (any) | `CPU` |
| Intel UHD / Iris / Arc GPU | `GPU` |
| Meteor Lake / Lunar Lake NPU | `NPU` |

In Pyqttyai → **Settings → STT → OpenVINO → Device**, pick the one matching
your hardware.

> ⚠️ For GPU/NPU, make sure you have the latest
> [**Intel Graphics Driver**](https://www.intel.com/content/www/us/en/download-center/home.html)
> installed (version `31.0.101.5xxx` or newer).

---

## ❓ FAQ

### 🤔 I picked the wrong build — do I have to reinstall?

No reinstall needed — just download a different `.exe`. Your settings live
in `%APPDATA%\Pyqttyai\` and survive across builds.

### 💽 Why are there so many flavors?

Because **one size doesn't fit all**:

- A Groq-only user shouldn't download 220 MB of OpenVINO they'll never use
- An Intel Arc owner shouldn't download `faster-whisper` if they prefer NPU
- A privacy-focused user shouldn't have cloud SDKs sitting in their binary

The matrix gives you exactly what you need — nothing more.

### 🛡️ Is my audio sent to the cloud?

- **Builds without `cloud` in the name:** **Never.** 100% local.
- **Builds with `cloud` in the name:** **Only** when you explicitly select
  Groq or OpenAI as the active backend. Local backends (faster-whisper,
  OpenVINO) never transmit audio.

### 🐧 Linux / macOS builds?

Not officially distributed yet — but you can build from source with
`packman.py`. See [`docs/packing.md`](docs/packing.md).

### 🔄 Auto-updates?

I plan to Pyqttyai checks GitHub Releases on startup and notifies you when a new
version is available. The update itself is manual (re-download the `.exe`).

### 🪶 What is `do-not-tell-me`?

It's the **minimal build** — no transcription engines at all. Useful if
you only need the script editor, NLP rules, and other non-STT features.
Or if you're a developer testing the UI shell.

---

## 🆘 Troubleshooting

| Problem | Fix |
|---|---|
| 🚫 `VCRUNTIME140.dll missing` | Install [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) |
| 🐌 First transcription is slow | Whisper models download on first use (~75 MB – 3 GB depending on size) |
| 🔇 "No microphone detected" | Check Windows → Settings → Privacy → Microphone |
| 🧊 OpenVINO GPU not listed | Update Intel Graphics Driver to `31.0.101.5xxx` or newer |
| 🛡️ Antivirus flags the `.exe` | Common false positive with PyInstaller. Add an exception for the install folder. |
| ⏱️ Slow startup (first launch) | The `.exe` self-extracts to `%TEMP%`. Subsequent launches are cached & fast. |

For other issues,
[open a GitHub Issue](https://github.com/YOUR_USER/pyqttyai/issues) with
the contents of `%APPDATA%\Pyqttyai\logs\pyqttyai.log`.

---

## 🔗 Links

- 📘 [Build from source (`docs/packing.md`)](docs/packing.md)
- 📜 [Changelog (`CHANGELOG.md`)](CHANGELOG.md)
- 🐛 [Report a bug](https://github.com/YOUR_USER/pyqttyai/issues)
- 💬 [Discussions](https://github.com/YOUR_USER/pyqttyai/discussions)
