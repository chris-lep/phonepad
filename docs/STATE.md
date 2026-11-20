# State — resume here

_Last updated: 2026-11-20_

## Where things stand

- v0.1.0 has been built: touchpad (move, tap, tap-and-drag, two-finger scroll and right-click,
  L/R buttons), live typing with special keys, pairing, trusted networks, autostart, doctor.
- An independent review (2026-11-20) found no way to inject input without a token and 5 major
  plus 22 minor problems; all are fixed or recorded (see the worklog).
- Verified by automated tests (unit, e2e in headless Chrome with an emulated iPhone incl. a
  server restart, XTest typing against a separate X server incl. bursts and crash leftovers;
  CI runs all of them) and by a first test on the owner's iPhone on 2026-11-20: setup,
  pairing in Vivaldi and as home-screen app, touchpad. The open questions below are still
  unchecked.
- Prepared for publication on GitHub: MIT license, README for new users, CI.

## Next steps

1. Use it for a while and answer the open questions below; try it on an Android phone.
2. Tune the defaults (speed, acceleration, scroll speed, tap-and-drag window) from that.
3. After the first push: check that CI passes on GitHub.

## Open questions for the owner

Need real phones to answer:

- Does iOS still auto-capitalise the first letter with the invisible marker in front of the
  text field? If not: accept it, or find another way to detect Backspace on an empty field.
- Does Return with a pending autocorrection send the corrected word before Enter (50 ms delay)?
- Does dictation keep running when the field restores the marker?
- Is the tap-and-drag window (250 ms) comfortable, or does it start drags by accident?
- Android (untested): does typing work with Gboard and other keyboards (composition, Enter
  reported as a key), and how does the home-screen shortcut behave over plain HTTP?

## Backlog (from review, not scheduled)

- Type characters the active layout already has through their own keycodes (needs the XKB
  group), so most typing causes no keymap changes at all (ADR-0003).
- Pin trusted networks to the gateway MAC or Wi-Fi BSSID (ADR-0005).

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
- **HTTPS with a local CA** installed on the phone: enables screen wake lock and motion sensors
  (an "air mouse"), and encrypts the token on the LAN (ADR-0004).
- **Wayland keyboard backend** (virtual-keyboard protocol, or uinput with xkbcommon) when
  Cinnamon on Wayland becomes the default (ADR-0003).
- **Clipboard sync** (phone ↔ laptop) and **send a URL** from the phone's share menu.
- **Cinnamon panel applet**: on/off switch, connected phones, "pair" button showing the QR
  code.
- **Multiple laptops**: one home-screen app per laptop already works; a picker could join them.
