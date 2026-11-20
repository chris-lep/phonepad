"""Backend interfaces for injecting input (see ADR-0003).

Backends are synchronous and are only ever called from the single input thread
(`InputService`), so they need no locking and may block briefly.
"""

from __future__ import annotations

from typing import Protocol

from phonepad.protocol import Button

WHEEL_NOTCH = 120  # high-resolution wheel units per notch (Linux REL_WHEEL_HI_RES)


class InputUnavailableError(RuntimeError):
    """A backend cannot work on this system (no permission, no X display, ...)."""


class PointerBackend(Protocol):
    name: str

    def move(self, dx: int, dy: int) -> None: ...

    def scroll(self, dx: int, dy: int) -> None:
        """Wheel units (120 per notch); dy > 0 scrolls up, dx > 0 scrolls right."""

    def button(self, button: Button, pressed: bool) -> None: ...

    def prepare_session(self) -> None:
        """Called when a phone connects (re-apply device settings)."""

    def close(self) -> None: ...


class KeyboardBackend(Protocol):
    name: str

    def key(self, key: str) -> None:
        """Press and release a special key from `phonepad.keys.KEYS`."""

    def type_text(self, text: str) -> None:
        """Type arbitrary Unicode text."""

    def close(self) -> None: ...


class NotchAccumulator:
    """Turns high-resolution wheel units into whole notches, keeping the remainder."""

    def __init__(self) -> None:
        self._rest = 0

    def add(self, units: int) -> int:
        """Add units; returns the number of whole notches (signed) now due."""
        self._rest += units
        notches = int(self._rest / WHEEL_NOTCH)  # truncate towards zero
        self._rest -= notches * WHEEL_NOTCH
        return notches
