# State — resume here

_Last updated: 2026-11-20_

## Where things stand

- v0.1.0 has been built: touchpad (move, tap, tap-and-drag, two-finger scroll and right-click,
  L/R buttons), live typing with special keys, pairing, trusted networks, autostart, doctor.
- Verified by automated tests only: unit tests, an e2e run in headless Chrome with an
  emulated iPhone, and XTest typing in Xephyr. **Not yet tried on the real iPhone.**

## Next steps

1. Christopher runs `sudo scripts/setup-system.sh` (udev rule for `/dev/uinput`, ufw rule).
2. `phonepad trust` at home, `phonepad service install`, `phonepad pair`, then test on the
   iPhone, in Safari and as a home-screen app.
3. Tune the defaults (speed, acceleration, scroll speed, tap-and-drag window) from that test.

## Open questions for Christopher

- Does iOS still auto-capitalise the first letter with the invisible marker in front of the
  text field? If not: accept it, or find another way to detect Backspace on an empty field.

## Ideas (not scheduled)

Ordered by rough value for the sofa → TV use:

- **Media and volume keys**: play/pause, next, volume up/down/mute (uinput `KEY_*`, layout
  independent). Small: new keys in `keys.py` plus a panel.
- **Shortcut buttons**: configurable buttons (Alt+Tab, Super, F for fullscreen, Ctrl+W,
  browser back/forward) needing a "key with modifiers" message.
- **Three-finger gestures**: swipe for back/forward or workspaces, three-finger tap for middle
  click (the recognizer already ignores 3+ fingers).
- **Momentum scrolling** after a flick, and pinch to zoom (Ctrl+scroll).
- **mDNS host name** (`laptop.local`) and IPv6, so a new DHCP address does not break the
  home-screen app.
- **Presentation mode**: big next/previous buttons, blank screen, laser pointer overlay.
- **HTTPS with a local CA** installed on the iPhone: enables screen wake lock and motion sensors
  (an "air mouse"), and encrypts the token on the LAN (ADR-0004).
- **Wayland keyboard backend** (virtual-keyboard protocol, or uinput with xkbcommon) when
  Cinnamon on Wayland becomes the default (ADR-0003).
- **Clipboard sync** (phone ↔ laptop) and **send a URL** from the iPhone share sheet.
- **Cinnamon panel applet**: on/off switch, connected phones, "pair" button showing the QR
  code.
- **Multiple laptops**: one home-screen app per laptop already works; a picker could join them.
