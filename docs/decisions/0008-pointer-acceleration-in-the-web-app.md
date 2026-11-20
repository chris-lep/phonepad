---
status: accepted
date: 2026-11-20
decision-makers: Christopher Lepenik
---

# Pointer acceleration in the web app, flat profile on the laptop

## Context and Problem Statement

libinput accelerates relative motion of the uinput mouse as if it were a real mouse, while the
XTest fallback is not accelerated. Two curves on top of each other are hard to tune.

## Decision Outcome

The web app applies one curve (speed and acceleration, see SPEC) using the touch timestamps,
and the server sets the virtual mouse to libinput's flat profile with natural scrolling off
(`xinput set-prop`). The feel is then the same for both backends and tunable on the phone.
Cinnamon may reset device properties when it sees a new device, so the server reapplies them
whenever a phone connects.
