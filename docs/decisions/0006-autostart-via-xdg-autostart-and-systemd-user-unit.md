---
status: accepted
date: 2026-11-20
decision-makers: project owner
---

# Autostart: XDG autostart entry starts a systemd user unit

## Context and Problem Statement

The owner wants the server running after login without a terminal. XTest needs `DISPLAY`
and `XAUTHORITY`, which the systemd user manager only has after the X session has started.
`graphical-session.target` is not active under Cinnamon.

## Considered Options

- XDG autostart entry that runs `systemctl --user start phonepad`
- systemd unit `WantedBy=default.target` (starts before the session, without `DISPLAY`)
- XDG autostart entry that runs the server directly

## Decision Outcome

Chosen option: "autostart entry starts the systemd unit": it starts after Cinnamon has
exported its environment, and systemd adds restart on failure and journald logs. Units do not
inherit the caller's environment; on Mint `/etc/X11/Xsession.d/95dbus_update-activation-env`
exports `DISPLAY` to the user manager, and the autostart entry also runs
`systemctl --user import-environment DISPLAY XAUTHORITY` first, so it does not depend on that.
`phonepad service install` writes both files with the current Python interpreter's path.
