from __future__ import annotations

import json
import stat
from pathlib import Path

from phonepad.auth import PAIRING_TRIES, PAIRING_TTL, Registry, clean_name
from tests.conftest import Clock


def test_pairing_issues_a_token_that_authenticates(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    code = reg.start_pairing().code
    assert len(code) == 6 and code.isdigit()

    result = reg.complete_pairing(code, "iPhone")
    assert result is not None
    device, token = result
    assert reg.authenticate(token) == reg.device(device.id)
    assert reg.authenticate("wrong") is None
    assert reg.authenticate("") is None


def test_only_the_token_hash_is_stored_and_files_are_private(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    _, token = reg.complete_pairing(reg.start_pairing().code, "x") or ("", "")
    text = (tmp_path / "devices.json").read_text()
    assert token not in text
    for name in ("devices.json", "pairing.json"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def test_code_is_single_use(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    code = reg.start_pairing().code
    assert reg.complete_pairing(code, "a") is not None
    assert reg.complete_pairing(code, "b") is None
    assert len(reg.devices()) == 1


def test_code_expires(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    code = reg.start_pairing().code
    assert reg.pairing_pending()
    clock.now += PAIRING_TTL + 1
    assert not reg.pairing_pending()
    assert reg.complete_pairing(code, "a") is None


def test_code_dies_after_too_many_wrong_tries(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    code = reg.start_pairing().code
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(PAIRING_TRIES):
        assert reg.complete_pairing(wrong, "a") is None
    assert reg.complete_pairing(code, "a") is None


def test_new_code_replaces_old(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    first = reg.start_pairing().code
    second = reg.start_pairing().code
    if first != second:
        assert reg.complete_pairing(first, "a") is None
    assert reg.complete_pairing(second, "a") is not None


def test_revoke(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    d1, t1 = reg.complete_pairing(reg.start_pairing().code, "one") or (None, "")
    d2, t2 = reg.complete_pairing(reg.start_pairing().code, "two") or (None, "")
    assert d1 is not None and d2 is not None
    assert reg.revoke(d1.id)
    assert not reg.revoke(d1.id)
    assert reg.authenticate(t1) is None
    assert reg.authenticate(t2) is not None
    assert reg.revoke_all() == 1
    assert reg.devices() == []


def test_last_used_is_updated_at_most_once_a_minute(tmp_path: Path, clock: Clock) -> None:
    reg = Registry(tmp_path, clock)
    device, token = reg.complete_pairing(reg.start_pairing().code, "a") or (None, "")
    assert device is not None
    first = device.last_used
    clock.now += 30
    reg.authenticate(token)
    assert reg.devices()[0].last_used == first
    clock.now += 60
    reg.authenticate(token)
    assert reg.devices()[0].last_used != first


def test_corrupt_files_read_as_empty(tmp_path: Path, clock: Clock) -> None:
    (tmp_path / "devices.json").write_text("{not json")
    (tmp_path / "pairing.json").write_text("[1, 2]")
    reg = Registry(tmp_path, clock)
    assert reg.devices() == []
    assert not reg.pairing_pending()
    assert reg.complete_pairing(reg.start_pairing().code, "a") is not None
    assert len(json.loads((tmp_path / "devices.json").read_text())["devices"]) == 1


def test_clean_name() -> None:
    assert clean_name("  iPhone\x00\n ") == "iPhone"
    assert clean_name("") == "Phone"
    assert len(clean_name("x" * 500)) == 60
