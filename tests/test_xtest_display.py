"""XTest against a throwaway X server (make xtest). Skipped without PHONEPAD_TEST_DISPLAY."""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from phonepad.input.xtest import XSession, XTestKeyboard, XTestPointer, char_to_keysym

DISPLAY = os.environ.get("PHONEPAD_TEST_DISPLAY", "")
pytestmark = [
    pytest.mark.xserver,
    pytest.mark.skipif(not DISPLAY, reason="needs PHONEPAD_TEST_DISPLAY (make xtest)"),
]


@pytest.fixture
def window() -> Any:
    from Xlib import X, display

    d = display.Display(DISPLAY)
    screen = d.screen()
    win = screen.root.create_window(
        0, 0, 200, 100, 0, screen.root_depth, event_mask=X.KeyPressMask | X.KeyReleaseMask
    )
    win.map()
    d.sync()
    time.sleep(0.2)
    win.set_input_focus(X.RevertToParent, X.CurrentTime)
    d.sync()
    yield d
    win.destroy()
    d.close()


def typed_keysyms(d: Any, expected: int) -> list[int]:
    """Keysyms of KeyPress events, looked up in the map current at the time of each event."""
    from Xlib import X

    result: list[int] = []
    deadline = time.monotonic() + 3
    while len(result) < expected and time.monotonic() < deadline:
        while d.pending_events():
            ev = d.next_event()
            if ev.type == X.MappingNotify:
                d.refresh_keyboard_mapping(ev)
            elif ev.type == X.KeyPress:
                result.append(d.keycode_to_keysym(ev.detail, 0))
        time.sleep(0.01)
    return result


def test_types_any_character_and_restores_keymap(window: Any) -> None:
    from Xlib import XK

    session = XSession(DISPLAY)
    keyboard = XTestKeyboard(session)
    first = window.display.info.min_keycode
    count = window.display.info.max_keycode - first + 1
    before = window.get_keyboard_mapping(first, count)

    text = "aÄß€😀zy"
    keyboard.type_text(text)
    keyboard.key("backspace")
    got = typed_keysyms(window, len(text) + 1)
    assert got == [char_to_keysym(ch) for ch in text] + [XK.string_to_keysym("BackSpace")]

    keyboard.close()
    session.close()
    assert window.get_keyboard_mapping(first, count) == before


def test_pointer_fallback_moves_relative(window: Any) -> None:
    session = XSession(DISPLAY)
    pointer = XTestPointer(session)
    root = window.screen().root
    root.warp_pointer(100, 100)
    window.sync()
    pointer.move(15, -7)
    time.sleep(0.1)
    pos = root.query_pointer()
    assert (pos.root_x, pos.root_y) == (115, 93)
    session.close()
