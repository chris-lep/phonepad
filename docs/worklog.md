# Worklog

Append-only, newest last. One entry per working session: what was done and why, how it was
verified, review outcomes, anything left open. Decisions get an ADR; this log links to it.

## 2026-11-20 — idea, interview, v0.1.0

- Christopher wanted to control the laptop's cursor from his iPhone. KDE Connect was too heavy
  (160 packages, 140 MB), so he chose to build it himself, "properly and extendable".
- Three interview rounds settled the requirements (`docs/SPEC.md`):
  - uses: sofa → TV, desk
  - v1 adds live typing
  - autostart, QR pairing, trusted networks only
  - home-screen web app, natural scrolling, no extra gestures
  - name `phonepad`
  - decisions in ADR-0002 to ADR-0008
- Pairing became "one-time code, then device token" (ADR-0004), because iOS home-screen apps
  do not share storage with Safari.
- Installed only into the conda env `phonepad` and the repo's `node_modules`. Christopher asked
  for no system changes without approval, so the udev and ufw steps are in
  `scripts/setup-system.sh` for him to run.
- Verified:
  - pytest (63)
  - node unit tests (28)
  - e2e in headless Chrome with iPhone emulation and touch (8): pairing incl. wrong code and
    QR link, tap, move, L button, live typing, reload, revoke
  - XTest typing of `aÄß€😀zy` + Backspace against Xephyr, keymap restored afterwards
  - screenshots of all screens in dark and light
- The e2e run found that a QR link opened while the page is already loaded only changes the
  fragment; fixed with a `hashchange` handler.
