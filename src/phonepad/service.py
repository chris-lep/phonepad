"""Autostart (see ADR-0006): systemd user unit + XDG autostart entry that starts it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from phonepad.paths import autostart_dir, systemd_user_dir

UNIT_NAME = "phonepad.service"
AUTOSTART_NAME = "phonepad.desktop"


def _quote(arg: str) -> str:
    """Quote one ExecStart argument for systemd if needed."""
    if arg and not any(ch in arg for ch in ' \t"\\$%;'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$").replace("%", "%%")
    return f'"{escaped}"'


def unit_text(python: str) -> str:
    exec_start = " ".join(_quote(a) for a in (python, "-m", "phonepad", "serve"))
    return f"""\
# Written by `phonepad service install`; remove with `phonepad service uninstall`.
# Started at login by ~/.config/autostart/{AUTOSTART_NAME}, which first imports DISPLAY and
# XAUTHORITY into the systemd user manager (see docs/decisions/0006-*.md).
[Unit]
Description=phonepad: phone as touchpad and keyboard
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=3
# Exit status 2: bad settings or port in use; restarting would not help.
RestartPreventExitStatus=2
"""


AUTOSTART_EXEC = (
    'sh -c "systemctl --user import-environment DISPLAY XAUTHORITY; '
    f'systemctl --user start {UNIT_NAME}"'
)


def autostart_text() -> str:
    return f"""\
[Desktop Entry]
Type=Application
Name=phonepad
Comment=Start the phonepad server (phone as touchpad and keyboard)
Exec={AUTOSTART_EXEC}
X-GNOME-Autostart-enabled=true
"""


def unit_path() -> Path:
    return systemd_user_dir() / UNIT_NAME


def autostart_path() -> Path:
    return autostart_dir() / AUTOSTART_NAME


def _systemctl(*args: str) -> int:
    return subprocess.run(["systemctl", "--user", *args], check=False).returncode


def install(python: str | None = None, start: bool = True) -> list[Path]:
    written = []
    for path, text in (
        (unit_path(), unit_text(python or sys.executable)),
        (autostart_path(), autostart_text()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    _systemctl("daemon-reload")
    if start:
        _systemctl("restart", UNIT_NAME)
    return written


def uninstall() -> list[Path]:
    _systemctl("stop", UNIT_NAME)
    removed = []
    for path in (autostart_path(), unit_path()):
        if path.exists():
            path.unlink()
            removed.append(path)
    _systemctl("daemon-reload")
    return removed


def status() -> int:
    return _systemctl("status", "--no-pager", UNIT_NAME)


def installed() -> bool:
    return unit_path().exists() and autostart_path().exists()
