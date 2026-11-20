"""X11 input through the XTest extension: keyboard (any Unicode character) and a pointer
fallback.

Characters are typed through spare keycodes (no keysyms in the current map) that are mapped to
the needed keysym on demand, so typing does not depend on the keyboard layout. Mapped keycodes
are cached least-recently-used first and cleared again on `close()`. The claimed keycodes are
recorded in a state file, so mappings left behind by a crash are reclaimed on the next start
(only keycodes from that record, so a real key is never taken).

A keycode that was pressed moments ago is not remapped at once: X clients look up the keysym
when they process the event, which may be after the remap. `REUSE_GUARD` waits that out.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from phonepad.input.base import InputUnavailableError, NotchAccumulator
from phonepad.keys import KEYS
from phonepad.protocol import Button

log = logging.getLogger(__name__)

T = TypeVar("T")

NO_SYMBOL = 0
REUSE_GUARD = 0.1  # seconds between pressing a keycode and remapping it to another keysym


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


def is_unused(keysyms: Sequence[int]) -> bool:
    return not any(keysyms)


def looks_like_ours(keysyms: Sequence[int]) -> bool:
    """One keysym repeated (how phonepad maps a keycode); X may zero the later columns."""
    present = {k for k in keysyms if k}
    return len(present) == 1 and bool(keysyms[0])


class KeycodeCache:
    """Assigns spare keycodes to keysyms, evicting the least recently used one."""

    def __init__(self, keycodes: list[int], clock: Callable[[], float] = time.monotonic) -> None:
        if not keycodes:
            raise InputUnavailableError("no spare keycodes in the X keyboard map")
        self._free = list(keycodes)
        self._assigned: OrderedDict[int, int] = OrderedDict()  # keysym -> keycode
        self._last_press: dict[int, float] = {}  # keycode -> time of the last press
        self._clock = clock

    def get(self, keysym: int) -> tuple[int, bool, float]:
        """(keycode, needs_mapping, seconds to wait before remapping it) for `keysym`."""
        if keysym in self._assigned:
            self._assigned.move_to_end(keysym)
            return self._assigned[keysym], False, 0.0
        if self._free:
            keycode = self._free.pop(0)
        else:
            _, keycode = self._assigned.popitem(last=False)
        self._assigned[keysym] = keycode
        since = self._clock() - self._last_press.get(keycode, float("-inf"))
        return keycode, True, max(REUSE_GUARD - since, 0.0)

    def pressed(self, keycode: int) -> None:
        self._last_press[keycode] = self._clock()

    def used(self) -> list[int]:
        return sorted(self._assigned.values())


class XSession:
    """A lazily opened X display connection, reopened on the next call after an error."""

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
        """Run `action(display)`, then drain the events X sent us.

        A broken connection is not retried here: a multi-key action may have been partly
        delivered, and repeating it would type text twice. The next call reconnects.
        """
        from Xlib import X
        from Xlib import error as xerror

        display = self.get()
        try:
            result = action(display)
            # Nobody reads this connection's events (MappingNotify after every remap);
            # without draining they pile up for the lifetime of the server.
            while display.pending_events():
                event = display.next_event()
                if event.type == X.MappingNotify:
                    display.refresh_keyboard_mapping(event)
            return result
        except (xerror.ConnectionClosedError, BrokenPipeError, ConnectionError) as exc:
            self.reset()
            raise InputUnavailableError("lost the connection to the X server") from exc

    def close(self) -> None:
        self.reset()


class XTestKeyboard:
    name = "xtest"

    def __init__(self, session: XSession, record: Path | None = None) -> None:
        self._session = session
        self._record = record  # JSON list of the keycodes claimed as spares
        self._cache: KeycodeCache | None = None
        self._generation = -1
        self._per_keycode = 0
        self._spares: list[int] = []

    def _setup(self, d: Any) -> KeycodeCache:
        """(Re)build the spare keycode cache for this display connection."""
        if self._cache is not None and self._generation == self._session.generation:
            return self._cache
        first = d.display.info.min_keycode
        count = d.display.info.max_keycode - first + 1
        mapping = d.get_keyboard_mapping(first, count)
        self._per_keycode = len(mapping[0]) if mapping else 1
        spares = [first + i for i, syms in enumerate(mapping) if is_unused(syms) and first + i > 8]
        for keycode in self._recorded():
            index = keycode - first
            in_range = 0 <= index < len(mapping)
            if keycode not in spares and in_range and looks_like_ours(mapping[index]):
                spares.append(keycode)  # left behind by an earlier run
        self._spares = sorted(spares)
        self._save_record(self._spares)
        self._cache = KeycodeCache(list(self._spares))
        self._generation = self._session.generation
        return self._cache

    def _recorded(self) -> list[int]:
        if self._record is None:
            return []
        try:
            data = json.loads(self._record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [k for k in data if isinstance(k, int)] if isinstance(data, list) else []

    def _save_record(self, keycodes: list[int]) -> None:
        if self._record is None:
            return
        try:
            self._record.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = self._record.with_suffix(".tmp")
            tmp.write_text(json.dumps(keycodes), encoding="utf-8")
            tmp.replace(self._record)
        except OSError:
            log.warning("cannot record spare keycodes in %s", self._record, exc_info=True)

    def _tap(self, d: Any, keycode: int) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        xtest.fake_input(d, X.KeyPress, keycode)
        xtest.fake_input(d, X.KeyRelease, keycode)

    def _tap_keysym(self, d: Any, keysym: int) -> None:
        cache = self._setup(d)
        keycode, needs_mapping, wait = cache.get(keysym)
        if needs_mapping:
            if wait:
                d.sync()
                time.sleep(wait)
            d.change_keyboard_mapping(keycode, [[keysym] * self._per_keycode])
            d.sync()  # the mapping must reach the server before the key event
        self._tap(d, keycode)
        cache.pressed(keycode)

    def _press_special(self, d: Any, key: str) -> None:
        from Xlib import XK

        keysym = XK.string_to_keysym(KEYS[key].x_keysym)
        # A keycode that gives the keysym without modifiers in the first group.
        for keycode, index in d.keysym_to_keycodes(keysym):
            if index == 0:
                self._tap(d, int(keycode))
                return
        self._tap_keysym(d, keysym)

    def key(self, key: str) -> None:
        def press(d: Any) -> None:
            self._press_special(d, key)
            d.sync()

        self._session.call(press)

    def type_text(self, text: str) -> None:
        def type_all(d: Any) -> None:
            for ch in text:
                if ch == "\n":
                    self._press_special(d, "enter")
                elif ch == "\t":
                    self._press_special(d, "tab")
                elif (keysym := char_to_keysym(ch)) is not None:
                    self._tap_keysym(d, keysym)
            d.sync()

        self._session.call(type_all)

    def close(self) -> None:
        """Clear the spare keycodes, including reclaimed leftovers (best effort)."""
        if self._cache is None:
            return
        self._cache = None
        try:
            d = self._session.get()
            for keycode in self._spares:
                d.change_keyboard_mapping(keycode, [[NO_SYMBOL] * self._per_keycode])
            d.sync()
            if self._record is not None:
                self._record.unlink(missing_ok=True)
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
