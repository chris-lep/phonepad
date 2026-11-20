#!/usr/bin/env bash
# Run a command against a throwaway nested X server (Xephyr), never the real display.
#   scripts/with-test-display.sh pytest -m xserver
# Sets PHONEPAD_TEST_DISPLAY and DISPLAY for the command. Xephyr opens a small window briefly.
set -euo pipefail
command -v Xephyr >/dev/null || { echo "Xephyr not found (package xserver-xephyr)" >&2; exit 1; }

n=90
while [[ -e /tmp/.X11-unix/X$n || -e /tmp/.X$n-lock ]]; do n=$((n + 1)); done
Xephyr ":$n" -screen 320x200 -nolisten tcp -br -noreset >/dev/null 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT
for _ in $(seq 50); do
  [[ -e /tmp/.X11-unix/X$n ]] && break
  sleep 0.1
done
PHONEPAD_TEST_DISPLAY=":$n" DISPLAY=":$n" "$@"
