"""Cross-platform application paths for Pyqttyai."""

from pathlib import Path

from platformdirs import (
    user_config_path,
    user_data_path,
    user_cache_path,
    user_log_path,
)

APP_NAME = "Pyqttyai"
APP_AUTHOR = "Polegatech"


def config_dir() -> Path:
    """User config directory.

    🐧 Linux:   ~/.config/Pyqttyai/
    🪟 Windows: C:\\Users\\<User>\\AppData\\Roaming\\Polegatech\\Pyqttyai\\
    🍎 macOS:   ~/Library/Application Support/Pyqttyai/
    """
    return user_config_path(APP_NAME, APP_AUTHOR, roaming=True)


def data_dir() -> Path:
    """User data directory (sessions, history)."""
    return user_data_path(APP_NAME, APP_AUTHOR, roaming=False)


def cache_dir() -> Path:
    """Cache directory (downloaded models, thumbnails)."""
    return user_cache_path(APP_NAME, APP_AUTHOR)


def log_dir() -> Path:
    """Application log directory."""
    return user_log_path(APP_NAME, APP_AUTHOR)


def whisper_models_dir() -> Path:
    """Default location for downloaded Whisper models."""
    return cache_dir() / "whisper_models"


def ensure_all() -> None:
    """Create all standard directories if missing."""
    for d in (config_dir(), data_dir(), cache_dir(), log_dir()):
        d.mkdir(parents=True, exist_ok=True)
