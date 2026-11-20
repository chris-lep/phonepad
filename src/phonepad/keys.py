"""Special keys the web app may send, by neutral name.

Each entry maps to an X keysym name (XTest backend) and an evdev key name (for a future uinput
or Wayland keyboard backend). Add a key here and it is accepted by the protocol.
"""

from __future__ import annotations

from typing import NamedTuple


class KeySpec(NamedTuple):
    x_keysym: str
    evdev: str


KEYS: dict[str, KeySpec] = {
    "enter": KeySpec("Return", "KEY_ENTER"),
    "backspace": KeySpec("BackSpace", "KEY_BACKSPACE"),
    "escape": KeySpec("Escape", "KEY_ESC"),
    "tab": KeySpec("Tab", "KEY_TAB"),
    "left": KeySpec("Left", "KEY_LEFT"),
    "right": KeySpec("Right", "KEY_RIGHT"),
    "up": KeySpec("Up", "KEY_UP"),
    "down": KeySpec("Down", "KEY_DOWN"),
    "delete": KeySpec("Delete", "KEY_DELETE"),
    "home": KeySpec("Home", "KEY_HOME"),
    "end": KeySpec("End", "KEY_END"),
    "pageup": KeySpec("Prior", "KEY_PAGEUP"),
    "pagedown": KeySpec("Next", "KEY_PAGEDOWN"),
}
