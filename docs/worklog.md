# Worklog

Append-only, newest last. One entry per working session: what was done and why, how it was
verified, review outcomes, anything left open. Decisions get an ADR; this log links to it.

## 2026-11-20 — idea, interview, v0.1.0

- The owner wanted to control the laptop's cursor from an iPhone. KDE Connect was too heavy
  (160 packages, 140 MB), so the owner chose to build it, "properly and extendable".
- Three interview rounds settled the requirements (`docs/SPEC.md`):
  - uses: sofa → TV, desk
  - v1 adds live typing
  - autostart, QR pairing, trusted networks only
  - home-screen web app, natural scrolling, no extra gestures
  - name `phonepad`
  - decisions in ADR-0002 to ADR-0008
- Pairing became "one-time code, then device token" (ADR-0004), because iOS home-screen apps
  do not share storage with the browser.
- Installed only into the conda env `phonepad` and the repo's `node_modules`. The owner asked
  for no system changes without approval, so the udev and ufw steps are in
  `scripts/setup-system.sh` for the user to run.
- Verified:
  - pytest (63)
  - node unit tests (28)
  - e2e in headless Chrome with iPhone emulation and touch (8): pairing incl. wrong code and
    QR link, tap, move, L button, live typing, reload, revoke
  - XTest typing of `aÄß€😀zy` + Backspace against Xephyr, keymap restored afterwards
  - screenshots of all screens in dark and light
- The e2e run found that a QR link opened while the page is already loaded only changes the
  fragment; fixed with a `hashchange` handler.

## 2026-11-20 — independent review and fixes

- **Independent review** (fable-reviewer): no authentication bypass; 5 major and 22 minor
  findings. Fixed:
  - XTest bursts garbled when keycodes were remapped before clients read the earlier press
    (reproduced in Xephyr): 100 ms reuse guard, all spare keycodes used, crash leftovers
    reclaimed from a `keymap.json` record (ADR-0003). Guessing leftovers from the keymap was
    rejected: BackSpace and F-keys look the same.
  - Text typed while offline was counted as sent, so later backspaces could delete laptop
    text: the buffer resets on every status change and on failed sends.
  - Dead sockets after phone sleep: `ping`/`pong`, connect timeout, reconnect when coming back
    to the foreground.
  - Client exceeded protocol limits (big flicks, pastes) and 4400 was not retried: deltas
    split, edits chunked, 4400 retried.
  - Tap then two-finger tap gave a double click: the drag button goes down only on movement.
  - Minor: Host check against DNS rebinding, a cap on unauthenticated sockets, read errors
    never count as "no devices", nmcli hiccups tolerated, wired profiles need `--yes`, X
    events drained, no retyping after an X reconnect, failing backends recreated, uinput
    retried after fallback, xinput wait only once, re-pairing keeps and then replaces the old
    token, storage fallback in memory, sentinel written as an escape, setup script subnet and
    `--remove` fixes, `import-environment` in autostart, no endless restarts on bad settings.
  - Recorded instead of fixed: per-profile trust and the weak host model (ADR-0005), Backspace
    per grapheme vs terminals and the browser's storage eviction on iOS (README "Known
    limitations"), iOS behaviour to check on the device (STATE.md).
- Found while fixing: aiohttp may cancel a session handler when the phone disconnects, which
  skipped the button release; the release now runs in its own task.
- Verified:
  - pytest (80)
  - node unit tests (38)
  - e2e (9), including an outage test that restarts the server
  - Xephyr (4): a 70-character burst read by a concurrent client, and crash leftovers
    restored

## 2026-11-20 — first real use, publication

- The owner set it up and used it on the iPhone (Vivaldi and home-screen app): works.
- Prepared the repo for a public GitHub repository:
  - MIT license (copyright in the owner's name)
  - neutral wording instead of personal names in the docs
  - README rewritten for new users: requirements, venv install, generic subnet example,
    daily use, screenshots (`docs/images/screenshots.png`, from the e2e setup), security
    contact
  - GitHub Actions CI: lint, types, unit, e2e, XTest typing against Xvfb, pytest on Python
    3.11 and 3.13
  - `scripts/with-test-display.sh` prefers headless Xvfb over Xephyr
  - Claude session links removed from the commit messages before the first push
- Found on Python 3.11: aiohttp serves `.js` as `application/javascript`; the test now
  accepts both JavaScript MIME types.
