# packing/pyqttyai_runtime_hook.py
import sys
import os

# 🛡️ Guard against None stdout/stderr in --windowed builds
class _NullStream:
    def write(self, *a, **kw): pass
    def flush(self, *a, **kw): pass
    def isatty(self): return False
    def fileno(self): raise OSError("no fileno")
    def close(self): pass
    def __getattr__(self, name): return lambda *a, **kw: None

if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

# 🤫 Disable tqdm progress bars (they also try to write to stderr)
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# 🔇 Silence symlink warnings on Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
