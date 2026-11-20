"""Best-effort X11 settings for the virtual mouse (see ADR-0008).

The web app does pointer acceleration and scroll direction itself, so the uinput mouse gets
libinput's flat profile and natural scrolling off. Uses the `xinput` command; does nothing
without X or `xinput`.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

TIMEOUT = 3.0


def _xinput(*args: str) -> subprocess.CompletedProcess[str] | None:
    exe = shutil.which("xinput")
    if exe is None or not os.environ.get("DISPLAY"):
        return None
    try:
        return subprocess.run(
            [exe, *args], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def flat_profile_values(current: str) -> list[str]:
    """Values for 'libinput Accel Profile Enabled' selecting "flat".

    The property has 2 (adaptive, flat) or 3 (adaptive, flat, custom) values depending on the
    libinput version; keep the count the device reports.
    """
    count = len([v for v in current.replace(",", " ").split() if v.strip()])
    return ["0", "1"] + ["0"] * max(count - 2, 0)


def _property_value(props: str, name: str) -> str | None:
    for line in props.splitlines():
        line = line.strip()
        if line.startswith(name + " ("):
            return line.split(":", 1)[1] if ":" in line else ""
    return None


def tune_pointer(device_name: str, wait: float = 0.0) -> bool:
    """Apply flat acceleration and natural scrolling off; True if the device was found."""
    target = f"pointer:{device_name}"
    deadline = time.monotonic() + wait
    while True:
        listed = _xinput("list-props", target)
        if listed is None:
            return False
        if listed.returncode == 0:
            break
        if time.monotonic() >= deadline:
            log.debug("xinput: %s not found", device_name)
            return False
        time.sleep(0.2)

    profile = _property_value(listed.stdout, "libinput Accel Profile Enabled")
    if profile is not None:
        _xinput("set-prop", target, "libinput Accel Profile Enabled", *flat_profile_values(profile))
    if _property_value(listed.stdout, "libinput Accel Speed") is not None:
        _xinput("set-prop", target, "libinput Accel Speed", "0")
    if _property_value(listed.stdout, "libinput Natural Scrolling Enabled") is not None:
        _xinput("set-prop", target, "libinput Natural Scrolling Enabled", "0")
    return True
