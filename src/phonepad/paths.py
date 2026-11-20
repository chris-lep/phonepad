"""XDG locations for configuration and state."""

from __future__ import annotations

import os
from pathlib import Path

APP = "phonepad"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def config_dir() -> Path:
    """User-edited settings (`config.toml`)."""
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def state_dir() -> Path:
    """Files written by phonepad itself (devices, trusted networks, pairing code)."""
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def systemd_user_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "systemd" / "user"


def autostart_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart"


def ensure_private_dir(path: Path) -> Path:
    """Create `path` (mode 0700) if needed and return it."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path
