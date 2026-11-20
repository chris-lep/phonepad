#!/usr/bin/env bash
# One-time system setup for phonepad. Needs root; read it before running.
#
#   sudo scripts/setup-system.sh                 # udev rule + firewall rule (port 8790, current subnet)
#   sudo scripts/setup-system.sh --port 8790 --subnet 10.0.0.0/24
#   sudo scripts/setup-system.sh --remove        # undo both
#
# What it changes (the same steps by hand are in README.md, "System setup"):
#   1. /etc/udev/rules.d/70-phonepad-uinput.rules (root:root 0644): gives the logged-in desktop
#      user read/write access to /dev/uinput (uaccess ACL), for the virtual mouse.
#   2. ufw: allow TCP <port> from <subnet> only, with the comment "phonepad".
set -euo pipefail

RULE_FILE=/etc/udev/rules.d/70-phonepad-uinput.rules
RULE='KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"'
PORT=8790
SUBNET=""
REMOVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --subnet) SUBNET="$2"; shift 2 ;;
    --remove) REMOVE=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0 $*" >&2
  exit 1
fi

ufw_active() { command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; }

if [[ $REMOVE -eq 1 ]]; then
  if [[ -e $RULE_FILE ]]; then
    rm -f "$RULE_FILE"
    udevadm control --reload-rules
    echo "removed $RULE_FILE (access to /dev/uinput ends at the next reboot)"
  fi
  if command -v ufw >/dev/null; then
    while num=$(ufw status numbered | grep 'phonepad' | head -n1 | grep -oP '^\[\s*\K[0-9]+'); [[ -n $num ]]; do
      ufw --force delete "$num" >/dev/null
      echo "removed ufw rule $num (phonepad)"
    done
  fi
  exit 0
fi

# 1. uinput access ---------------------------------------------------------------------------
echo "$RULE" > "$RULE_FILE"
chmod 0644 "$RULE_FILE"
udevadm control --reload-rules
udevadm trigger --sysname-match=uinput --action=change
udevadm settle
echo "wrote $RULE_FILE"
if [[ -n ${SUDO_USER:-} ]]; then
  if sudo -u "$SUDO_USER" test -w /dev/uinput; then
    echo "ok: $SUDO_USER can write /dev/uinput"
  else
    echo "warning: /dev/uinput is not writable for $SUDO_USER yet; log out and in (or reboot)" >&2
  fi
fi

# 2. firewall --------------------------------------------------------------------------------
if ufw_active; then
  if [[ -z $SUBNET ]]; then
    dev=$(ip -4 route show default | awk '{print $5; exit}')
    SUBNET=$(ip -4 route show dev "$dev" proto kernel scope link | awk '{print $1; exit}')
  fi
  if [[ -z $SUBNET ]]; then
    echo "cannot find the current subnet; pass --subnet, e.g. --subnet 10.0.0.0/24" >&2
    exit 1
  fi
  ufw allow from "$SUBNET" to any port "$PORT" proto tcp comment 'phonepad'
  echo "ok: ufw allows TCP $PORT from $SUBNET"
else
  echo "ufw is not active; no firewall rule needed"
fi
echo "Restart phonepad to use the uinput mouse: systemctl --user restart phonepad"
