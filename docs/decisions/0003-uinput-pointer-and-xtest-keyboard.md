---
status: accepted
date: 2026-11-20
decision-makers: Christopher Lepenik
---

# uinput for the pointer, XTest for the keyboard, behind backend interfaces

## Context and Problem Statement

Input must reach every application. Scrolling should be smooth, typing must handle any
character on an `at,us` layout, and a later switch of Cinnamon to Wayland should not mean a
rewrite.

## Considered Options

- uinput pointer + XTest keyboard
- XTest for everything (X11 only, no sudo, scrolling in notches)
- uinput for everything (typing limited to the active layout, needs a layout mapping)

## Decision Outcome

Chosen option: "uinput pointer + XTest keyboard" (Christopher, interview). The uinput mouse
has high-resolution wheels (pixel-smooth scrolling) and works on Wayland. XTest types any
character by temporarily mapping a spare keycode to the needed keysym, so the layout does not
matter. Both sit behind the `PointerBackend` / `KeyboardBackend` protocols in
`phonepad/input/`, chosen by a factory; a recording backend serves tests.

### Consequences

- Good, because a Wayland keyboard backend (virtual-keyboard protocol or uinput with
  xkbcommon) can be added later without touching the server or web app.
- Good, because the server falls back to an XTest pointer when `/dev/uinput` is not writable.
- Bad, because `/dev/uinput` needs a udev rule (`TAG+="uaccess"`), set up once with sudo. Any
  process of the logged-in user can then create input devices; on X11 any such process could
  already inject input through XTest, so the risk does not grow in practice.
- Bad, because remapping keycodes sends MappingNotify to all X clients. Spare keycodes are
  cached (least recently used first), so remaps happen only for new characters.

### Changes after review (2026-11-20)

- Remapping a keycode that clients have not processed yet garbled bursts of more distinct
  characters than spare keycodes (found in review with Xephyr). A keycode pressed less than
  100 ms ago is now remapped only after that wait.
- Claimed keycodes are recorded in `keymap.json`, so leftovers from a crash are reclaimed.
  Guessing leftovers from the keymap's shape was rejected: real keys such as BackSpace and the
  F-keys have the same repeated keysym in their first columns.
- Not done yet: typing characters that the active layout already has through their own
  keycodes (needs the active XKB group); that would avoid most remaps.
