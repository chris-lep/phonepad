from __future__ import annotations

import json

import pytest

from phonepad.protocol import (
    MAX_MOVE,
    ButtonEvent,
    Hello,
    Key,
    Move,
    Pair,
    ProtocolError,
    Scroll,
    Text,
    parse,
)


def msg(**fields: object) -> str:
    return json.dumps(fields)


def test_valid_messages() -> None:
    assert parse(msg(type="hello", v=1, token="t")) == Hello("t")
    assert parse(msg(type="pair", v=1, code="123 456", name="n")) == Pair("123456", "n")
    assert parse(msg(type="move", dx=3, dy=-2)) == Move(3, -2)
    assert parse(msg(type="scroll", dx=0, dy=240)) == Scroll(0, 240)
    assert parse(msg(type="button", button="left", action="down")) == ButtonEvent("left", "down")
    assert parse(msg(type="text", backspace=2, insert="ö")) == Text(2, "ö")
    assert parse(msg(type="key", key="enter")) == Key("enter")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        msg(type="nope"),
        msg(dx=1),
        msg(type="hello", token="t"),  # no version
        msg(type="hello", v=2, token="t"),
        msg(type="move", dx=1.5, dy=0),
        msg(type="move", dx=True, dy=0),
        msg(type="move", dx=MAX_MOVE + 1, dy=0),
        msg(type="button", button="side", action="click"),
        msg(type="button", button="left", action="hold"),
        msg(type="text", backspace=-1, insert=""),
        msg(type="text", backspace=0, insert="x" * 1001),
        msg(type="text", backspace=0, insert=5),
        msg(type="key", key="F13"),
        msg(type="key", key=["enter"]),
    ],
)
def test_invalid_messages(raw: str) -> None:
    with pytest.raises(ProtocolError):
        parse(raw)
