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


def test_long_burst_with_more_characters_than_spare_keycodes(window: Any) -> None:
    """Regression: remapping a just-pressed keycode garbled bursts (dictation, paste).

    A second thread reads the events while typing, like a real application would.
    """
    import threading

    from Xlib import X, display

    reader = display.Display(DISPLAY)
    got: list[int] = []
    done = threading.Event()
    # Listen on the focused window through a separate connection, as a real client.
    focus = reader.get_input_focus().focus
    focus.change_attributes(event_mask=X.KeyPressMask)
    reader.sync()

    def read() -> None:
        while not done.is_set() or reader.pending_events():
            while reader.pending_events():
                ev = reader.next_event()
                if ev.type == X.MappingNotify:
                    reader.refresh_keyboard_mapping(ev)
                elif ev.type == X.KeyPress:
                    got.append(reader.keycode_to_keysym(ev.detail, 0))
            time.sleep(0.001)

    thread = threading.Thread(target=read)
    thread.start()
    session = XSession(DISPLAY)
    keyboard = XTestKeyboard(session)
    text = "The quick brown fox jumps over the lazy dog, 1234567890! ÄÖÜß€ äöü"
    keyboard.type_text(text)
    time.sleep(0.5)
    done.set()
    thread.join(5)
    keyboard.close()
    session.close()
    reader.close()
    assert got == [char_to_keysym(ch) for ch in text]


def test_leftovers_from_a_crash_are_reclaimed_and_cleared(window: Any, tmp_path: Any) -> None:
    first = window.display.info.min_keycode
    count = window.display.info.max_keycode - first + 1
    before = window.get_keyboard_mapping(first, count)
    record = tmp_path / "keymap.json"

    crashed = XTestKeyboard(XSession(DISPLAY), record)
    crashed.type_text("xyz")  # maps three spare keycodes, then "crashes" without close()
    assert window.get_keyboard_mapping(first, count) != before
    assert record.exists()

    session = XSession(DISPLAY)
    keyboard = XTestKeyboard(session, record)
    keyboard.type_text("a")
    keyboard.close()
    session.close()
    assert window.get_keyboard_mapping(first, count) == before
    assert not record.exists()
