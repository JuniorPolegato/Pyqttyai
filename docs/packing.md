# 📦 Pyqttyai — Packaging Guide (Windows)

Pyqttyai uses a **single dispatcher script** (`packing/packman.py`) that
generates PyInstaller `.spec` files from a feature-flag matrix. This replaces
the old "three hand-written specs" approach with a clean, scalable system.

---

## 🎯 The Big Picture

```
┌──────────────────┐    ┌─────────────────────┐    ┌──────────────┐
│  packman.py      │───►│  generated/*.spec   │───►│  dist/*.exe  │
│  (dispatcher)    │    │  (auto-generated)   │    │  (final)     │
└──────────────────┘    └─────────────────────┘    └──────────────┘
        ▲
        │
   ┌────┴─────┐
   │ Profile  │  ← you pick one of 11 feature combinations
   │  0 — 10  │
   └──────────┘
```

---

## 🎚️ Feature Flags

Each profile toggles four independent features:

| Flag | What it bundles | Adds (approx) |
|---|---|---:|
| `fwhisper` | `faster-whisper`, `ctranslate2`, `tokenizers` | ~85 MB |
| `ovgenai` | `openvino`, `openvino_genai`, `openvino_tokenizers` | ~110 MB |
| `cloud` | `groq`, `openai` (+ `httpx`, `pydantic` stack) | ~30 MB |
| `ovoptimum` | `optimum`, `transformers`, `torch`, `accelerate` | ~2.8 GB 🐘 |

Plus a fifth (`extras`: `sentencepiece`, `accelerate`, `datasets`) only used
in the `full` profile.

> 🛡️ **Silero VAD** (1.2 MB) is auto-bundled whenever **any** flag is enabled.
> It runs through `onnxruntime` and prevents Whisper from hallucinating
> "thanks for watching" on silent segments.

---

## 📋 Profile Matrix

| # | Key | FW | OV-Gen | Cloud | OV-Opt | Real Size |
|:-:|---|:-:|:-:|:-:|:-:|---:|
| 0 | `do-not-tell-me` | ❌ | ❌ | ❌ | ❌ | **59 MB** |
| 1 | `fwhisper` | ✅ | ❌ | ❌ | ❌ | **142 MB** |
| 2 | `ovgenai` | ❌ | ✅ | ❌ | ❌ | **166 MB** |
| 3 | `cloud` | ❌ | ❌ | ✅ | ❌ | **91 MB** |
| 4 | `fwhisper-ovgenai` | ✅ | ✅ | ❌ | ❌ | **215 MB** |
| 5 | `fwhisper-cloud` | ✅ | ❌ | ✅ | ❌ | **148 MB** |
| 6 | `fwhisper-ovgenai-cloud` | ✅ | ✅ | ✅ | ❌ | **222 MB** |
| 7 | `ovgenai-cloud` | ❌ | ✅ | ✅ | ❌ | **173 MB** |
| 8 | `cloud-ovfull` | ❌ | ✅ | ✅ | ✅ | ~3 GB 🐘 |
| 9 | `fwhisper-cloud-ovfull` | ✅ | ✅ | ✅ | ✅ | ~3.2 GB 🐘 |
| 10 | `full` | ✅ | ✅ | ✅ | ✅+ | ~3.3 GB 🐘 |

> 💡 **Sizes 0–7 are measured from actual v0.5.7 builds.** Profiles 8–10 are
> available for development but **not shipped** in official releases (too
> large for the marginal value they add over `ovgenai`).

---

## 🚀 Quick Start

### 1. Prerequisites

```powershell
# Python 3.10+ recommended
python --version

# Install PyInstaller + your runtime dependencies (requirements_win.txt for Windows)
pip install pyinstaller
pip install -r requirements_win.txt
```

### 2. Verify the Silero VAD asset exists

```powershell
Test-Path pyqttyai\audio\assets\silero_vad.onnx
# Must return: True
```

If missing, downloads of every non-trivial profile will fail, so try:

```powershell
cp pyqttyai\audio\assets\silero_vad_v6_fw.onnx pyqttyai\audio\assets\silero_vad.onnx
```

### 3. Build a single profile

```powershell
# By number
python packing\packman.py 3

# Or by name (same result)
python packing\packman.py cloud
```

The dispatcher will:

1. 📝 Render the `.spec` to `packing/generated/Pyqttyai_<profile>.spec`
2. 🚀 Invoke `pyinstaller` with `--clean --noconfirm`
3. ✅ Drop the binary at `dist/Pyqttyai_<profile>.exe`

### 4. Build everything at once

```powershell
# Builds the shippable tiers (0–7), in order of increasing size
foreach ($p in 0, 3, 1, 5, 2, 7, 4, 6) {
    Write-Host "`n🚀 Building profile $p..." -ForegroundColor Cyan
    python packing\packman.py $p
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Profile $p FAILED — stopping." -ForegroundColor Red
        break
    }
}
```

---

## 🎛️ CLI Reference

```
python packing\packman.py <profile> [--no-build] [--no-clean]
```

| Argument | Description |
|---|---|
| `profile` | Profile number (`0`–`10`) or name (e.g., `cloud`) |
| `--no-build` | Generate the `.spec` only, skip PyInstaller |
| `--no-clean` | Don't pass `--clean` to PyInstaller (faster rebuilds) |

---

## 🛠️ How the Spec Template Works

`packman.py` contains a single `SPEC_TEMPLATE` string with conditional
`if {flag}:` blocks. When you pick a profile, the dispatcher substitutes
the booleans and writes a self-contained `.spec` file.

Key design choices:

- 🧮 **`_merge(pkg)` helper** — wraps `collect_all()` to aggregate datas,
  binaries, and hidden imports for any package in one call.
- 🚫 **Smart excludes** — when `fwhisper` is off, we exclude `ctranslate2`,
  `tokenizers`, etc. to prevent accidental bundling via transitive deps.
- 🛡️ **VAD asset is conditional** — only bundled when at least one engine
  is enabled (the `do-not-tell-me` profile skips it entirely).
- 🔇 **Runtime hook** (`pyqttyai_runtime_hook.py`) — silences `tqdm`,
  Hugging Face telemetry, and Windows symlink warnings; also guards
  against `None` stdout/stderr in `--windowed` mode.

---

## ⚠️ Critical Gotchas

### 1. 🐉 UPX is enabled but **selectively excluded**

The current spec uses `upx=True` with explicit exclusions for known-bad DLLs:

```python
upx_exclude=[
    'vcruntime140.dll', 'python3*.dll',
    'onnxruntime*.dll', 'onnxruntime_providers_*.dll',
    'openvino*.dll', 'torch*.dll',
],
```

If you see **silent crashes on startup**, try setting `upx=False` in the
template to confirm UPX isn't the culprit.

### 2. 🛡️ Antivirus false positives

Windows Defender frequently flags PyInstaller binaries. Either:

- Add `dist\` to Defender exclusions **before** building
- Or sign the binary with a code-signing certificate (recommended for
  public releases)

### 3. 📥 Don't bundle Whisper model weights

Pyqttyai downloads them on first use (75 MB – 3 GB depending on size).
Bundling them would balloon every binary needlessly.

### 4. 🧪 Test on a clean Windows VM

System-wide installs (CUDA toolkit, Intel oneAPI, etc.) leak into
PyInstaller bundles silently. A clean VM catches "works on my machine"
bugs early.

### 5. 🐛 Debugging a broken build

Set `console=True` in the template temporarily — the `.exe` will open a
terminal showing the exact import/runtime error.

```python
# In SPEC_TEMPLATE, change:
console=False,  →  console=True,
```

---

## 📦 Distribution Strategy on GitHub Releases

For **v0.5.7**, ship the 8 small profiles (0–7), skip the OV-Optimum
monsters. Compress each:

```powershell
cd dist
$version = "v0.5.7"
$profiles = @(
    'do-not-tell-me', 'cloud', 'fwhisper', 'fwhisper-cloud',
    'ovgenai', 'ovgenai-cloud', 'fwhisper-ovgenai', 'fwhisper-ovgenai-cloud'
)

foreach ($p in $profiles) {
    Compress-Archive `
        -Path "Pyqttyai_$p.exe" `
        -DestinationPath "Pyqttyai-$version-$p-win64.zip" `
        -Force
    Write-Host "✅ Zipped: Pyqttyai-$version-$p-win64.zip"
}
```

Then upload via GitHub CLI:

```powershell
gh release create v0.5.7 `
    --title "Pyqttyai v0.5.7" `
    --notes-file CHANGELOG.md `
    dist\Pyqttyai-v0.5.7-*.zip
```

---

## 🎁 Summary

| Step | Command |
|---|---|
| 1. Build one | `python packing\packman.py cloud` |
| 2. Build all shippable | (see PowerShell loop above) |
| 3. Zip for release | (see Compress-Archive loop) |
| 4. Publish | `gh release create v0.5.7 ...` |

That's it — from source to GitHub Releases in three commands. 🚀
