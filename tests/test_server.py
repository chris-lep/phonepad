from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient

from phonepad.auth import Registry
from phonepad.input import InputService
from phonepad.input.recording import Recorder, RecordingKeyboard, RecordingPointer
from phonepad.network import Connection, TrustStore
from phonepad.server import PhonepadServer

ClientFactory = Callable[[web.Application], Awaitable[TestClient[Any, Any]]]


class FakeSource:
    def __init__(self) -> None:
        self.active: list[Connection] = []
        self.addresses: dict[str, list[str]] = {}

    async def active_connections(self) -> list[Connection]:
        return self.active

    async def ipv4_addresses(self, device: str) -> list[str]:
        return self.addresses.get(device, [])


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
async def server(tmp_path: Path, recorder: Recorder) -> AsyncIterator[PhonepadServer]:
    inputs = InputService(lambda: RecordingPointer(recorder), lambda: RecordingKeyboard(recorder))
    srv = PhonepadServer(
        port=0,
        registry=Registry(tmp_path / "state"),
        trust=TrustStore(tmp_path / "state"),
        network=None,
        inputs=inputs,
    )
    yield srv
    await inputs.close()


@pytest.fixture
async def client(server: PhonepadServer, aiohttp_client: ClientFactory) -> TestClient[Any, Any]:
    return await aiohttp_client(server.make_app())


def paired_token(server: PhonepadServer, name: str = "Test phone") -> str:
    result = server.registry.complete_pairing(server.registry.start_pairing().code, name)
    assert result is not None
    return result[1]


async def connect(client: TestClient[Any, Any], token: str) -> Any:
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "hello", "v": 1, "token": token})
    welcome = await ws.receive_json()
    assert welcome["type"] == "welcome", welcome
    return ws


async def until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


# --- HTTP --------------------------------------------------------------------------------------


async def test_index_and_static_files_with_security_headers(client: TestClient[Any, Any]) -> None:
    resp = await client.get("/")
    assert resp.status == 200
    assert "<title>phonepad</title>" in await resp.text()
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert resp.headers["X-Content-Type-Options"] == "nosniff"

    js = await client.get("/static/js/main.js")
    assert js.status == 200
    # Both are JavaScript MIME types for module scripts (Python 3.11 reports the older one).
    assert js.content_type in ("text/javascript", "application/javascript")
    manifest = await client.get("/manifest.webmanifest")
    assert manifest.content_type == "application/manifest+json"
    assert (await client.get("/static/../server.py")).status in (403, 404)


async def test_status_only_from_loopback(client: TestClient[Any, Any]) -> None:
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert data["pointer"] == "none" and data["sessions"] == []


# --- authentication ----------------------------------------------------------------------------


async def test_pairing_over_websocket(server: PhonepadServer, client: TestClient[Any, Any]) -> None:
    code = server.registry.start_pairing().code
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "pair", "v": 1, "code": code, "name": "iPhone"})
    paired = await ws.receive_json()
    assert paired["type"] == "paired" and paired["device"]["name"] == "iPhone"
    welcome = await ws.receive_json()
    assert welcome["type"] == "welcome"
    assert "keyboard" in welcome["capabilities"]
    await ws.close()
    # The token works for the next connection.
    ws = await connect(client, paired["token"])
    await ws.close()


async def test_wrong_code_is_rejected(server: PhonepadServer, client: TestClient[Any, Any]) -> None:
    code = server.registry.start_pairing().code
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "pair", "v": 1, "code": "x" + code[1:], "name": "n"})
    err = await ws.receive_json()
    assert err == {"type": "error", "code": "bad_code", "message": err["message"]}
    closed = await ws.receive()
    assert closed.type == WSMsgType.CLOSE and closed.data == 4401


async def test_unknown_token_is_rejected(client: TestClient[Any, Any]) -> None:
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "hello", "v": 1, "token": "nope"})
    assert (await ws.receive_json())["code"] == "unauthorized"
    assert (await ws.receive()).data == 4401


async def test_input_before_authentication_is_rejected(
    client: TestClient[Any, Any], recorder: Recorder
) -> None:
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "move", "dx": 1, "dy": 1})
    assert (await ws.receive_json())["code"] == "unauthorized"
    assert (await ws.receive()).data == 4401
    assert recorder.events == []


async def test_authentication_times_out(
    client: TestClient[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("phonepad.server.AUTH_TIMEOUT", 0.05)
    ws = await client.ws_connect("/ws")
    assert (await ws.receive()).data == 4401


async def test_foreign_origin_is_refused(client: TestClient[Any, Any]) -> None:
    resp = await client.get(
        "/ws",
        headers={
            "Origin": "http://evil.example",
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        },
    )
    assert resp.status == 403


async def test_same_origin_is_allowed(server: PhonepadServer, client: TestClient[Any, Any]) -> None:
    token = paired_token(server)
    origin = f"http://{client.host}:{client.port}"
    ws = await client.ws_connect("/ws", origin=origin)
    await ws.send_json({"type": "hello", "v": 1, "token": token})
    assert (await ws.receive_json())["type"] == "welcome"
    await ws.close()


# --- input -------------------------------------------------------------------------------------


async def test_messages_become_input_events_in_order(
    server: PhonepadServer, client: TestClient[Any, Any], recorder: Recorder
) -> None:
    ws = await connect(client, paired_token(server))
    for message in (
        {"type": "move", "dx": 5, "dy": -3},
        {"type": "scroll", "dx": 0, "dy": 240},
        {"type": "button", "button": "right", "action": "click"},
        {"type": "text", "backspace": 2, "insert": "ä"},
        {"type": "key", "key": "enter"},
    ):
        await ws.send_json(message)
    await until(lambda: len(recorder.events) >= 8)
    await ws.close()
    assert recorder.events == [
        {"kind": "move", "dx": 5, "dy": -3},
        {"kind": "scroll", "dx": 0, "dy": 240},
        {"kind": "button", "button": "right", "pressed": True},
        {"kind": "button", "button": "right", "pressed": False},
        {"kind": "key", "key": "backspace"},
        {"kind": "key", "key": "backspace"},
        {"kind": "text", "text": "ä"},
        {"kind": "key", "key": "enter"},
    ]


async def test_held_buttons_are_released_on_disconnect(
    server: PhonepadServer, client: TestClient[Any, Any], recorder: Recorder
) -> None:
    ws = await connect(client, paired_token(server))
    await ws.send_json({"type": "button", "button": "left", "action": "down"})
    await until(lambda: len(recorder.events) == 1)
    await ws.close()
    await until(lambda: len(recorder.events) == 2)
    assert recorder.events[-1] == {"kind": "button", "button": "left", "pressed": False}


async def test_bad_message_closes_the_connection(
    server: PhonepadServer, client: TestClient[Any, Any]
) -> None:
    ws = await connect(client, paired_token(server))
    await ws.send_str(json.dumps({"type": "move", "dx": "far", "dy": 0}))
    assert (await ws.receive_json())["code"] == "bad_message"
    assert (await ws.receive()).data == 4400


async def test_unavailable_input_is_reported_not_fatal(
    tmp_path: Path, aiohttp_client: ClientFactory
) -> None:
    from phonepad.input import InputUnavailableError

    recorder = Recorder()

    def no_keyboard() -> Any:
        raise InputUnavailableError("cannot open X display")

    inputs = InputService(lambda: RecordingPointer(recorder), no_keyboard)
    srv = PhonepadServer(
        port=0,
        registry=Registry(tmp_path),
        trust=TrustStore(tmp_path),
        network=None,
        inputs=inputs,
    )
    client = await aiohttp_client(srv.make_app())
    ws = await connect(client, paired_token(srv))
    await ws.send_json({"type": "key", "key": "enter"})
    err = await ws.receive_json()
    assert err["code"] == "input_unavailable" and "X display" in err["message"]
    await ws.send_json({"type": "move", "dx": 1, "dy": 0})
    await until(lambda: len(recorder.events) == 1)
    await ws.close()
    await inputs.close()


async def test_revoked_device_is_disconnected(
    server: PhonepadServer, client: TestClient[Any, Any]
) -> None:
    ws = await connect(client, paired_token(server))
    await until(lambda: len(server.sessions) == 1)
    server.registry.revoke_all()
    await server._close_revoked()
    assert (await ws.receive_json())["code"] == "revoked"
    assert (await ws.receive()).data == 4403


# --- listeners ---------------------------------------------------------------------------------


async def test_listens_on_trusted_networks_only(tmp_path: Path, recorder: Recorder) -> None:
    source = FakeSource()
    home = Connection("uuid-home", "Home", "802-11-wireless", "wlan0")
    source.active = [home]
    source.addresses = {"wlan0": ["127.0.0.2"]}  # a loopback alias stands in for the LAN address
    inputs = InputService(lambda: RecordingPointer(recorder), lambda: RecordingKeyboard(recorder))
    srv = PhonepadServer(
        port=0,
        registry=Registry(tmp_path),
        trust=TrustStore(tmp_path),
        network=source,
        inputs=inputs,
    )
    await srv.start()
    try:
        assert set(srv.sites) == {"127.0.0.1"}  # not trusted yet
        srv.trust.add(home)
        await srv._reconcile()
        assert set(srv.sites) == {"127.0.0.1", "127.0.0.2"}
        assert srv.urls["127.0.0.2"].startswith("http://127.0.0.2:")
        source.active = []  # left the network
        await srv._reconcile()
        assert set(srv.sites) == {"127.0.0.1"}
    finally:
        await srv.stop()


# --- review fixes ------------------------------------------------------------------------------


async def test_unknown_host_is_refused(client: TestClient[Any, Any]) -> None:
    """DNS rebinding: a foreign name pointing at the laptop must not reach the app."""
    resp = await client.get("/", headers={"Host": "evil.example:8790"})
    assert resp.status == 421
    assert (await client.get("/", headers={"Host": "localhost"})).status == 200


async def test_ping_is_answered(server: PhonepadServer, client: TestClient[Any, Any]) -> None:
    ws = await connect(client, paired_token(server))
    await ws.send_json({"type": "ping"})
    assert await ws.receive_json() == {"type": "pong"}
    await ws.close()


async def test_too_many_unauthenticated_connections_are_refused(
    client: TestClient[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("phonepad.server.MAX_PENDING_AUTH", 1)
    first = await client.ws_connect("/ws")  # never authenticates
    resp = await client.get(
        "/ws",
        headers={
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        },
    )
    assert resp.status == 503
    await first.close()


async def test_repairing_over_websocket_replaces_the_old_device(
    server: PhonepadServer, client: TestClient[Any, Any]
) -> None:
    old = paired_token(server)
    code = server.registry.start_pairing().code
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "pair", "v": 1, "code": code, "name": "iPhone", "replaces": old})
    assert (await ws.receive_json())["type"] == "paired"
    await ws.close()
    assert [d.name for d in server.registry.devices()] == ["iPhone"]


async def test_unreadable_device_list_does_not_unpair_anyone(
    server: PhonepadServer, client: TestClient[Any, Any], tmp_path: Path
) -> None:
    ws = await connect(client, paired_token(server))
    await until(lambda: len(server.sessions) == 1)
    (tmp_path / "state" / "devices.json").write_text("{broken")
    await server._close_revoked()
    assert len(server.sessions) == 1  # still connected
    other = await client.ws_connect("/ws")
    await other.send_json({"type": "hello", "v": 1, "token": "x"})
    assert (await other.receive_json())["code"] == "server_error"
    await ws.close()


async def test_short_networkmanager_hiccups_keep_the_lan_listeners(
    tmp_path: Path, recorder: Recorder
) -> None:
    from phonepad.network import NetworkError

    class FlakySource(FakeSource):
        failing = False

        async def active_connections(self) -> list[Connection]:
            if self.failing:
                raise NetworkError("NetworkManager restarting")
            return self.active

    source = FlakySource()
    home = Connection("uuid-home", "Home", "802-11-wireless", "wlan0")
    source.active, source.addresses = [home], {"wlan0": ["127.0.0.3"]}
    inputs = InputService(lambda: RecordingPointer(recorder), lambda: RecordingKeyboard(recorder))
    srv = PhonepadServer(
        port=0,
        registry=Registry(tmp_path),
        trust=TrustStore(tmp_path),
        network=source,
        inputs=inputs,
    )
    srv.trust.add(home)
    await srv.start()
    try:
        assert "127.0.0.3" in srv.sites
        source.failing = True
        await srv._reconcile()
        await srv._reconcile()
        assert "127.0.0.3" in srv.sites  # tolerated
        await srv._reconcile()
        assert "127.0.0.3" not in srv.sites  # then fail closed
        source.failing = False
        await srv._reconcile()
        assert "127.0.0.3" in srv.sites
    finally:
        await srv.stop()
