---
status: accepted
date: 2026-11-20
decision-makers: Christopher Lepenik
---

# Listen only on trusted networks (plus loopback)

## Context and Problem Statement

With autostart the server also runs in offices and hotels. Christopher chose to accept
connections only on networks he allows.

## Considered Options

- Bind to the IPv4 addresses of trusted NetworkManager connections, checked every 3 s
- Bind to all interfaces and reject untrusted ones in the handler
- Manual on/off

## Decision Outcome

Chosen option: "bind to trusted addresses". Trust is per NetworkManager connection UUID
(`phonepad trust`), read via `nmcli`. On an untrusted network no LAN port is open at all, which
is stronger than rejecting in the handler. `127.0.0.1` is always bound for status and tests.
Polling `nmcli` every 3 s is simple and robust; `nmcli monitor` or D-Bus can replace it if the
delay matters.

### Consequences

- Good, because the ufw rule and the bind address both limit exposure.
- Bad, because IPv6 and mDNS host names (`laptop.local`) are not served yet; the QR code uses
  the IPv4 address, so a changed DHCP lease means a new home-screen bookmark. A DHCP
  reservation in the router avoids that.
