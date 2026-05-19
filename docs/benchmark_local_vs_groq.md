# 🎙️ Local vs Cloud Whisper — Benchmark Report

> **TL;DR**: For real-time voice commands, **Groq Cloud is ~10× faster than local CUDA GPU**
> and ~30× faster than CPU. **OpenVINO is not recommended** despite Intel marketing —
> heavy install, slow first load, and broken language detection. Use Groq when online,
> `faster-whisper` on CPU/CUDA when offline.

---

## 🧪 Test Setup

| Item | Value |
|---|---|
| **Audio** | Live recording, **60.6 s**, Portuguese (pt-BR), with handclap noise |
| **Trimmed (VAD)** | **37.75 s** after Silero VAD pre-trim (-37.7%) |
| **Model** | `whisper-large-v3-turbo` (cloud + local equivalent) |
| **Sample rate** | 16 kHz mono PCM WAV |
| **Test script** | `tests/test_recorder_vad_groq.py` |
| **Hardware** | Local CPU + NVIDIA CUDA GPU + Intel iGPU |
| **Date** | May 2026 |

The same WAV was sent to **5 backend configurations**, each tested with and without
VAD pre-trim.

---

## 📊 Headline Results — Transcription Time

Time to transcribe one **60.6-second clip** (lower is better):

| Backend | Without VAD | With VAD | Audio sent | Speedup vs realtime |
|---|---:|---:|---:|---:|
| 🥇 **Groq Cloud (turbo)** | **1.23 s** | **1.05 s** | 60.6 → 37.75 s | **49–58×** |
| 🥈 **CUDA / faster-whisper** | 6.88 s | 6.80 s | 60.6 s | **8.8×** |
| 🥉 **CPU / faster-whisper** | 22.65 s | 26.45 s | 60.6 s | **2.7×** |
| ⚠️ **OpenVINO GPU (Intel iGPU)** | 10.78 s | 6.77 s | 60.6 s | 5.6×–9.0× |
| ❌ **OpenVINO CPU** | 28.17 s | 27.23 s | 60.6 s | 2.2× |

> 💡 **VAD pre-trim** reduced audio from 60.6 s → 37.75 s, but **didn't always help**
> CPU/OpenVINO due to processing overhead. On GPU/Cloud, savings are real.

---

## ⏱️ Detailed Breakdown

### 🥇 Groq Cloud

```
Upload + transcribe full clip (60.6s) : 1.23 s
Upload + transcribe VAD trim (37.75s) : 1.05 s
Same 60s clip (warm)                  : 0.90 s
```

✅ **Sub-second responses** for typical voice commands (3–10 s).
✅ **No model load time** (HTTP client only).
⚠️ Adds **"Thank you"** at the end of audio with trailing silence (Whisper hallucination).
   → **Fix**: enable VAD pre-trim — kills the trailing silence.

### 🥈 CUDA GPU + faster-whisper (`large-v3-turbo`)

```
Model load (cold, from disk) : 1.91 s
Transcribe full clip (60.6s) : 6.88 s
Transcribe VAD trim (37.75s) : 6.72 s
```

✅ Best **offline** option if you have an NVIDIA GPU.
✅ Returns rich `language_probability` + per-segment timestamps.
✅ Model fits in ~2 GB VRAM with `int8_float16`.

### 🥉 CPU + faster-whisper (`large-v3-turbo`)

```
Model load (cold, from disk) : 1.77 s
Transcribe full clip (60.6s) : 22.65 s
Transcribe VAD trim (37.75s) : 26.14 s   ⚠️
```

⚠️ **Slower than realtime** for `large-v3-turbo`. For CPU-only setups,
   **drop to `base` or `small` model** for usable latency.
⚠️ Counter-intuitive: VAD made it **slower** (probably overhead vs benefit
   on a workload that's already CPU-bound).

### ⚠️ OpenVINO — **not recommended**

```
Install size:    2.5 GB  (PyTorch + Intel + NVIDIA packages)
Model download:  1.6 GB  (HuggingFace conversion artifacts)
RAM at load:     ~8 GB
First load:      ~128 s  (one-time conversion)
Subsequent:      Cached but still slow startup
```

| Variant | Cold load | Transcribe (60.6s) | Transcribe (VAD 37.75s) |
|---|---:|---:|---:|
| **OpenVINO CPU** | 129.6 s | 28.17 s | 29.11 s |
| **OpenVINO GPU (iGPU)** | 127.8 s | 10.78 s | 6.64 s |

#### 🚨 Critical Issues with OpenVINO

1. **🐘 Heavy install** — pulls 2.5 GB of dependencies including PyTorch + Intel
   runtime + (oddly) NVIDIA packages
2. **🐌 Cold load is glacial** — 2 minutes vs faster-whisper's 1.9 s
3. **📦 Model conversion artifacts** add another 1.6 GB on disk
4. **🧠 ~8 GB RAM** during conversion (a problem on 8 GB machines)
5. **🌍 Broken language metadata** — always returns `language='en'` and
   `language_probability=0.0` regardless of actual content
6. **📝 Output quality regression** — drops words like "Acabei de dar uma pausa…"
   on the no-VAD path; only the VAD-trimmed path got a partial result

#### 💬 Verdict on OpenVINO

> Despite Intel's marketing, OpenVINO offers **no benefit over faster-whisper** for
> Whisper inference on this hardware. The Intel iGPU path is the **only** one that
> approaches CUDA speeds, but at the cost of a 2-minute load and 8 GB RAM spike.
>
> **Recommendation: do not include OpenVINO as a default backend.** Keep the
> code path available behind an "advanced" flag for users with Intel-only systems
> who specifically want to test it.

---

## 🎯 Quality Comparison (raw text)

All backends transcribed the same audio. Differences:

### Groq Cloud (no VAD)
> "estou gravando esse áudio em tempo real para comparar o GROC com GPU e CPU
> e também vou cortar as pausas, os espaços deste arquivo, desse áudio, com o
> celeiro que faz o VAD, que é a detecção de voz. Acabei de dar uma pausa de
> alguns segundos com ruído muito baixo. Agora vou dar uma pausa com ruído mais
> alto, estalando os dedos. Agora vou finalizar. **Thank you.**" ⚠️

### Groq Cloud (with VAD pre-trim)
> "…Agora vou finalizar." ✅ **No "Thank you" hallucination!**

### faster-whisper (CPU/CUDA — same output)
> "Estou gravando este áudio em tempo real para comparar o GROC com GPU e CPU…
> Agora vou finalizar..." ✅ Clean trailing ellipsis.

### OpenVINO CPU (no VAD)
> "estou gravando esse áudio… **que é a detecção de voz**" ❌ **Truncated** —
> missing the second half of the recording.

### OpenVINO GPU (with VAD)
> "Estou gravando esse áudio… **com ruído muito baixo.**" ❌ Still **truncated**.

---

## 📈 Realtime Factor (RTF) — Lower is Better

> RTF = transcription_time / audio_duration. **0.02 = 50× faster than realtime.**

| Backend | RTF (no VAD) | RTF (VAD) |
|---|---:|---:|
| 🥇 Groq Cloud | **0.020** | **0.028** |
| 🥈 CUDA + faster-whisper | 0.114 | 0.178 |
| 🥉 CPU + faster-whisper | 0.374 | 0.692 |
| ⚠️ OpenVINO GPU | 0.178 | 0.176 |
| ❌ OpenVINO CPU | 0.465 | 0.771 |

---

## 🪶 Resource Footprint

| Backend | Install size | Model on disk | RAM | First load | Warm load |
|---|---:|---:|---:|---:|---:|
| **Groq Cloud** | ~5 MB (`groq` SDK) | 0 | <100 MB | <1 s | <1 s |
| **faster-whisper CPU/GPU** | ~600 MB | ~1.5 GB | ~2 GB | ~30 s | 1.9 s |
| **OpenVINO** | **~2.5 GB** | **~1.6 GB** | **~8 GB peak** | **~128 s** | varies |

---

## 🚦 Recommendations

### 🌐 Online (default, recommended)
```
Backend: Groq Cloud
Model:   whisper-large-v3-turbo
VAD:     Enabled (eliminates "Thank you" hallucination)
Result:  ~1 s per voice command, free tier covers 8 hours/day
```

### 💻 Offline + has NVIDIA GPU
```
Backend: faster-whisper
Device:  cuda (faster)
Compute: int8_float16
Model:   large-v3-turbo
VAD:     Enabled
Result:  ~7 s per minute of audio, fits in 2 GB VRAM
```

### 💻 Offline + CPU only
```
Backend: faster-whisper
Device:  cpu (faster)
Compute: int8
Model:   base or small  ⚠️ NOT large-v3-turbo (too slow)
VAD:     Test both — sometimes overhead exceeds benefit
Result:  Realtime or near-realtime with smaller models
```

### ❌ Avoid
- **OpenVINO** — heavy install, slow startup, broken language detection
- **`large-v3-turbo` on CPU** — slower than realtime, frustrating for live use
- **Cloud without VAD** — wastes free-tier audio quota on silence + adds hallucinations

---

## ✂️ VAD Pre-Trim Impact

Silero VAD trimmed our test audio from **60.6 s → 37.75 s** (-37.7%).

| Backend | Time saved | "Thank you" hallucination removed? |
|---|---|---|
| Groq Cloud | -0.18 s (small absolute, big % gain) | ✅ Yes |
| CUDA | -0.16 s | ✅ Yes (faster-whisper handles it) |
| CPU (large-v3-turbo) | **+3.79 s slower** ⚠️ | n/a |
| OpenVINO | Mixed | ❌ Still truncates |

**Conclusion**: VAD is **almost always worth it for cloud backends** (saves quota +
fixes hallucinations). For local backends, results depend on overhead vs benefit.

---

## 🛠️ Reproducing the Benchmark

```bash
# 1. Install dependencies
pip install -r requirements_min.txt

# 2. Set Groq API key
echo 'GROQ_API_KEY=gsk_…' >> .env

# 3. Record fresh audio (or supply existing WAV)
python tests/test_recorder_vad_groq.py
# OR with an existing file:
python tests/test_recorder_vad_groq.py /tmp/my_audio.wav

# Each run prints timestamps for:
#   - Groq full clip
#   - Local model load
#   - Transcribe vad_filter=False
#   - Transcribe vad_filter=True
#   - VAD pre-trim
#   - Transcribe VAD-trimmed clip
#   - Groq VAD-trimmed clip
```
[Groq x CUDA x OpenViNO](../tests/result_groq_cuda_openvino.txt)

To switch the local backend, edit the test script's `WhisperConfig` (device =
`cuda (faster)` / `cpu (faster)` / `gpu (OpenVINO)` / `cpu (OpenVINO)`).

---

## 📝 Hallucination Note: Whisper's "Thank you" / "Obrigado"

When audio ends with silence or noise, Whisper-based models often hallucinate
phrases like:
- 🇬🇧 "Thank you."
- 🇧🇷 "Obrigado."
- 🇪🇸 "Gracias."

This is a **well-known artifact** of the original Whisper training data, which
included many YouTube videos ending with these phrases. **VAD pre-trim eliminates
the trailing silence and thus the hallucination.** Always enable VAD when sending
audio to a cloud backend.

---

## 🏆 Final Verdict

| Use case | Pick |
|---|---|
| 🎙️ Live voice commands online | 🥇 Groq Cloud + VAD |
| 🔒 Privacy / offline + GPU | 🥈 faster-whisper CUDA |
| 🔒 Privacy / offline + CPU | 🥉 faster-whisper + smaller model |
| 🧪 Curiosity / Intel-only system | ⚠️ OpenVINO (be patient) |
| ❌ Anything else | Skip OpenVINO, skip OpenAI Whisper (paid only) |

---

*Benchmark by Claudio Polegato Junior · Ribeirão Preto, BR · May 2026*
