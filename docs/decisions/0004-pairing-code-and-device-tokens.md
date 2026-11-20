---
status: accepted
date: 2026-11-20
decision-makers: project owner
---

# One-time pairing code, then a per-device token; plain HTTP on the LAN

## Context and Problem Statement

Controlling input means being able to type commands, so nobody else on the Wi-Fi may connect.
The owner chose QR-code pairing. iOS home-screen web apps have storage separate from the browser
that added them, so a token saved after scanning a QR code in the browser is not visible to
the home-screen app.

## Considered Options

- One-time code (QR fills it in, or typed) exchanged for a long-lived device token
- Token directly in the QR code
- Confirm each new connection on the laptop with a PIN

## Decision Outcome

Chosen option: "one-time code exchanged for a device token". The QR code carries the code in
the URL fragment (never sent to the server or into logs); the home-screen app shows a field for
the same code. Codes: 6 digits, 5 minutes, 5 tries, one use. Tokens: 256 bit, only the SHA-256
hash is stored, revocable per device. `phonepad pair` writes the pending code to
`pairing.json`; the running server reads it, so the CLI does not talk to the server.

The connection is plain HTTP/WebSocket on trusted networks only (ADR-0005). The token can be
sniffed on the LAN; accepted for a home network.

### Consequences

- Good, because pairing works in the browser and in an iOS home-screen app.
- Bad, because some browser APIs need HTTPS (screen wake lock, motion sensors for an "air mouse").
  Revisit with a local CA certificate installed on the phone when such a feature is wanted.
