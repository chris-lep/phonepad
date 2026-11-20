---
status: accepted
date: 2026-11-20
decision-makers: project owner
---

# A web app served from the laptop, with an aiohttp server

## Context and Problem Statement

The phone needs a touch surface that sends events to the laptop with low latency. KDE Connect
pulls in about 160 packages (140 MB); Unified Remote is closed source. The owner chose to
build it, without an App Store app.

## Considered Options

- Web app in the phone's browser (or as home-screen web app) + Python server with WebSocket
  (aiohttp)
- The same, with a standard-library server and a hand-written WebSocket implementation
- Native phone app (iOS / Android)

## Decision Outcome

Chosen option: "web app + aiohttp", because every phone has a browser, a home-screen web
app runs full screen like an app (on iOS), and WebSocket gives one ordered, low-latency channel.
aiohttp serves the static files and the WebSocket from one asyncio server and handles
heartbeats, so no protocol code is hand-written. The frontend is plain ES modules without a
build step; pure logic (gestures, typing diff, acceleration) is unit-tested with `node:test`.

### Consequences

- Good, because nothing is installed on the phone and updates are a server restart.
- Good, because four small runtime dependencies (aiohttp, evdev, python-xlib, segno) replace a
  desktop stack.
- Bad, because mobile browsers allow some APIs only over HTTPS (wake lock, motion sensors);
  see ADR-0004.
