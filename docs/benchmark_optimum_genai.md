# Benchmark Results — Whisper Turbo Backends
**Date:** 2026-05-11
**Model:** Whisper Large-v3 Turbo
**Test audio:** 30s sample (pt-BR)
**Hardware:** Intel iGPU + NVIDIA CUDA GPU

---

## 📊 Results Summary

| Backend | Load (1st time) | Load (cached) | Transcription | Speed vs real-time | Notes |
|---|---:|---:|---:|:---:|---|
| 🥇 **OpenVINO + Optimum (iGPU)** | 126.9s ⚠️ | ~9s | **2.6s** | **11.14×** | Top performance for Intel iGPU; one-time compile cost |
| 🥈 **CUDA / faster-whisper** | 1.4s | — | 2.7s | 11.07× | Excellent offline performance, fast cold start |
| 🥉 **OpenVINO Legacy** | 4.2s | — | 5.1s | 5.85× | Slower; usable as fallback |

---

## 🧠 Memory Footprint

Measured via `/proc/self/status` (Linux). **VmHWM** = peak resident set size; **RSS** = current working set.

| Backend | Peak RAM (VmHWM) | Working RAM (RSS) | Relative |
|---|---:|---:|:---:|
| 🥇 **OpenVINO-GenAI** | **1.88 GB** (1,970,432 kB) | **1.36 GB** (1,424,400 kB) | 1.0× (baseline) |
| 🥈 **CUDA / faster-whisper** | 2.24 GB (2,344,964 kB) | 1.75 GB (1,835,732 kB) | ~1.2× |
| 🥉 **OpenVINO + Transformers** | 7.17 GB (7,517,308 kB) | 4.60 GB (4,821,232 kB) | ~3.8× ⚠️ |

### Key observations
- **OpenVINO-GenAI** is the most memory-efficient backend — ideal for constrained environments or background pre-loading.
- **faster-whisper (CUDA)** sits in a healthy middle ground; most of the GPU weights live in VRAM, keeping system RAM modest.
- **OpenVINO + Transformers** consumes **~3.8× more RAM** than GenAI for the same model. The HuggingFace `transformers` wrapper keeps duplicate PyTorch + OpenVINO graphs in memory during inference.

---

## 🔍 Key Findings

### Performance
- **OpenVINO + Optimum** now **ties with CUDA** on transcription speed (~2.6–2.7s for 30s of audio).
- **OpenVINO Legacy** is roughly **2× slower** than the modern paths.

### Load Times
- ⚠️ **Optimum (Intel iGPU)** has a **~2 min cold start** due to model compilation.
- After first run, **load drops to ~9s**.
- **CUDA / faster-whisper** begins instantly (~1.4s).

### Language Detection (pt-BR)
| Backend | Confidence |
|---|---:|
| OpenVINO + Optimum | **100%** ✅ |
| CUDA (previous runs) | ~50% ⚠️ |

### ⚠️ Silent Fallback Warning
If the **turbo** model isn't properly converted, the pipeline silently falls back to **large-v3** (not turbo), reducing expected performance. Always verify the conversion artifacts.

---

## 💡 Practical Recommendations

1. **Pre-load OpenVINO + Optimum in background** at startup — hides the ~2 min compile time.
2. **Use CUDA / faster-whisper** when available for fastest offline start.
3. **Prefer OpenVINO-GenAI** when RAM is a constraint (≈1.9 GB peak vs ≈7.5 GB for the Transformers path).
4. **Avoid the OpenVINO + Transformers path in production** unless you specifically need its API — the memory cost is steep.
5. **Keep OpenVINO Legacy** only as a fallback.
6. **Validate turbo model conversion** upfront to avoid silent fallback to large-v3.

---

*Benchmark by Claudio Polegato Junior · Ribeirão Preto, BR · May 2026*
