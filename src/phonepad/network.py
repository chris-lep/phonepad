"""Trusted networks (see ADR-0005): which addresses the server may listen on."""

from __future__ import annotations

import asyncio
import ipaddress
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from phonepad.jsonstore import JsonFile

NMCLI_TIMEOUT = 5.0
TRUSTABLE_TYPES = frozenset({"802-11-wireless", "802-3-ethernet", "wifi", "ethernet"})


@dataclass(frozen=True)
class Connection:
    """An active NetworkManager connection."""

    uuid: str
    name: str
    type: str
    device: str


class NetworkError(RuntimeError):
    """NetworkManager could not be queried."""


class NetworkSource(Protocol):
    async def active_connections(self) -> list[Connection]: ...

    async def ipv4_addresses(self, device: str) -> list[str]: ...


def split_terse(line: str) -> list[str]:
    r"""Split one line of `nmcli -t` output (fields separated by ':', '\:' and '\\' escaped)."""
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def parse_active_connections(output: str) -> list[Connection]:
    result = []
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) == 4 and fields[0]:
            result.append(Connection(*fields))
    return result


def parse_ipv4_addresses(output: str) -> list[str]:
    """Addresses from `nmcli -g IP4.ADDRESS device show` ("10.0.0.8/24 | 10.0.0.9/24")."""
    result = []
    for part in output.replace("\n", "|").split("|"):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(str(ipaddress.IPv4Interface(part).ip))
        except ValueError:
            continue
    return result


class NmcliSource:
    """Reads NetworkManager state through the `nmcli` command."""

    def __init__(self, nmcli: str | None = None) -> None:
        self._nmcli = nmcli or shutil.which("nmcli") or "nmcli"

    async def _run(self, *args: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._nmcli,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise NetworkError(f"cannot run nmcli: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(), NMCLI_TIMEOUT)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise NetworkError("nmcli timed out") from exc
        if proc.returncode != 0:
            raise NetworkError(f"nmcli {' '.join(args)}: {err.decode(errors='replace').strip()}")
        return out.decode(errors="replace")

    async def active_connections(self) -> list[Connection]:
        out = await self._run("-t", "-f", "UUID,NAME,TYPE,DEVICE", "connection", "show", "--active")
        return parse_active_connections(out)

    async def ipv4_addresses(self, device: str) -> list[str]:
        if not device:
            return []
        return parse_ipv4_addresses(await self._run("-g", "IP4.ADDRESS", "device", "show", device))


class TrustStore:
    """Trusted NetworkManager connections (`networks.json`), keyed by connection UUID."""

    def __init__(self, state_dir: Path) -> None:
        self._file = JsonFile(state_dir / "networks.json", lambda: {"trusted": {}})

    def trusted(self) -> dict[str, str]:
        """UUID -> name at the time it was trusted."""
        raw = self._file.read().get("trusted", {})
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def add(self, connection: Connection) -> None:
        def change(data: dict[str, Any]) -> None:
            trusted = data.get("trusted")
            if not isinstance(trusted, dict):
                trusted = data["trusted"] = {}
            trusted[connection.uuid] = connection.name

        self._file.update(change)

    def remove(self, key: str) -> list[str]:
        """Remove trusted connections whose UUID or name is `key`; returns the removed names."""

        def change(data: dict[str, Any]) -> list[str]:
            trusted = data.get("trusted")
            if not isinstance(trusted, dict):
                return []
            gone = [uuid for uuid, name in trusted.items() if key in (uuid, name)]
            return [trusted.pop(uuid) for uuid in gone]

        return self._file.update(change)


async def trusted_addresses(source: NetworkSource, store: TrustStore) -> set[str]:
    """IPv4 addresses of the devices of currently active trusted connections."""
    trusted = store.trusted()
    if not trusted:
        return set()
    addresses: set[str] = set()
    for conn in await source.active_connections():
        if conn.uuid in trusted:
            addresses.update(await source.ipv4_addresses(conn.device))
    return addresses
