#!/usr/bin/env bash
# Run a command against a throwaway X server, never the real display.
#   scripts/with-test-display.sh pytest -m xserver
# Uses Xvfb (headless) if installed, else Xephyr (opens a small window briefly).
# Sets PHONEPAD_TEST_DISPLAY and DISPLAY for the command.
set -euo pipefail

if command -v Xvfb >/dev/null; then
  server=(Xvfb -screen 0 320x200x24 -nolisten tcp)
elif command -v Xephyr >/dev/null; then
  server=(Xephyr -screen 320x200 -nolisten tcp -br -noreset)
else
  echo "needs Xvfb (package xvfb) or Xephyr (package xserver-xephyr)" >&2
  exit 1
fi

n=90
while [[ -e /tmp/.X11-unix/X$n || -e /tmp/.X$n-lock ]]; do n=$((n + 1)); done
"${server[0]}" ":$n" "${server[@]:1}" >/dev/null 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT
for _ in $(seq 50); do
  [[ -e /tmp/.X11-unix/X$n ]] && break
  sleep 0.1
done
[[ -e /tmp/.X11-unix/X$n ]] || { echo "test X server did not start" >&2; exit 1; }
PHONEPAD_TEST_DISPLAY=":$n" DISPLAY=":$n" "$@"
