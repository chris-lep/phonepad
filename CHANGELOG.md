# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-20

### Added

- Touchpad web app for the phone's browser: pointer with adjustable speed and acceleration, tap to
  click, tap-then-touch to drag, two-finger scroll (natural by default) and right-click, L/R
  buttons.
- Live typing with the phone's keyboard (autocorrect and dictation included) and special keys
  (Esc, Tab, arrows, Backspace, Enter), any Unicode character on any keyboard layout.
- Pairing with a one-time code or QR code; per-device tokens; `phonepad devices` / `revoke`.
- Trusted networks (`phonepad trust`): the server listens on the LAN only there.
- uinput virtual mouse with smooth scrolling, XTest keyboard, XTest pointer fallback.
- `phonepad service install` (autostart at login), `phonepad doctor`, `scripts/setup-system.sh`.
- Home-screen web app (manifest, icons), dark and light theme.
