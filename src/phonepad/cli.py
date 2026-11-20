"""Command line: `phonepad serve | pair | devices | revoke | trust | untrust | networks |
service | doctor`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from phonepad import __version__, service
from phonepad import config as config_mod
from phonepad.auth import Registry
from phonepad.doctor import fetch_status, print_checks, run_checks
from phonepad.network import (
    TRUSTABLE_TYPES,
    Connection,
    NetworkError,
    NmcliSource,
    TrustStore,
    trusted_addresses,
)
from phonepad.paths import state_dir

EXIT_CONFIG = 2  # bad settings or port in use: systemd does not restart (see service.py)


def _config(args: argparse.Namespace) -> config_mod.Config:
    try:
        return config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        print(f"phonepad: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG) from exc


# --- serve -----------------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    from phonepad.input import create_input_service
    from phonepad.server import PhonepadServer, serve_forever

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    cfg = _config(args)
    port = cfg.port if args.port is None else args.port
    state = state_dir()
    server = PhonepadServer(
        port=port,
        registry=Registry(state),
        trust=TrustStore(state),
        network=None if args.no_lan else NmcliSource(),
        inputs=create_input_service(
            cfg.pointer_backend, args.record_input, keymap_record=state / "keymap.json"
        ),
        extra_listen=tuple(args.listen),
        advertise_host=cfg.advertise_host,
    )
    try:
        asyncio.run(serve_forever(server))
    except OSError as exc:  # typically: the port is already in use
        logging.getLogger("phonepad").error("%s", exc)
        return EXIT_CONFIG
    return 0


# --- pairing and devices ----------------------------------------------------------------------


def _pairing_host(cfg: config_mod.Config) -> str | None:
    if cfg.advertise_host:
        return cfg.advertise_host
    try:
        addresses = asyncio.run(trusted_addresses(NmcliSource(), TrustStore(state_dir())))
    except NetworkError:
        return None
    return sorted(addresses)[0] if addresses else None


def cmd_pair(args: argparse.Namespace) -> int:
    cfg = _config(args)
    host = _pairing_host(cfg)
    if fetch_status(cfg.port) is None:
        print(
            f"Warning: no phonepad server answers on port {cfg.port}.\n"
            "Start it with `phonepad service install` (autostart) or `phonepad serve`.\n"
        )
    if host is None:
        print(
            "Warning: this laptop is not on a trusted network, so phones cannot reach it.\n"
            "Connect to your home network and run `phonepad trust` first.\n"
        )

    pairing = Registry(state_dir()).start_pairing()
    code = f"{pairing.code[:3]} {pairing.code[3:]}"
    minutes = round((pairing.expires_at - time.time()) / 60)
    if host is not None:
        url = f"http://{host}:{cfg.port}/#code={pairing.code}"
        try:
            import segno

            segno.make(url, error="m").terminal(compact=True)
        except Exception:
            pass
        print(f"\nScan the QR code with the phone's camera, or open {url.split('#')[0]}")
        print("Home-screen app on an iPhone: share menu > Add to Home Screen, then open it and")
        print("enter the code there (it does not share the browser's pairing).")
    print(f"\n  Pairing code: {code}   (valid {minutes} minutes, one phone)\n")
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    devices = Registry(state_dir()).devices()
    if not devices:
        print("No paired devices. Pair one with `phonepad pair`.")
        return 0
    print(f"{'ID':<10} {'NAME':<28} {'PAIRED':<26} LAST USED")
    for d in devices:
        print(f"{d.id:<10} {d.name[:28]:<28} {d.paired_at:<26} {d.last_used or '-'}")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    registry = Registry(state_dir())
    if args.all:
        print(f"Removed {registry.revoke_all()} device(s).")
        return 0
    if args.id is None:
        raise SystemExit("phonepad revoke: give a device ID (see `phonepad devices`) or --all")
    if registry.revoke(args.id):
        print(f"Removed {args.id}; it is disconnected within a few seconds.")
        return 0
    print(f"No device with ID {args.id}.", file=sys.stderr)
    return 1


# --- networks ---------------------------------------------------------------------------------


def _active() -> list[Connection]:
    try:
        return asyncio.run(NmcliSource().active_connections())
    except NetworkError as exc:
        raise SystemExit(f"phonepad: {exc}") from exc


def cmd_networks(args: argparse.Namespace) -> int:
    trusted = TrustStore(state_dir()).trusted()
    active = {c.uuid: c for c in _active()}
    print("Trusted networks:")
    if not trusted:
        print("  none (connect to your home network and run `phonepad trust`)")
    for uuid, name in trusted.items():
        state = "active" if uuid in active else "not connected"
        print(f"  {name}  ({uuid}, {state})")
    others = [c for c in active.values() if c.uuid not in trusted and c.type in TRUSTABLE_TYPES]
    if others:
        print("Other active networks:")
        for c in others:
            print(f"  {c.name}  ({c.uuid}, {c.device})")
    return 0


def cmd_trust(args: argparse.Namespace) -> int:
    active = _active()
    if args.uuid:
        candidates = [c for c in active if c.uuid == args.uuid]
        if not candidates:
            raise SystemExit(f"phonepad trust: no active connection with UUID {args.uuid}")
    else:
        candidates = [c for c in active if c.type in TRUSTABLE_TYPES]
    if not candidates:
        raise SystemExit("phonepad trust: no active Wi-Fi or Ethernet connection")
    if len(candidates) > 1:
        print("Several networks are active; choose one with --uuid:")
        for c in candidates:
            print(f"  {c.uuid}  {c.name} ({c.device})")
        return 1
    conn = candidates[0]
    if conn.type in ("802-3-ethernet", "ethernet") and not args.yes:
        print(
            f"{conn.name!r} is a wired connection profile. NetworkManager uses the same profile\n"
            "on every network you plug into, so trusting it trusts all of them.\n"
            "Run again with --yes if that is what you want."
        )
        return 1
    TrustStore(state_dir()).add(conn)
    print(f"Trusted {conn.name!r}. The server listens there within a few seconds.")
    if conn.type in ("802-11-wireless", "wifi"):
        print("Note: any Wi-Fi with the same name and password counts as this network.")
    return 0


def cmd_untrust(args: argparse.Namespace) -> int:
    removed = TrustStore(state_dir()).remove(args.network)
    if not removed:
        print(f"No trusted network named {args.network!r} (see `phonepad networks`).")
        return 1
    print(f"No longer trusted: {', '.join(removed)}")
    return 0


# --- service and doctor -----------------------------------------------------------------------


def cmd_service(args: argparse.Namespace) -> int:
    if args.action == "install":
        for path in service.install():
            print(f"wrote {path}")
        print("Started now and at every login. Logs: journalctl --user -u phonepad -f")
        return 0
    if args.action == "uninstall":
        for path in service.uninstall():
            print(f"removed {path}")
        return 0
    return service.status()


def cmd_doctor(args: argparse.Namespace) -> int:
    return print_checks(run_checks())


# --- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phonepad", description="Use a phone as touchpad and keyboard for this laptop."
    )
    parser.add_argument("--version", action="version", version=f"phonepad {__version__}")
    parser.add_argument(
        "--config", type=Path, default=None, help="settings file (default ~/.config/phonepad/…)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the server in the foreground")
    p.add_argument("--port", type=int, help="port (default from settings, 8790)")
    p.add_argument(
        "--listen",
        action="append",
        default=[],
        metavar="ADDR",
        help="also listen on ADDR, without the trusted-network check (development)",
    )
    p.add_argument("--no-lan", action="store_true", help="do not listen on trusted networks")
    p.add_argument(
        "--record-input",
        type=Path,
        metavar="FILE",
        help="write input events to FILE (JSON lines) instead of injecting them",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_serve)

    sub.add_parser("pair", help="show a pairing code and QR code").set_defaults(func=cmd_pair)
    sub.add_parser("devices", help="list paired devices").set_defaults(func=cmd_devices)

    p = sub.add_parser("revoke", help="unpair a device")
    p.add_argument("id", nargs="?", help="device ID from `phonepad devices`")
    p.add_argument("--all", action="store_true", help="unpair all devices")
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("trust", help="trust the current network")
    p.add_argument("--uuid", help="NetworkManager connection UUID (if several are active)")
    p.add_argument("--yes", action="store_true", help="also trust a wired connection profile")
    p.set_defaults(func=cmd_trust)

    p = sub.add_parser("untrust", help="stop trusting a network")
    p.add_argument("network", help="name or UUID from `phonepad networks`")
    p.set_defaults(func=cmd_untrust)

    sub.add_parser("networks", help="list trusted and active networks").set_defaults(
        func=cmd_networks
    )

    p = sub.add_parser("service", help="autostart at login (systemd user unit)")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.set_defaults(func=cmd_service)

    sub.add_parser("doctor", help="check the setup").set_defaults(func=cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
