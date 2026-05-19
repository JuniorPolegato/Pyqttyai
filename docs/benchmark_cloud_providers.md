# 🎙️ Cloud Whisper Providers — Benchmark

> **TL;DR**: Groq is the clear winner for the Pyqttyai use case (short voice commands).
> Fireworks is a solid backup. Gemini is too slow. OpenAI requires a paid plan.

## 🧪 Test Setup

- **Audio file**: `audio_com_ruído.wav` — 46.1 seconds of Portuguese speech with hand noise
- **Test script**: [`test_openai.py`](../tests/test_openai.py)
- **Loops**: 5 iterations per provider
- **Network**: Residential broadband, Brazil (BR-SP)
- **Date**: May 2026

The script uses a single OpenAI-compatible adapter (`OpenAICompatibleEngine`) for all
four providers, since they share the same SDK shape.

## 📋 Providers Tested

| Provider | Endpoint | Model | Auth |
|---|---|---|---|
| **Groq** | `api.groq.com/openai/v1` | `whisper-large-v3-turbo` | `GROQ_API_KEY` |
| **OpenAI** | `api.openai.com/v1` | `whisper-1` | `OPENAI_API_KEY` |
| **Fireworks** | `audio-turbo.api.fireworks.ai/v1` | `whisper-v3-turbo` | `FIREWORKS_API_KEY` |
| **Gemini** | `generativelanguage.googleapis.com/v1beta/openai/` | `gemini-3.1-flash-lite-preview` | `GOOGLE_API_KEY` |

## 📊 Results — Transcription Time (seconds)

| Loop | Groq ⚡ | OpenAI ❌ | Fireworks 🔥 | Gemini 🐌 |
|---:|---:|---:|---:|---:|
| 1 | 0.86 | (quota) | 1.53 | 50.79 |
| 2 | 0.61 | (quota) | 1.43 | 20.17 |
| 3 | 0.82 | (quota) | 1.13 | 17.71 |
| 4 | 0.61 | (quota) | 1.43 | 19.55 |
| 5 | 0.71 | (quota) | 2.45 | 23.75 |
| **Avg** | **0.72** | — | **1.59** | **26.39** |
| **Min** | **0.61** | — | **1.13** | **17.71** |

> 💡 Audio duration was **46.1 s**. Realtime factor (RTF) = audio / transcription time.

| Provider | Avg RTF | Verdict |
|---|---:|---|
| **Groq** | **64×** realtime | 🏆 winner — sub-second for 46s clip |
| **Fireworks** | 29× realtime | ✅ solid backup |
| **Gemini** | 1.7× realtime | ❌ too slow for live commands |
| **OpenAI** | n/a | ❌ no free tier (insufficient_quota) |

## 🎯 Transcription Quality

All Whisper-based providers produced near-identical text. The key difference:

### Groq — adds Whisper's classic silence hallucination
> _"…só o ruído da mão **Obrigado**."_ ⚠️

The trailing **"Obrigado"** appears on every loop — a known artifact of Whisper
when audio ends with silence/noise. **Mitigation**: VAD pre-trim (already implemented
in `vad_preprocessor.py`) cuts the trailing silence before upload.

### Fireworks — clean output, drops trailing noise naturally
> _"…agora eu vou colocar só o ruido da mão"_ ✅

Slightly different spelling (`ruido` vs `ruído`), no hallucination.

### Gemini — most "polished", with punctuation and capitalization
> _"Falando um pouco e vou esperar alguns segundos, uns 5 segundos para ver se ele corta."_ 🎨

Better formatting, but **20–50 s latency** kills it for live use.

### OpenAI
Could not test — every call returned `429 insufficient_quota`. The OpenAI Whisper
API has **no free tier**; a paid billing plan is required.

## 🔑 Free-Tier Comparison

| Provider | Free tier? | Daily limit | Notes |
|---|---|---|---|
| **Groq** | ✅ Yes | 28,800 audio sec/day per model | Best free offer |
| **Fireworks** | ✅ Yes (trial credit) | Varies by signup | Good fallback |
| **Gemini** | ✅ Yes | Generous on Flash models | Latency unsuitable |
| **OpenAI** | ❌ No | Pay-per-use only | $0.006 / minute |

> 🎁 **Pro tip**: Groq limits are **per-model**. Configuring both `whisper-large-v3-turbo`
> and `whisper-large-v3` as switchable presets effectively **doubles** daily capacity.

## 🚦 Recommendation

For Pyqttyai voice commands:

1. 🥇 **Default**: Groq + `whisper-large-v3-turbo` — fastest, best free tier
2. 🥇 **Fallback1**: Groq + `whisper-large-v3` — fastest, best free tier
3. 🥈 **Fallback2**: Fireworks `whisper-v3-turbo` — when Groq rate-limits - payed after the bonus 💰
3. 💻 **Offline / privacy / Nvidia**: Local `faster-whisper` with `large-v3-turbo` model
3. 💻 **Offline / privacy / CPU**: Local `faster-whisper` with `base` or `small`, maybe `large-v3-turbo` model
4. ❌ **Avoid**: Gemini for live commands (acceptable for batch transcription)
5. 💰 **Avoid**: OpenAI Whisper unless billing is set up

## 🛠️ Reproducing the Benchmark

```bash
# 1. Set API keys in .env
echo 'GROQ_API_KEY=gsk_…'        >> .env
echo 'OPENAI_API_KEY=sk-…'       >> .env   # optional
echo 'FIREWORKS_API_KEY=fw_…'    >> .env   # optional
echo 'GOOGLE_API_KEY=AIza…'      >> .env   # optional

# 2. Place a test WAV at /tmp/audio_com_ruído.wav
#    (16 kHz mono, 30–60 s of speech recommended)

# 3. Run
pip install openai
python tests/test_openai.py
```
[result](../tests/result_cloud.txt)

---

*Benchmark by Claudio Polegato Junior · Ribeirão Preto, BR · May 2026*
