from __future__ import annotations

from typing import Any

import pytest

from phonepad.input import InputService, InputUnavailableError, create_input_service
from phonepad.input.base import NotchAccumulator
from phonepad.input.recording import Recorder, RecordingKeyboard, RecordingPointer
from phonepad.input.xinput_tuning import _property_value, flat_profile_values
from phonepad.input.xtest import KeycodeCache, char_to_keysym


def test_notch_accumulator_keeps_remainder_both_ways() -> None:
    acc = NotchAccumulator()
    assert acc.add(60) == 0
    assert acc.add(60) == 1
    assert acc.add(250) == 2  # 10 left
    assert acc.add(-130) == -1  # -120 -> -1, 0 left
    assert acc.add(-119) == 0
    assert acc.add(-1) == -1


def test_char_to_keysym() -> None:
    assert char_to_keysym("a") == ord("a")
    assert char_to_keysym("Ä") == 0xC4  # Latin-1
    assert char_to_keysym("€") == 0x01000000 + 0x20AC
    assert char_to_keysym("😀") == 0x01000000 + 0x1F600
    assert char_to_keysym("\x07") is None
    assert char_to_keysym("\x85") is None


def test_keycode_cache_is_lru() -> None:
    cache = KeycodeCache([200, 201])
    assert cache.get(1) == (200, True)
    assert cache.get(2) == (201, True)
    assert cache.get(1) == (200, False)  # hit, 1 is now most recent
    assert cache.get(3) == (201, True)  # evicts 2
    assert cache.get(2) == (200, True)  # evicts 1
    assert cache.used() == [200, 201]


def test_keycode_cache_needs_spare_keycodes() -> None:
    with pytest.raises(InputUnavailableError):
        KeycodeCache([])


def test_xinput_property_parsing() -> None:
    props = (
        "Device 'phonepad virtual pointer':\n"
        "\tlibinput Accel Speed (332):\t0.000000\n"
        "\tlibinput Accel Speed Default (333):\t0.000000\n"
        "\tlibinput Accel Profile Enabled (335):\t1, 0, 0\n"
    )
    assert _property_value(props, "libinput Accel Profile Enabled") == "\t1, 0, 0"
    assert _property_value(props, "libinput Accel Speed") == "\t0.000000"
    assert _property_value(props, "libinput Natural Scrolling Enabled") is None
    assert flat_profile_values("1, 0, 0") == ["0", "1", "0"]
    assert flat_profile_values("1, 0") == ["0", "1"]


async def test_recording_service_keeps_order() -> None:
    recorder = Recorder()
    service = InputService(lambda: RecordingPointer(recorder), lambda: RecordingKeyboard(recorder))
    await service.start()
    await service.pointer(lambda p: p.move(1, 2))
    await service.keyboard(lambda k: k.type_text("hi"))
    await service.pointer(lambda p: p.button("left", True))
    await service.close()
    assert [e["kind"] for e in recorder.events] == ["move", "text", "button"]
    assert service.pointer_name == "recording"


async def test_failed_backend_is_retried_on_next_use() -> None:
    attempts: list[int] = []
    recorder = Recorder()

    def flaky_keyboard() -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise InputUnavailableError("no X yet")
        return RecordingKeyboard(recorder)

    service = InputService(lambda: RecordingPointer(recorder), flaky_keyboard)
    with pytest.raises(InputUnavailableError):
        await service.keyboard(lambda k: k.key("enter"))
    assert service.last_error == "no X yet"
    await service.keyboard(lambda k: k.key("enter"))
    await service.close()
    assert recorder.events == [{"kind": "key", "key": "enter"}]


async def test_unexpected_backend_errors_become_input_unavailable() -> None:
    recorder = Recorder()
    service = InputService(lambda: RecordingPointer(recorder), lambda: RecordingKeyboard(recorder))

    def boom(_: Any) -> None:
        raise ValueError("bad")

    with pytest.raises(InputUnavailableError):
        await service.pointer(boom)
    await service.close()


async def test_record_file(tmp_path: Any) -> None:
    path = tmp_path / "events.jsonl"
    service = create_input_service(record=path)
    await service.start()
    await service.keyboard(lambda k: k.type_text("ä"))
    await service.close()
    assert path.read_text(encoding="utf-8") == '{"kind": "text", "text": "ä"}\n'
