"""Optional user settings from `~/.config/phonepad/config.toml` (read-only for the app)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from phonepad.paths import config_dir

PointerBackendName = Literal["auto", "uinput", "xtest"]
POINTER_BACKENDS: tuple[PointerBackendName, ...] = ("auto", "uinput", "xtest")
DEFAULT_PORT = 8790


class ConfigError(ValueError):
    """The settings file exists but is invalid."""


@dataclass(frozen=True)
class Config:
    port: int = DEFAULT_PORT
    pointer_backend: PointerBackendName = "auto"
    advertise_host: str = ""


def default_path() -> Path:
    return config_dir() / "config.toml"


def load(path: Path | None = None) -> Config:
    """Read the settings file; a missing file gives the defaults."""
    path = path or default_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    unknown = set(data) - {"port", "pointer_backend", "advertise_host"}
    if unknown:
        raise ConfigError(f"{path}: unknown settings {sorted(unknown)}")
    port = data.get("port", DEFAULT_PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ConfigError(f"{path}: port must be an integer 0-65535")
    backend = data.get("pointer_backend", "auto")
    if backend not in POINTER_BACKENDS:
        raise ConfigError(f"{path}: pointer_backend must be one of {list(POINTER_BACKENDS)}")
    host = data.get("advertise_host", "")
    if not isinstance(host, str):
        raise ConfigError(f"{path}: advertise_host must be a string")
    return Config(port=port, pointer_backend=cast(PointerBackendName, backend), advertise_host=host)
