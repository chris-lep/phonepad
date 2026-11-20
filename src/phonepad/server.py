"""HTTP + WebSocket server: serves the web app and turns messages into input events."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import ipaddress
import logging
import mimetypes
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import WSCloseCode, WSMsgType, web

from phonepad import __version__
from phonepad.auth import Device, Registry
from phonepad.input import InputService, InputUnavailableError
from phonepad.input.base import PointerBackend
from phonepad.jsonstore import StateFileError
from phonepad.network import NetworkError, NetworkSource, TrustStore, trusted_addresses
from phonepad.protocol import (
    CLOSE_BAD_MESSAGE,
    CLOSE_FORBIDDEN,
    CLOSE_UNAUTHENTICATED,
    PROTOCOL_VERSION,
    Button,
    ButtonEvent,
    Hello,
    Key,
    Message,
    Move,
    Pair,
    Ping,
    ProtocolError,
    Scroll,
    Text,
    encode,
    parse,
)

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
LOOPBACK = "127.0.0.1"
AUTH_TIMEOUT = 5.0
HOUSEKEEPING_INTERVAL = 3.0
HEARTBEAT = 5.0  # a vanished phone is noticed (and its buttons released) within ~10 s
MAX_PENDING_AUTH = 16  # unauthenticated WebSockets at a time
NETWORK_FAILURES_TOLERATED = 2  # nmcli errors in a row before LAN listeners are closed
MAX_MESSAGE = 16 * 1024
ERROR_REPEAT_AFTER = 5.0
CAPABILITIES = ("pointer", "scroll", "buttons", "keyboard", "ping")

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


@dataclass(eq=False)
class Session:
    ws: web.WebSocketResponse
    device: Device
    peer: str
    local_ip: str
    pressed: set[Button] = field(default_factory=set)
    last_error: tuple[str, float] = ("", 0.0)


Handler = Callable[[Session, Any], Awaitable[None]]


def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _release(button: Button, pointer: PointerBackend) -> None:
    pointer.button(button, False)


class PhonepadServer:
    def __init__(
        self,
        *,
        port: int,
        registry: Registry,
        trust: TrustStore,
        network: NetworkSource | None,
        inputs: InputService,
        extra_listen: tuple[str, ...] = (),
        advertise_host: str = "",
        static_dir: Path = STATIC_DIR,
    ) -> None:
        self.port = port
        self.registry = registry
        self.trust = trust
        self.network = network
        self.inputs = inputs
        self.extra_listen = extra_listen
        self.advertise_host = advertise_host
        self._pending_auth = 0
        self._network_failures = 0
        self._lan: set[str] = set()
        self.static_dir = static_dir
        self.sessions: set[Session] = set()
        self.sites: dict[str, web.TCPSite] = {}
        self.urls: dict[str, str] = {}
        self._runner: web.AppRunner | None = None
        self._housekeeping: asyncio.Task[None] | None = None
        self._network_problem = ""
        self._bind_problems: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._handlers: dict[type[Message], Handler] = {
            Move: self._on_move,
            Scroll: self._on_scroll,
            ButtonEvent: self._on_button,
            Text: self._on_text,
            Key: self._on_key,
            Ping: self._on_ping,
        }

    # --- app -----------------------------------------------------------------------------

    def make_app(self) -> web.Application:
        app = web.Application(middlewares=[self._check_host, self._headers])
        app.router.add_get("/", self._index)
        app.router.add_get("/manifest.webmanifest", self._file("manifest.webmanifest"))
        app.router.add_get("/ws", self._websocket)
        app.router.add_get("/api/status", self._status)
        app.router.add_static("/static/", self.static_dir, follow_symlinks=False)
        return app

    def _host_allowed(self, host: str) -> bool:
        """Only names this server is reachable under (blocks DNS rebinding)."""
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        name = name.strip("[]").lower()
        allowed = {"localhost", LOOPBACK, *self.sites, *self.extra_listen}
        if self.advertise_host:
            allowed.add(self.advertise_host.lower())
        return name in allowed

    @web.middleware
    async def _check_host(
        self, request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        if not self._host_allowed(request.host):
            log.warning("refused request for unknown host %r from %s", request.host, request.remote)
            raise web.HTTPMisdirectedRequest(text="unknown host")
        return await handler(request)

    @web.middleware
    async def _headers(
        self, request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        response = await handler(request)
        if request.path != "/ws":
            response.headers.setdefault("Cache-Control", "no-cache")
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                f"connect-src 'self' ws://{request.host}; manifest-src 'self'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            )
        return response

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(self.static_dir / "index.html")

    def _file(self, name: str) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
        async def handler(request: web.Request) -> web.StreamResponse:
            return web.FileResponse(self.static_dir / name)

        return handler

    async def _status(self, request: web.Request) -> web.StreamResponse:
        if not _is_loopback(request.remote):
            raise web.HTTPForbidden()
        return web.json_response(
            {
                "version": __version__,
                "urls": sorted(self.urls.values()),
                "lan": sorted(ip for ip in self.sites if not _is_loopback(ip)),
                "network_problem": self._network_problem,
                "pointer": self.inputs.pointer_name,
                "keyboard": self.inputs.keyboard_name,
                "input_error": self.inputs.last_error,
                "sessions": [
                    {"device": s.device.name, "peer": s.peer}
                    for s in sorted(self.sessions, key=lambda s: s.device.name)
                ],
                "pairing_pending": self.registry.pairing_pending(),
            }
        )

    # --- WebSocket -----------------------------------------------------------------------

    async def _websocket(self, request: web.Request) -> web.StreamResponse:
        origin = request.headers.get("Origin")
        if origin is not None and origin != f"{request.scheme}://{request.host}":
            log.warning("refused WebSocket from origin %s (host %s)", origin, request.host)
            raise web.HTTPForbidden(text="origin not allowed")

        if self._pending_auth >= MAX_PENDING_AUTH:
            raise web.HTTPServiceUnavailable(text="too many connections")

        ws = web.WebSocketResponse(heartbeat=HEARTBEAT, max_msg_size=MAX_MESSAGE)
        await ws.prepare(request)
        peer = request.remote or "?"
        sockname = request.transport.get_extra_info("sockname") if request.transport else None
        local_ip = sockname[0] if sockname else ""

        self._pending_auth += 1
        try:
            device = await self._authenticate(ws, peer)
        finally:
            self._pending_auth -= 1
        if device is None:
            return ws

        session = Session(ws, device, peer, local_ip)
        self.sessions.add(session)
        log.info("%s connected from %s", device.name, peer)
        try:
            await ws.send_str(
                encode(
                    "welcome",
                    v=PROTOCOL_VERSION,
                    server_version=__version__,
                    device={"id": device.id, "name": device.name},
                    capabilities=list(CAPABILITIES),
                )
            )
            self._spawn(self._prepare_pointer())
            await self._serve(session)
        finally:
            # aiohttp may cancel this handler when the phone goes away; the release must run
            # anyway, so it gets its own task.
            self.sessions.discard(session)
            self._spawn(self._release_buttons(session))
            log.info("%s disconnected (%s)", device.name, ws.close_code)
        return ws

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _authenticate(self, ws: web.WebSocketResponse, peer: str) -> Device | None:
        try:
            first = await asyncio.wait_for(ws.receive(), AUTH_TIMEOUT)
        except TimeoutError:
            await ws.close(code=CLOSE_UNAUTHENTICATED, message=b"authentication timeout")
            return None
        if first.type != WSMsgType.TEXT:
            await ws.close(code=CLOSE_UNAUTHENTICATED, message=b"authentication required")
            return None
        try:
            msg = parse(first.data)
        except ProtocolError as exc:
            await self._reject(ws, "bad_message", str(exc), CLOSE_BAD_MESSAGE)
            return None

        try:
            return await self._check_credentials(ws, peer, msg)
        except StateFileError as exc:
            log.error("%s", exc)
            await self._reject(
                ws,
                "server_error",
                "The laptop cannot read its device list.",
                WSCloseCode.INTERNAL_ERROR,
            )
            return None

    async def _check_credentials(
        self, ws: web.WebSocketResponse, peer: str, msg: Message
    ) -> Device | None:
        if isinstance(msg, Hello):
            device = await asyncio.to_thread(self.registry.authenticate, msg.token)
            if device is None:
                log.warning("unknown device token from %s", peer)
                await self._reject(ws, "unauthorized", "This phone is not paired.")
            return device
        if isinstance(msg, Pair):
            result = await asyncio.to_thread(
                self.registry.complete_pairing, msg.code, msg.name, msg.replaces
            )
            if result is None:
                log.warning("wrong or expired pairing code from %s", peer)
                await self._reject(
                    ws, "bad_code", "Wrong or expired code. Run `phonepad pair` for a new one."
                )
                return None
            device, token = result
            log.info("paired new device %s (%s) from %s", device.name, device.id, peer)
            await ws.send_str(
                encode("paired", token=token, device={"id": device.id, "name": device.name})
            )
            return device
        await self._reject(ws, "unauthorized", "authenticate first")
        return None

    async def _reject(
        self, ws: web.WebSocketResponse, code: str, message: str, close: int = CLOSE_UNAUTHENTICATED
    ) -> None:
        with contextlib.suppress(ConnectionError):
            await ws.send_str(encode("error", code=code, message=message))
        await ws.close(code=close, message=code.encode())

    async def _serve(self, session: Session) -> None:
        async for raw in session.ws:
            if raw.type != WSMsgType.TEXT:
                if raw.type == WSMsgType.ERROR:
                    log.warning("WebSocket error: %s", session.ws.exception())
                continue
            try:
                msg = parse(raw.data)
                handler = self._handlers.get(type(msg))
                if handler is None:
                    raise ProtocolError(f"unexpected message {msg.TYPE!r}")
            except ProtocolError as exc:
                log.warning("bad message from %s: %s", session.device.name, exc)
                await self._reject(session.ws, "bad_message", str(exc), CLOSE_BAD_MESSAGE)
                return
            try:
                await handler(session, msg)
            except InputUnavailableError as exc:
                await self._report(session, "input_unavailable", str(exc))

    async def _report(self, session: Session, code: str, message: str) -> None:
        """Send an error, but the same one at most every few seconds."""
        now = time.monotonic()
        last, when = session.last_error
        if message == last and now - when < ERROR_REPEAT_AFTER:
            return
        session.last_error = (message, now)
        with contextlib.suppress(ConnectionError):
            await session.ws.send_str(encode("error", code=code, message=message))

    # --- handlers ------------------------------------------------------------------------

    async def _prepare_pointer(self) -> None:
        with contextlib.suppress(InputUnavailableError):
            await self.inputs.new_session()

    async def _on_ping(self, session: Session, msg: Ping) -> None:
        await session.ws.send_str(encode("pong"))

    async def _on_move(self, session: Session, msg: Move) -> None:
        await self.inputs.pointer(lambda p: p.move(msg.dx, msg.dy))

    async def _on_scroll(self, session: Session, msg: Scroll) -> None:
        await self.inputs.pointer(lambda p: p.scroll(msg.dx, msg.dy))

    async def _on_button(self, session: Session, msg: ButtonEvent) -> None:
        button = msg.button
        if msg.action == "click":

            def click(p: Any) -> None:
                p.button(button, True)
                p.button(button, False)

            await self.inputs.pointer(click)
            session.pressed.discard(button)
            return
        pressed = msg.action == "down"
        await self.inputs.pointer(lambda p: p.button(button, pressed))
        if pressed:
            session.pressed.add(button)
        else:
            session.pressed.discard(button)

    async def _on_text(self, session: Session, msg: Text) -> None:
        def edit(k: Any) -> None:
            for _ in range(msg.backspace):
                k.key("backspace")
            if msg.insert:
                k.type_text(msg.insert)

        await self.inputs.keyboard(edit)

    async def _on_key(self, session: Session, msg: Key) -> None:
        await self.inputs.keyboard(lambda k: k.key(msg.key))

    async def _release_buttons(self, session: Session) -> None:
        # Another phone may still hold the same button; release only what no one else holds.
        held_elsewhere = {b for s in self.sessions for b in s.pressed}
        for button in session.pressed - held_elsewhere:
            with contextlib.suppress(InputUnavailableError):
                await self.inputs.pointer(functools.partial(_release, button))
        session.pressed.clear()

    # --- listeners and housekeeping --------------------------------------------------------

    async def start(self) -> None:
        await self.inputs.start()
        self._runner = web.AppRunner(self.make_app(), access_log=None, handle_signals=False)
        await self._runner.setup()
        await self._reconcile()
        if LOOPBACK not in self.sites:
            raise OSError(f"cannot listen on {LOOPBACK}:{self.port}")
        self._housekeeping = asyncio.create_task(self._housekeeping_loop())

    async def _housekeeping_loop(self) -> None:
        while True:
            await asyncio.sleep(HOUSEKEEPING_INTERVAL)
            try:
                await self._reconcile()
                await self._close_revoked()
            except Exception:
                log.exception("housekeeping failed")

    async def _desired_addresses(self) -> set[str]:
        desired = {LOOPBACK, *self.extra_listen}
        if self.network is None:
            return desired
        try:
            lan = await trusted_addresses(self.network, self.trust)
        except (NetworkError, StateFileError) as exc:
            # Tolerate a short hiccup (NetworkManager restarting, resume from suspend), then
            # fail closed: without NetworkManager we cannot tell whether the network is trusted.
            self._network_failures += 1
            if self._network_failures <= NETWORK_FAILURES_TOLERATED:
                log.warning("cannot check networks (%s), keeping the current listeners", exc)
                return desired | self._lan
            if str(exc) != self._network_problem:
                log.error("cannot check networks, not listening on the LAN: %s", exc)
            self._network_problem = str(exc)
            self._lan = set()
            return desired
        self._network_failures = 0
        self._network_problem = ""
        self._lan = lan
        return desired | lan

    async def _reconcile(self) -> None:
        assert self._runner is not None
        desired = await self._desired_addresses()
        for host in sorted(set(self.sites) - desired):
            await self._stop_site(host)
        for host in sorted(desired - set(self.sites)):
            await self._start_site(host)

    async def _start_site(self, host: str) -> None:
        assert self._runner is not None
        before = {tuple(a) for a in self._runner.addresses}
        site = web.TCPSite(self._runner, host, self.port, reuse_address=True)
        try:
            await site.start()
        except OSError as exc:
            if self._bind_problems.get(host) != str(exc):
                log.error("cannot listen on %s:%s: %s", host, self.port, exc)
            self._bind_problems[host] = str(exc)
            return
        self._bind_problems.pop(host, None)
        new = [tuple(a) for a in self._runner.addresses if tuple(a) not in before]
        port = new[0][1] if new else self.port
        self.sites[host] = site
        self.urls[host] = f"http://{host}:{port}/"
        log.info("listening on %s", self.urls[host])

    async def _stop_site(self, host: str) -> None:
        site = self.sites.pop(host)
        self.urls.pop(host, None)
        for session in [s for s in self.sessions if s.local_ip == host]:
            await session.ws.close(code=CLOSE_FORBIDDEN, message=b"network no longer trusted")
        await site.stop()
        log.info("stopped listening on %s", host)

    async def _close_revoked(self) -> None:
        if not self.sessions:
            return
        try:
            known = {d.id for d in await asyncio.to_thread(self.registry.devices)}
        except StateFileError as exc:
            log.error("not checking revocations: %s", exc)  # never disconnect on a read error
            return
        for session in [s for s in self.sessions if s.device.id not in known]:
            log.info("%s was revoked, disconnecting", session.device.name)
            await self._reject(session.ws, "revoked", "This phone was unpaired.", CLOSE_FORBIDDEN)

    async def stop(self) -> None:
        if self._housekeeping is not None:
            self._housekeeping.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._housekeeping
        for session in list(self.sessions):
            await session.ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")
        if self._tasks:  # pending button releases
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._runner is not None:
            await self._runner.cleanup()
        self.sites.clear()
        await self.inputs.close()


async def serve_forever(server: PhonepadServer) -> None:
    """Run until SIGINT/SIGTERM."""
    import signal

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await server.start()
    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        await server.stop()
