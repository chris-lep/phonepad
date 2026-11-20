# AGENTS.md — phonepad

iPhone as touchpad and keyboard for a Linux laptop (developed on Linux Mint, Cinnamon, X11). A
Python server (aiohttp) serves a no-build web app and turns WebSocket messages into input
events (uinput pointer, XTest keyboard). Main use: from the sofa, with the laptop on the TV.

## Start here

1. [docs/STATE.md](docs/STATE.md): current state, next steps, open questions, ideas. Read it first.
2. [docs/SPEC.md](docs/SPEC.md): requirements, behaviour and the protocol.
3. [docs/decisions/](docs/decisions/README.md): decision records (why it is built this way).
4. [docs/worklog.md](docs/worklog.md): dated history of sessions (read on demand).
5. [CHANGELOG.md](CHANGELOG.md): user-visible changes per release.

## Commands

```bash
conda activate phonepad          # Python 3.12 env, package installed editable
make check                       # ruff format+lint, mypy, Biome, pytest, node unit + e2e
make xtest                       # XTest typing against a throwaway X server (Xvfb, or Xephyr window)
make fmt                         # apply formatting (ruff, Biome)
phonepad serve --no-lan --port 0 --record-input /tmp/ev.jsonl   # safe local run, no real input
```

First-time setup: see [README.md](README.md#development).

## Layout

- `src/phonepad/`: `server.py` (HTTP, WebSocket sessions, trusted-network listeners),
  `protocol.py` (message registry + validation), `keys.py` (special keys), `auth.py` (pairing
  codes, device tokens), `network.py` (nmcli, trusted networks), `jsonstore.py` (locked atomic
  state files), `config.py`, `paths.py`, `service.py` (autostart), `doctor.py`, `cli.py`.
- `src/phonepad/input/`: `base.py` (backend protocols), `uinput.py`, `xtest.py`,
  `xinput_tuning.py`, `recording.py`, `__init__.py` (`InputService`: one input thread, factory).
- `src/phonepad/static/`: `js/gestures.js`, `js/motion.js`, `js/typing.js` (pure, unit-tested),
  `js/connection.js` (WebSocket, auth, reconnect), `js/settings.js`, `js/main.js` (DOM wiring).
- `tests/`: Python (`test_*.py`), `js/` (node:test), `e2e/` (real server + headless Chrome).
- `.github/workflows/ci.yml`: lint, types, unit, e2e and XTest tests (Xvfb) on every push.
- `scripts/`: `setup-system.sh` (sudo: udev + ufw; run by the user, never by an agent), `with-test-display.sh`,
  `make_icons.py`.

## Adding a feature (extension points)

- New message: a dataclass with `@message("name")` in `protocol.py`, a handler registered in
  `PhonepadServer._handlers`, a capability string in `CAPABILITIES`; the web app checks
  `connection.capabilities` before showing the feature. Update the protocol table in SPEC.
- New special key: one line in `keys.py` (X keysym + evdev name).
- New input backend (e.g. Wayland keyboard): implement the protocol in `input/base.py` and
  choose it in `create_input_service`.

## Hard rules

- **Never inject real input into the developer's desktop** from tests or experiments: it could
  type into their terminal. Use `--record-input`, the recording backends or `make xtest`.
- **No system changes without the owner's approval** (apt, sudo, `/etc`, udev, ufw). System
  steps go into `scripts/setup-system.sh` and the README for the user to run.
- Keep the security model (ADR-0004, ADR-0005): authenticate in the first message, LAN only on
  trusted networks, Origin check, only token hashes on disk, files mode 0600.
- Runtime dependencies stay small (aiohttp, evdev, python-xlib, segno); the frontend has no
  build step and no third-party code.
- Gesture, motion or typing changes need unit tests in `tests/js/`; DOM wiring changes in
  `main.js` need the e2e test to cover them.
- Commits: Conventional Commits; `make check` green before committing.

## Gotchas

- `page.goto(sameUrl#hash)` in Puppeteer does not reload the page; the app handles
  `hashchange` for QR links for the same reason.
- Pointer acceleration lives in the web app; the uinput mouse is set to libinput's flat
  profile via `xinput`. Do not add a second curve on the server.
- python-xlib is not thread-safe: every X call goes through the single `InputService` thread.

## Keeping the docs alive (agent workflow)

| Event                                          | Update                         | Notes                                                    |
| ---------------------------------------------- | ------------------------------ | -------------------------------------------------------- |
| Behaviour or requirement changes               | `docs/SPEC.md`                 | Same commit as the code.                                 |
| Decision with real alternatives, or a reversal | new `docs/decisions/NNNN-*.md` | Copy `adr-template.md`; add it to the index.             |
| User-visible change                            | `CHANGELOG.md` → `Unreleased`  | Keep a Changelog format.                                 |
| Every working session                          | append `docs/worklog.md`       | Date, what, why, how verified, review outcomes.          |
| End of session / handoff                       | `docs/STATE.md`                | Resume-here, open questions, backlog. Then commit.       |
| A mistake worth not repeating                  | Gotchas above                  | At most 3 lines each.                                    |

- One fact lives in one place; link to it instead of copying it.
- The project owner decides scope and behaviour. Record those decisions as ADRs
  (`decision-makers`), and list open questions in STATE.md rather than deciding them silently.
