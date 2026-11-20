"""Virtual mouse through the kernel's uinput (works on X11 and Wayland)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from phonepad.input.base import InputUnavailableError, NotchAccumulator
from phonepad.input.xinput_tuning import tune_pointer
from phonepad.protocol import Button

log = logging.getLogger(__name__)

DEVICE_NAME = "phonepad virtual pointer"


class UinputPointer:
    name = "uinput"

    def __init__(self) -> None:
        try:
            from evdev import UInput, ecodes
        except ImportError as exc:  # pragma: no cover - evdev is a dependency
            raise InputUnavailableError(f"python-evdev missing: {exc}") from exc
        self._e: Any = ecodes
        capabilities: dict[int, Sequence[int]] = {
            ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
            ecodes.EV_REL: [
                ecodes.REL_X,
                ecodes.REL_Y,
                ecodes.REL_WHEEL,
                ecodes.REL_HWHEEL,
                ecodes.REL_WHEEL_HI_RES,
                ecodes.REL_HWHEEL_HI_RES,
            ],
        }
        try:
            self._dev = UInput(capabilities, name=DEVICE_NAME, vendor=0x1209, product=0x7070)
        except Exception as exc:  # evdev raises UInputError / OSError
            raise InputUnavailableError(
                f"cannot create a uinput device ({exc}); run scripts/setup-system.sh"
            ) from exc
        self._buttons = {
            "left": ecodes.BTN_LEFT,
            "right": ecodes.BTN_RIGHT,
            "middle": ecodes.BTN_MIDDLE,
        }
        self._wheel = NotchAccumulator()
        self._hwheel = NotchAccumulator()
        self._tuned = False

    def move(self, dx: int, dy: int) -> None:
        e = self._e
        if dx:
            self._dev.write(e.EV_REL, e.REL_X, dx)
        if dy:
            self._dev.write(e.EV_REL, e.REL_Y, dy)
        self._dev.syn()

    def scroll(self, dx: int, dy: int) -> None:
        e = self._e
        if dy:
            self._dev.write(e.EV_REL, e.REL_WHEEL_HI_RES, dy)
            if notches := self._wheel.add(dy):
                self._dev.write(e.EV_REL, e.REL_WHEEL, notches)
        if dx:
            self._dev.write(e.EV_REL, e.REL_HWHEEL_HI_RES, dx)
            if notches := self._hwheel.add(dx):
                self._dev.write(e.EV_REL, e.REL_HWHEEL, notches)
        self._dev.syn()

    def button(self, button: Button, pressed: bool) -> None:
        self._dev.write(self._e.EV_KEY, self._buttons[button], 1 if pressed else 0)
        self._dev.syn()

    def prepare_session(self) -> None:
        # The X server picks up the device asynchronously after creation; wait on first use.
        self._tuned = tune_pointer(DEVICE_NAME, wait=0.0 if self._tuned else 3.0) or self._tuned

    def close(self) -> None:
        self._dev.close()
