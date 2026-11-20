from __future__ import annotations

from pathlib import Path

import pytest

from phonepad.config import Config, ConfigError, load


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load(tmp_path / "nope.toml") == Config()


def test_values(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('port = 9000\npointer_backend = "xtest"\nadvertise_host = "laptop.local"\n')
    assert load(path) == Config(9000, "xtest", "laptop.local")


@pytest.mark.parametrize(
    "text",
    ["port = 'x'", "port = 70000", "pointer_backend = 'mouse'", "colour = 1", "port ="],
)
def test_invalid(tmp_path: Path, text: str) -> None:
    path = tmp_path / "c.toml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        load(path)
