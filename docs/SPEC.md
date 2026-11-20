# phonepad — requirements and behaviour

What the app must do. This is the source of truth for behaviour: change it in the same commit
as the code. The reasons behind choices are in [decisions/](decisions/README.md). Requirements
agreed with Christopher on 2026-11-20 (interview).

## Purpose

Use an iPhone as touchpad and keyboard for the ThinkPad (Linux Mint, Cinnamon, X11). Main uses:
from the sofa while the laptop drives the TV over HDMI, and at the desk when the laptop is out
of reach. Nothing is installed on the phone: the laptop serves a web app that Safari opens,
ideally added to the home screen so it runs full screen.

## Parts

- **Server** (`phonepad serve`, Python): serves the web app, accepts one WebSocket per phone
  and turns its messages into input events on the laptop.
- **Web app** (`src/phonepad/static/`): touchpad, keyboard panel, pairing and settings screens.
- **CLI** (`phonepad …`): pairing, paired devices, trusted networks, autostart, diagnostics.

## Touchpad

| Gesture                                     | Result                                       |
| ------------------------------------------- | -------------------------------------------- |
| one finger moves                            | pointer moves (speed and acceleration below) |
| one-finger tap                              | left click                                   |
| tap, then touch again within 250 ms and move | left-button drag until the finger lifts (on by default, can be switched off) |
| two-finger tap                              | right click                                  |
| two fingers move                            | scroll, vertical and horizontal              |
| **L** / **R** buttons under the pad         | left / right button, held while pressed      |

- A tap is a touch that lasts under 250 ms and moves less than the slop (6 CSS px). Movement
  under the slop is not sent, so taps do not nudge the pointer.
- After a second finger touches down, lifting fingers does not move the pointer until all
  fingers are up (no jumps).
- Three or more fingers do nothing (reserved for later gestures).
- Pointer gain = speed × (1 + acceleration × min(max(v − 0.1, 0), 1.5)), where v is finger speed
  in CSS px per ms. Fractions carry over, so slow movement is not lost.
- Scrolling sends high-resolution wheel units (120 = one notch). Natural direction (content
  follows the fingers) is the default; settings can switch it.
- Movement and scrolling are combined per animation frame (at most about 60 messages per second).
  Clicks and keys first send any pending movement, so order is kept.
- When a phone disconnects, every button it was holding is released.

## Keyboard

- The keyboard button opens a text field and the iPhone keyboard. Typing is **live**: every
  change in the field is sent as "delete n characters, then type this text", computed from the
  common prefix of the old and new text in grapheme clusters. Autocorrect, predictions,
  dictation and editing in the middle of the field therefore end in the same text on the laptop.
- The field keeps an invisible marker (U+200B) in front of the text. Deleting it means
  Backspace on an empty field: the app sends Backspace and restores the marker.
- Return sends Enter and clears the field. Any click, button or special key also clears it, as
  the laptop's text cursor may have moved.
- A row of special keys: Esc, Tab, ←, ↑, ↓, →, Backspace, Enter.
- Any Unicode character can be typed (umlauts, ß, €, emoji), independent of the laptop's
  keyboard layout (`at,us`).
- Autocorrect and auto-capitalisation are on by default and can be switched off in settings.

## Settings (stored on the phone)

Pointer speed, acceleration, scroll speed, natural scrolling, tap-and-drag, autocorrect.
"Unpair this phone" deletes the phone's token. Settings and the token live in the page's local
storage; if they are lost the defaults apply and the phone must be paired again.

## Pairing and devices

- `phonepad pair` creates a one-time pairing code (6 digits, valid 5 minutes, at most 5 wrong
  tries, a new code replaces the old one). It prints the code and a QR code for
  `http://<laptop-ip>:<port>/#code=<code>`.
- Scanning the QR code opens the web app in Safari, which pairs at once. In the home-screen app
  (it has its own storage) the code is typed into the pairing screen instead.
- A successful pairing gives the phone a random device token (256 bit). The server stores only
  its SHA-256 hash with an id, name, pairing time and last-use time.
- `phonepad devices` lists paired devices; `phonepad revoke <id>` or `--all` removes them. A
  revoked phone is disconnected within seconds and sent back to the pairing screen.
- Every WebSocket must authenticate (token or pairing code) in its first message within
  5 seconds, else it is closed. WebSocket upgrades whose `Origin` does not match the `Host` are
  refused.

## Networks

- The server always listens on `127.0.0.1` (status and local testing).
- It listens on the LAN only on **trusted networks**: NetworkManager connections added with
  `phonepad trust` (stored by connection UUID). It binds only to the IPv4 addresses of those
  connections' devices, checks every 3 seconds, starts and stops listeners as networks come and
  go, and disconnects phones on a network that is no longer trusted.
- `phonepad networks` shows trusted and active connections; `phonepad untrust` removes one.
- The firewall (ufw) must allow the port from the home subnet; `scripts/setup-system.sh` adds
  that rule.

## Input on the laptop

- Pointer and scroll: a uinput virtual mouse (`phonepad virtual pointer`) with high-resolution
  wheels. Needs write access to `/dev/uinput` (udev rule from `scripts/setup-system.sh`).
  Without access the server falls back to XTest (scrolling then moves in whole notches).
- On X11 the server sets the virtual mouse to a flat acceleration profile and turns off natural
  scrolling for it (via `xinput`), as both are handled in the web app. It reapplies this when a
  phone connects, because Cinnamon may reset it.
- Keyboard: XTest. Characters are typed through spare keycodes that are temporarily mapped to
  the needed keysym (cached, least recently used first, restored on exit), so the layout does not
  matter. Special keys use the keyboard's own keycodes.
- The server does not need `DISPLAY` to start. The X connection is opened when first needed and
  reopened after errors.

## Running

- `phonepad service install` writes a systemd user unit and an XDG autostart entry that starts
  it at Cinnamon login (so the session's `DISPLAY` is set). `phonepad service uninstall` removes
  both. Logs: `journalctl --user -u phonepad`.
- `phonepad serve` runs it in the foreground. Options: `--port`, `--listen ADDR` (extra address,
  not checked against trusted networks, for development), `--record-input FILE` (write input
  events as JSON lines instead of injecting them).
- `phonepad doctor` checks uinput access, X and XTest, `xinput`, NetworkManager, trusted
  networks, the running server and paired devices, and says how to fix each problem.
- Settings file (optional, TOML): `~/.config/phonepad/config.toml` with `port` (default 8790),
  `pointer_backend` (`auto`, `uinput`, `xtest`) and `advertise_host` (host for the pairing
  URL). State: `~/.local/state/phonepad/` (`devices.json`, `networks.json`, `pairing.json`,
  mode 0600).

## Protocol (WebSocket `/ws`, JSON text messages)

Phone to laptop:

| Message                                                | Meaning                                      |
| ------------------------------------------------------ | -------------------------------------------- |
| `{"type":"hello","v":1,"token":"…"}`                   | authenticate with a device token             |
| `{"type":"pair","v":1,"code":"123456","name":"…"}`     | authenticate with a pairing code             |
| `{"type":"move","dx":3,"dy":-2}`                       | relative pointer move (integers, ±2000)      |
| `{"type":"scroll","dx":0,"dy":240}`                    | wheel units; `dy` > 0 scrolls up, `dx` > 0 right |
| `{"type":"button","button":"left","action":"down"}`   | `left`/`right`/`middle`; `down`/`up`/`click` |
| `{"type":"text","backspace":2,"insert":"ö"}`           | delete, then type (each at most 1000)        |
| `{"type":"key","key":"enter"}`                         | special key (list in `phonepad/keys.py`)     |

Laptop to phone: `welcome` (`v`, `server_version`, `device`, `capabilities`), `paired`
(`token`, `device`), `error` (`code`, `message`). Close codes: 4400 bad message, 4401 not
authenticated, 4403 revoked or network no longer trusted. Unknown message types are errors;
the welcome's `capabilities` list tells the app which features the server has, so new features
can be added on both sides independently.
