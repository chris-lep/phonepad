from __future__ import annotations

from typing import Any

import pytest

from phonepad.input import InputService, InputUnavailableError, create_input_service
from phonepad.input.base import NotchAccumulator
from phonepad.input.recording import Recorder, RecordingKeyboard, RecordingPointer
from phonepad.input.xinput_tuning import _property_value, flat_profile_values
from phonepad.input.xtest import (
    REUSE_GUARD,
    KeycodeCache,
    char_to_keysym,
    is_unused,
    looks_like_ours,
)


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
    assert cache.get(1)[:2] == (200, True)
    assert cache.get(2)[:2] == (201, True)
    assert cache.get(1)[:2] == (200, False)  # hit, 1 is now most recent
    assert cache.get(3)[:2] == (201, True)  # evicts 2
    assert cache.get(2)[:2] == (200, True)  # evicts 1
    assert cache.used() == [200, 201]


def test_keycode_cache_waits_before_remapping_a_just_pressed_keycode() -> None:
    now = [100.0]
    cache = KeycodeCache([200], clock=lambda: now[0])
    keycode, _, wait = cache.get(1)
    assert wait == 0.0  # never pressed
    cache.pressed(keycode)
    now[0] += 0.03
    assert cache.get(1) == (200, False, 0.0)  # same keysym: no remap, no wait
    _, needs_mapping, wait = cache.get(2)
    assert needs_mapping and wait == pytest.approx(REUSE_GUARD - 0.03)
    now[0] += 1
    assert cache.get(3)[2] == 0.0


def test_only_phonepad_style_mappings_look_like_ours() -> None:
    assert looks_like_ours([0x61] * 10)
    assert looks_like_ours([0x61, 0x61, 0x61, 0x61, 0, 0, 0])  # as X stores it
    assert not looks_like_ours([0, 0, 0, 0])
    assert not looks_like_ours([0x61, 0x41, 0x61, 0x41])
    assert not is_unused([0x61])
    assert is_unused([0, 0])


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


async def test_backend_that_fails_unexpectedly_is_recreated() -> None:
    recorder = Recorder()
    made: list[RecordingPointer] = []

    def factory() -> RecordingPointer:
        made.append(RecordingPointer(recorder))
        return made[-1]

    service = InputService(factory, lambda: RecordingKeyboard(recorder))

    def boom(_: Any) -> None:
        raise OSError("device gone")

    with pytest.raises(InputUnavailableError):
        await service.pointer(boom)
    assert service.last_error
    await service.pointer(lambda p: p.move(1, 1))
    assert len(made) == 2
    assert service.last_error == ""  # cleared by the success
    await service.close()


async def test_fallback_pointer_is_upgraded_on_a_new_session() -> None:
    recorder = Recorder()
    uinput_ready = [False]

    class Fallback(RecordingPointer):
        name = "xtest"

    class Preferred(RecordingPointer):
        name = "uinput"

    def factory() -> RecordingPointer:
        return Preferred(recorder) if uinput_ready[0] else Fallback(recorder)

    service = InputService(factory, lambda: RecordingKeyboard(recorder), preferred_pointer="uinput")
    await service.start()
    await service.new_session()
    assert service.pointer_name == "xtest"
    uinput_ready[0] = True  # e.g. after scripts/setup-system.sh
    await service.new_session()
    assert service.pointer_name == "uinput"
    await service.close()
