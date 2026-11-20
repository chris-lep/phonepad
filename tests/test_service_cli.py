from __future__ import annotations

from pathlib import Path

import pytest

from phonepad import cli, service
from phonepad.network import Connection


def test_unit_file() -> None:
    text = service.unit_text("/home/me/miniconda3/envs/phonepad/bin/python")
    assert "ExecStart=/home/me/miniconda3/envs/phonepad/bin/python -m phonepad serve" in text
    assert "RestartPreventExitStatus=2" in text
    assert "StartLimitBurst=" in text
    quoted = service.unit_text("/home/me/my envs/python")
    assert 'ExecStart="/home/me/my envs/python" -m phonepad serve' in quoted


def test_autostart_imports_the_session_environment() -> None:
    text = service.autostart_text()
    assert "import-environment DISPLAY XAUTHORITY" in text
    assert "systemctl --user start phonepad.service" in text


def test_install_and_uninstall_write_only_user_files(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_systemctl", lambda *a: calls.append(a) or 0)
    written = service.install(python="/usr/bin/python3")
    assert all(str(p).startswith(str(isolated_home)) for p in written)
    assert service.installed()
    assert ("restart", "phonepad.service") in calls
    assert service.uninstall() == [service.autostart_path(), service.unit_path()]
    assert not service.installed()


def test_trusting_a_wired_profile_needs_confirmation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wired = Connection("uuid-wired", "Wired connection 1", "802-3-ethernet", "eth0")
    monkeypatch.setattr(cli, "_active", lambda: [wired])
    assert cli.main(["trust"]) == 1
    assert "every network" in capsys.readouterr().out
    assert cli.main(["trust", "--yes"]) == 0
    assert cli.main(["networks"]) == 0


def test_bad_settings_exit_with_status_2(isolated_home: Path) -> None:
    config = isolated_home / "bad.toml"
    config.write_text("port = 'x'")
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", str(config), "pair"])
    assert exc.value.code == cli.EXIT_CONFIG
