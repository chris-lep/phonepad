"""WebSocket messages between the web app and the server (see docs/SPEC.md, "Protocol").

Each message type is a frozen dataclass registered under its `type` string. To add a feature,
define a message here, handle it in the server and announce a capability in `welcome`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Self, TypeVar, cast

from phonepad.keys import KEYS

PROTOCOL_VERSION = 1
MAX_MOVE = 2000
MAX_SCROLL = 120 * 50
MAX_TEXT = 1000
MAX_SECRET = 200
MAX_NAME_LEN = 200

Button = Literal["left", "right", "middle"]
ButtonAction = Literal["down", "up", "click"]
BUTTONS: tuple[Button, ...] = ("left", "right", "middle")
BUTTON_ACTIONS: tuple[ButtonAction, ...] = ("down", "up", "click")

# Close codes (WebSocket application range 4000-4999).
CLOSE_BAD_MESSAGE = 4400
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


class ProtocolError(ValueError):
    """A message that does not follow the protocol."""


class Message:
    TYPE: ClassVar[str]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        raise NotImplementedError


MESSAGE_TYPES: dict[str, type[Message]] = {}
M = TypeVar("M", bound=type[Message])


def message(type_name: str) -> Callable[[M], M]:
    def register(cls: M) -> M:
        cls.TYPE = type_name
        MESSAGE_TYPES[type_name] = cls
        return cls

    return register


def _int(data: dict[str, Any], key: str, limit: int, *, low: int | None = None) -> int:
    value = data.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"{key} must be an integer")
    low = -limit if low is None else low
    if not low <= value <= limit:
        raise ProtocolError(f"{key} out of range")
    return value


def _str(data: dict[str, Any], key: str, limit: int) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ProtocolError(f"{key} must be a string")
    if len(value) > limit:
        raise ProtocolError(f"{key} too long")
    return value


def _check_version(data: dict[str, Any]) -> None:
    if data.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version (server speaks {PROTOCOL_VERSION})")


@message("hello")
@dataclass(frozen=True)
class Hello(Message):
    token: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        _check_version(data)
        return cls(_str(data, "token", MAX_SECRET))


@message("pair")
@dataclass(frozen=True)
class Pair(Message):
    code: str
    name: str
    replaces: str = ""  # the phone's previous token, removed on success

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        _check_version(data)
        code = "".join(_str(data, "code", 20).split())
        return cls(code, _str(data, "name", MAX_NAME_LEN), _str(data, "replaces", MAX_SECRET))


@message("ping")
@dataclass(frozen=True)
class Ping(Message):
    """Liveness check from the web app; answered with `pong`."""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls()


@message("move")
@dataclass(frozen=True)
class Move(Message):
    dx: int
    dy: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(_int(data, "dx", MAX_MOVE), _int(data, "dy", MAX_MOVE))


@message("scroll")
@dataclass(frozen=True)
class Scroll(Message):
    """Wheel units, 120 per notch. dy > 0 scrolls up, dx > 0 scrolls right (evdev signs)."""

    dx: int
    dy: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(_int(data, "dx", MAX_SCROLL), _int(data, "dy", MAX_SCROLL))


@message("button")
@dataclass(frozen=True)
class ButtonEvent(Message):
    button: Button
    action: ButtonAction

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        button, action = data.get("button"), data.get("action")
        if button not in BUTTONS:
            raise ProtocolError("unknown button")
        if action not in BUTTON_ACTIONS:
            raise ProtocolError("unknown button action")
        return cls(cast(Button, button), cast(ButtonAction, action))


@message("text")
@dataclass(frozen=True)
class Text(Message):
    """Press Backspace `backspace` times, then type `insert`."""

    backspace: int
    insert: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        backspace = _int(data, "backspace", MAX_TEXT, low=0)
        insert = _str(data, "insert", MAX_TEXT)
        return cls(backspace, insert)


@message("key")
@dataclass(frozen=True)
class Key(Message):
    key: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        key = data.get("key")
        if not isinstance(key, str) or key not in KEYS:
            raise ProtocolError("unknown key")
        return cls(key)


def parse(raw: str) -> Message:
    """Decode and validate one message."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError("not JSON") from exc
    if not isinstance(data, dict):
        raise ProtocolError("message must be an object")
    kind = data.get("type")
    cls = MESSAGE_TYPES.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise ProtocolError(f"unknown message type {kind!r}")
    return cls.from_json(data)


def encode(type_name: str, **fields: Any) -> str:
    return json.dumps({"type": type_name, **fields}, separators=(",", ":"))
