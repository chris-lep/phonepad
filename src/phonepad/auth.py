"""Paired devices and one-time pairing codes (see ADR-0004).

Device tokens are random 256-bit strings; only their SHA-256 hash is stored. Pairing codes are
6 digits, valid for `PAIRING_TTL` seconds and `PAIRING_TRIES` attempts, and are used once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from phonepad.jsonstore import JsonFile

PAIRING_TTL = 300.0
PAIRING_TRIES = 5
CODE_DIGITS = 6
LAST_USED_RESOLUTION = 60.0  # do not rewrite devices.json more often per device
MAX_NAME = 60


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def clean_name(name: str) -> str:
    """A printable, bounded device name."""
    printable = "".join(ch for ch in name if ch.isprintable()).strip()
    return printable[:MAX_NAME] or "Phone"


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    token_hash: str
    paired_at: str
    last_used: str | None = None

    @classmethod
    def from_json(cls, data: Any) -> Device | None:
        try:
            return cls(
                id=str(data["id"]),
                name=str(data["name"]),
                token_hash=str(data["token_hash"]),
                paired_at=str(data["paired_at"]),
                last_used=data.get("last_used"),
            )
        except (KeyError, TypeError, AttributeError):
            return None


@dataclass(frozen=True)
class PairingCode:
    code: str
    expires_at: float


class Registry:
    """Paired devices (`devices.json`) and the pending pairing code (`pairing.json`)."""

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time) -> None:
        self._devices = JsonFile(state_dir / "devices.json", lambda: {"devices": []})
        self._pairing = JsonFile(state_dir / "pairing.json", dict, strict=False)
        self._clock = clock

    # --- devices -------------------------------------------------------------------------

    def devices(self) -> list[Device]:
        data = self._devices.read()
        raw = data.get("devices", []) if isinstance(data, dict) else []
        return [d for d in (Device.from_json(item) for item in raw) if d is not None]

    def device(self, device_id: str) -> Device | None:
        return next((d for d in self.devices() if d.id == device_id), None)

    def authenticate(self, token: str) -> Device | None:
        """The device owning `token`, or None. Records the time of use."""
        if not token:
            return None
        wanted = _hash(token)
        match = next((d for d in self.devices() if hmac.compare_digest(d.token_hash, wanted)), None)
        if match is None:
            return None
        now = self._clock()
        if now - _parse_iso(match.last_used) >= LAST_USED_RESOLUTION:
            self._set_last_used(match.id, _iso(now))
        return match

    def _set_last_used(self, device_id: str, when: str) -> None:
        def change(data: dict[str, Any]) -> None:
            for item in _device_list(data):
                if item.get("id") == device_id:
                    item["last_used"] = when

        self._devices.update(change)

    def revoke(self, device_id: str) -> bool:
        def change(data: dict[str, Any]) -> bool:
            items = _device_list(data)
            kept = [item for item in items if item.get("id") != device_id]
            data["devices"] = kept
            return len(kept) != len(items)

        return self._devices.update(change)

    def revoke_all(self) -> int:
        def change(data: dict[str, Any]) -> int:
            count = len(_device_list(data))
            data["devices"] = []
            return count

        return self._devices.update(change)

    # --- pairing -------------------------------------------------------------------------

    def start_pairing(self) -> PairingCode:
        """Create a new pairing code, replacing any pending one."""
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        expires = self._clock() + PAIRING_TTL

        def change(data: dict[str, Any]) -> None:
            data.clear()
            data.update(
                {"code_hash": _hash(code), "expires_at": expires, "tries_left": PAIRING_TRIES}
            )

        self._pairing.update(change)
        return PairingCode(code, expires)

    def pairing_pending(self) -> bool:
        data = self._pairing.read()
        return bool(isinstance(data, dict) and data.get("expires_at", 0) > self._clock())

    def complete_pairing(
        self, code: str, name: str, replaces: str = ""
    ) -> tuple[Device, str] | None:
        """Exchange a valid code for a new device and its token; None if the code is wrong.

        `replaces` is the phone's previous token, if any: that device entry is removed, so
        re-pairing a phone does not leave stale entries behind.
        """
        now = self._clock()

        def check(data: dict[str, Any]) -> bool:
            if not data:
                return False
            expired = not isinstance(data.get("expires_at"), int | float) or (
                data["expires_at"] <= now
            )
            tries = data.get("tries_left", 0)
            if expired or not isinstance(tries, int) or tries <= 0:
                data.clear()
                return False
            if hmac.compare_digest(str(data.get("code_hash", "")), _hash(code)):
                data.clear()  # one use
                return True
            data["tries_left"] = tries - 1
            if data["tries_left"] <= 0:
                data.clear()
            return False

        if not self._pairing.update(check):
            return None

        token = secrets.token_urlsafe(32)
        device = Device(
            id=secrets.token_hex(4),
            name=clean_name(name),
            token_hash=_hash(token),
            paired_at=_iso(now),
            last_used=_iso(now),
        )

        old_hash = _hash(replaces) if replaces else None

        def add(data: dict[str, Any]) -> None:
            kept = [
                item
                for item in _device_list(data)
                if old_hash is None
                or not hmac.compare_digest(str(item.get("token_hash")), old_hash)
            ]
            data["devices"] = [*kept, asdict(device)]

        self._devices.update(add)
        return device, token


def _device_list(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    items = data.get("devices")
    if not isinstance(items, list):
        items = []
        data["devices"] = items
    return [item for item in items if isinstance(item, dict)]
