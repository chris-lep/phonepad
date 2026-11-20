"""X11 input through the XTest extension: keyboard (any Unicode character) and a pointer
fallback.

Characters are typed through spare keycodes (no keysyms in the current map) that are mapped to
the needed keysym on demand, so typing does not depend on the keyboard layout. Mapped keycodes
are cached least-recently-used first and cleared again on `close()`.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

from phonepad.input.base import InputUnavailableError, NotchAccumulator
from phonepad.keys import KEYS
from phonepad.protocol import Button

log = logging.getLogger(__name__)

T = TypeVar("T")

MAX_SCRATCH = 16
NO_SYMBOL = 0


def char_to_keysym(ch: str) -> int | None:
    """The X keysym for one character, or None for control characters.

    Latin-1 printable characters have keysyms equal to their code point; everything else uses
    the Unicode keysym range 0x01000000 + code point.
    """
    cp = ord(ch)
    if cp < 0x20 or 0x7F <= cp < 0xA0:
        return None
    if cp < 0x100:
        return cp
    return 0x01000000 + cp


class KeycodeCache:
    """Assigns spare keycodes to keysyms, evicting the least recently used one."""

    def __init__(self, keycodes: list[int]) -> None:
        if not keycodes:
            raise InputUnavailableError("no spare keycodes in the X keyboard map")
        self._free = list(keycodes)
        self._assigned: OrderedDict[int, int] = OrderedDict()  # keysym -> keycode

    def get(self, keysym: int) -> tuple[int, bool]:
        """(keycode, needs_mapping) for `keysym`."""
        if keysym in self._assigned:
            self._assigned.move_to_end(keysym)
            return self._assigned[keysym], False
        if self._free:
            keycode = self._free.pop(0)
        else:
            _, keycode = self._assigned.popitem(last=False)
        self._assigned[keysym] = keycode
        return keycode, True

    def forget(self, keysym: int) -> None:
        keycode = self._assigned.pop(keysym, None)
        if keycode is not None:
            self._free.insert(0, keycode)

    def used(self) -> list[int]:
        return sorted(self._assigned.values())


class XSession:
    """A lazily opened X display connection that is reopened after errors."""

    def __init__(self, display_name: str | None = None) -> None:
        self._name = display_name
        self._display: Any = None
        self.generation = 0  # increases with every new connection

    def get(self) -> Any:
        if self._display is None:
            from Xlib import display as xdisplay
            from Xlib import error as xerror

            try:
                d = xdisplay.Display(self._name)
            except (xerror.DisplayError, OSError) as exc:
                raise InputUnavailableError(f"cannot open X display: {exc}") from exc
            if not d.has_extension("XTEST"):
                d.close()
                raise InputUnavailableError("the X server has no XTEST extension")
            self._display = d
            self.generation += 1
        return self._display

    def reset(self) -> None:
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                log.debug("closing X display failed", exc_info=True)
        self._display = None

    def call(self, action: Callable[[Any], T]) -> T:
        """Run `action(display)`; on a broken connection reopen once and retry."""
        from Xlib import error as xerror

        for attempt in (1, 2):
            display = self.get()
            try:
                return action(display)
            except (xerror.ConnectionClosedError, BrokenPipeError, ConnectionError):
                self.reset()
                if attempt == 2:
                    raise InputUnavailableError("lost the connection to the X server") from None
                log.info("X connection lost, reconnecting")
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.reset()


class XTestKeyboard:
    name = "xtest"

    def __init__(self, session: XSession) -> None:
        self._session = session
        self._cache: KeycodeCache | None = None
        self._generation = -1
        self._per_keycode = 0

    def _setup(self, d: Any) -> KeycodeCache:
        """(Re)build the spare keycode cache for this display connection."""
        if self._cache is not None and self._generation == self._session.generation:
            return self._cache
        first = d.display.info.min_keycode
        count = d.display.info.max_keycode - first + 1
        mapping = d.get_keyboard_mapping(first, count)
        self._per_keycode = len(mapping[0]) if mapping else 1
        spare = [first + i for i, syms in enumerate(mapping) if not any(syms) and first + i > 8]
        self._cache = KeycodeCache(spare[-MAX_SCRATCH:])
        self._generation = self._session.generation
        return self._cache

    def _tap(self, d: Any, keycode: int) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        xtest.fake_input(d, X.KeyPress, keycode)
        xtest.fake_input(d, X.KeyRelease, keycode)

    def _tap_keysym(self, d: Any, keysym: int) -> None:
        cache = self._setup(d)
        keycode, needs_mapping = cache.get(keysym)
        if needs_mapping:
            d.change_keyboard_mapping(keycode, [[keysym] * self._per_keycode])
            d.sync()  # the mapping must reach the server before the key event
        self._tap(d, keycode)

    def _special_keycode(self, d: Any, keysym: int) -> int | None:
        """A keycode that produces `keysym` without modifiers in the first group."""
        for keycode, index in d.keysym_to_keycodes(keysym):
            if index == 0:
                return int(keycode)
        return None

    def key(self, key: str) -> None:
        from Xlib import XK

        keysym = XK.string_to_keysym(KEYS[key].x_keysym)

        def press(d: Any) -> None:
            keycode = self._special_keycode(d, keysym)
            if keycode is None:
                self._tap_keysym(d, keysym)
            else:
                self._tap(d, keycode)
            d.sync()

        self._session.call(press)

    def type_text(self, text: str) -> None:
        def type_all(d: Any) -> None:
            for ch in text:
                if ch == "\n":
                    self.key("enter")
                    continue
                if ch == "\t":
                    self.key("tab")
                    continue
                keysym = char_to_keysym(ch)
                if keysym is not None:
                    self._tap_keysym(d, keysym)
            d.sync()

        self._session.call(type_all)

    def close(self) -> None:
        """Give the spare keycodes back (best effort)."""
        if self._cache is None:
            return
        used = self._cache.used()
        self._cache = None
        try:
            d = self._session.get()
            for keycode in used:
                d.change_keyboard_mapping(keycode, [[NO_SYMBOL] * self._per_keycode])
            d.sync()
        except Exception:
            log.debug("restoring the keymap failed", exc_info=True)


class XTestPointer:
    """Pointer fallback when uinput is not available (scrolling in whole notches)."""

    name = "xtest"
    _BUTTONS: ClassVar[dict[str, int]] = {"left": 1, "middle": 2, "right": 3}

    def __init__(self, session: XSession) -> None:
        self._session = session
        self._session.get()  # fail now if X is not reachable
        self._wheel = NotchAccumulator()
        self._hwheel = NotchAccumulator()

    def move(self, dx: int, dy: int) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        def act(d: Any) -> None:
            xtest.fake_input(d, X.MotionNotify, detail=True, x=dx, y=dy)
            d.flush()

        self._session.call(act)

    def scroll(self, dx: int, dy: int) -> None:
        vertical = self._wheel.add(dy)
        horizontal = self._hwheel.add(dx)
        clicks = [4 if vertical > 0 else 5] * abs(vertical)
        clicks += [7 if horizontal > 0 else 6] * abs(horizontal)
        if clicks:
            self._click_all(clicks)

    def _click_all(self, buttons: list[int]) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        def act(d: Any) -> None:
            for b in buttons:
                xtest.fake_input(d, X.ButtonPress, b)
                xtest.fake_input(d, X.ButtonRelease, b)
            d.flush()

        self._session.call(act)

    def button(self, button: Button, pressed: bool) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        def act(d: Any) -> None:
            event = X.ButtonPress if pressed else X.ButtonRelease
            xtest.fake_input(d, event, self._BUTTONS[button])
            d.flush()

        self._session.call(act)

    def prepare_session(self) -> None:
        pass

    def close(self) -> None:
        pass
