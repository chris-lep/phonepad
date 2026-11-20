from __future__ import annotations

from pathlib import Path

from phonepad.network import (
    Connection,
    TrustStore,
    parse_active_connections,
    parse_ipv4_addresses,
    split_terse,
    trusted_addresses,
)

HOME = Connection("uuid-home", "Home: 5G", "802-11-wireless", "wlp0s20f3")
DOCKER = Connection("uuid-docker", "docker0", "bridge", "docker0")


class FakeSource:
    def __init__(self, active: list[Connection], addresses: dict[str, list[str]]) -> None:
        self.active = active
        self.addresses = addresses

    async def active_connections(self) -> list[Connection]:
        return self.active

    async def ipv4_addresses(self, device: str) -> list[str]:
        return self.addresses.get(device, [])


def test_split_terse_handles_escapes() -> None:
    assert split_terse(r"a\:b:c\\d:") == ["a:b", "c\\d", ""]


def test_parse_active_connections() -> None:
    out = (
        "uuid-home:Home\\: 5G:802-11-wireless:wlp0s20f3\n"
        "uuid-docker:docker0:bridge:docker0\nbroken line\n"
    )
    assert parse_active_connections(out) == [HOME, DOCKER]


def test_parse_ipv4_addresses() -> None:
    assert parse_ipv4_addresses("10.0.0.8/24 | 192.168.1.2/16\n") == ["10.0.0.8", "192.168.1.2"]
    assert parse_ipv4_addresses("\n") == []
    assert parse_ipv4_addresses("garbage") == []


def test_trust_store_add_remove(tmp_path: Path) -> None:
    store = TrustStore(tmp_path)
    assert store.trusted() == {}
    store.add(HOME)
    assert store.trusted() == {"uuid-home": "Home: 5G"}
    assert store.remove("Home: 5G") == ["Home: 5G"]
    store.add(HOME)
    assert store.remove("uuid-home") == ["Home: 5G"]
    assert store.remove("nothing") == []


async def test_trusted_addresses_only_for_trusted_active_connections(tmp_path: Path) -> None:
    store = TrustStore(tmp_path)
    source = FakeSource([HOME, DOCKER], {"wlp0s20f3": ["10.0.0.8"], "docker0": ["172.17.0.1"]})
    assert await trusted_addresses(source, store) == set()
    store.add(HOME)
    assert await trusted_addresses(source, store) == {"10.0.0.8"}
    source.active = [DOCKER]
    assert await trusted_addresses(source, store) == set()
