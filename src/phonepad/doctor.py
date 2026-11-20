"""`phonepad doctor`: check the setup and say how to fix each problem."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from phonepad import config as config_mod
from phonepad import service
from phonepad.auth import Registry
from phonepad.network import NetworkError, NmcliSource, TrustStore
from phonepad.paths import state_dir


@dataclass(frozen=True)
class Check:
    ok: bool | None  # None = warning / cannot tell
    label: str
    hint: str = ""


def fetch_status(port: int, timeout: float = 1.0) -> dict[str, Any] | None:
    """The running server's /api/status, or None if it is not reachable."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as r:
            data = json.load(r)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return data if isinstance(data, dict) else None


def _x_check() -> Check:
    if not os.environ.get("DISPLAY"):
        return Check(None, "X display", "DISPLAY is not set (fine over SSH; the service has it)")
    try:
        from Xlib import display

        d = display.Display()
        has = d.has_extension("XTEST")
        d.close()
    except Exception as exc:
        return Check(False, "X display", f"cannot open {os.environ['DISPLAY']}: {exc}")
    if not has:
        return Check(False, "XTest extension", "the X server has no XTEST extension")
    return Check(True, f"X display {os.environ['DISPLAY']} with XTest (keyboard)")


def run_checks() -> list[Check]:
    checks: list[Check] = []
    try:
        cfg = config_mod.load()
        checks.append(Check(True, f"settings ({config_mod.default_path()}), port {cfg.port}"))
    except config_mod.ConfigError as exc:
        checks.append(Check(False, "settings file", str(exc)))
        cfg = config_mod.Config()

    if os.access("/dev/uinput", os.W_OK):
        checks.append(Check(True, "/dev/uinput writable (smooth scrolling)"))
    else:
        checks.append(
            Check(
                False,
                "/dev/uinput not writable",
                "run `sudo scripts/setup-system.sh` (udev rule); until then the XTest pointer "
                "is used and scrolling moves in notches",
            )
        )

    checks.append(_x_check())
    if shutil.which("xinput"):
        checks.append(Check(True, "xinput (flat acceleration for the virtual mouse)"))
    else:
        checks.append(Check(None, "xinput missing", "pointer may be accelerated twice"))

    trust = TrustStore(state_dir())
    trusted = trust.trusted()
    try:
        active = asyncio.run(NmcliSource().active_connections())
    except NetworkError as exc:
        checks.append(Check(False, "NetworkManager", str(exc)))
        active = []
    if not trusted:
        checks.append(
            Check(
                False, "no trusted network", "connect to your home Wi-Fi and run `phonepad trust`"
            )
        )
    elif any(c.uuid in trusted for c in active):
        names = ", ".join(c.name for c in active if c.uuid in trusted)
        checks.append(Check(True, f"on a trusted network ({names})"))
    else:
        checks.append(
            Check(None, "not on a trusted network", f"trusted: {', '.join(trusted.values())}")
        )

    status = fetch_status(cfg.port)
    if status is None:
        checks.append(
            Check(
                False,
                f"server not running on port {cfg.port}",
                "`phonepad service install` (autostart) or `phonepad serve`; logs: "
                "`journalctl --user -u phonepad`",
            )
        )
    else:
        lan = status.get("lan") or []
        checks.append(
            Check(
                True,
                f"server {status.get('version')} running, pointer: {status.get('pointer')}, "
                f"LAN: {', '.join(lan) or 'none'}",
            )
        )
        if status.get("input_error"):
            checks.append(Check(None, "last input error", str(status["input_error"])))
        if status.get("network_problem"):
            checks.append(Check(False, "server cannot read networks", status["network_problem"]))

    if service.installed():
        checks.append(Check(True, "autostart installed"))
    else:
        checks.append(Check(None, "autostart not installed", "`phonepad service install`"))

    devices = Registry(state_dir()).devices()
    if devices:
        checks.append(Check(True, f"{len(devices)} paired device(s)"))
    else:
        checks.append(Check(None, "no paired devices", "`phonepad pair`"))

    checks.append(
        Check(
            None,
            "firewall not checked (needs root)",
            f"`sudo ufw status | grep {cfg.port}` should show an ALLOW rule from your home subnet",
        )
    )
    return checks


def print_checks(checks: list[Check]) -> int:
    marks = {True: "ok  ", False: "FAIL", None: "note"}
    for check in checks:
        line = f"[{marks[check.ok]}] {check.label}"
        if check.hint:
            line += f"\n       {check.hint}"
        print(line)
    return 1 if any(c.ok is False for c in checks) else 0
