"""🎛️ Runtime detection of which Whisper backends are bundled."""
import logging

log = logging.getLogger(__name__)

try:
    import faster_whisper  # noqa: F401
    _HAS_FASTER = True
except ImportError:
    _HAS_FASTER = False

try:
    import groq  # noqa: F401
    _HAS_GROQ = True
except ImportError:
    _HAS_GROQ = False

try:
    import openai  # noqa: F401
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

try:
    import openvino_genai  # noqa: F401
    _HAS_OV_GENAI = True
except ImportError:
    _HAS_OV_GENAI = False

try:
    import optimum.intel  # noqa: F401
    import openvino       # noqa: F401
    _HAS_OV = True
except ImportError:
    _HAS_OV = False

# 🎚️ Silero VAD asset probe (can be present even without faster_whisper-VAD path used)
def _probe_vad() -> bool:
    """Verify standalone Silero VAD ONNX asset is loadable."""
    try:
        from pyqttyai.audio.silero_vad import is_vad_available
        return is_vad_available()
    except Exception as e:
        log.warning(f"⚠️ Silero VAD not loadable: {e}")
        return False

_HAS_VAD = _probe_vad()


AVAILABLE_BACKENDS: dict[str, bool] = {
    "faster-whisper": _HAS_FASTER,
    "groq":           _HAS_GROQ,
    "openai":         _HAS_OPENAI,
    "openvino":       _HAS_OV,
    "openvino_genai": _HAS_OV_GENAI,
    "silero_vad":     _HAS_VAD,   # 🎚️ NEW
}


def get_build_flavor() -> str:
    """Return 'min', 'cloud', or 'full' based on what was bundled."""
    if AVAILABLE_BACKENDS["openvino_genai"] or AVAILABLE_BACKENDS["openvino"]:
        return "full"
    if AVAILABLE_BACKENDS["groq"] or AVAILABLE_BACKENDS["openai"]:
        return "cloud"
    return "min"


def has_vad() -> bool:
    """🎚️ Convenience accessor used by transcription worker."""
    return _HAS_VAD


def log_capabilities() -> None:
    flavor = get_build_flavor().upper()
    log.info(f"🏷️  Build flavor: {flavor}")
    for name, available in AVAILABLE_BACKENDS.items():
        log.info(f"   {'✅' if available else '❌'} {name}")
