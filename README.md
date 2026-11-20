# phonepad

Use an iPhone as touchpad and keyboard for this Linux laptop. The laptop serves a small web
app; the phone opens it in Safari (or as a home-screen app). Nothing is installed on the
phone, and it works only on networks you trust.

- One finger moves the pointer, a tap clicks, tap-then-touch drags.
- Two fingers scroll smoothly (pixel-precise via a uinput virtual mouse); a two-finger tap is a
  right click.
- Live typing with the iPhone keyboard, including autocorrect, dictation, umlauts and emoji.
  Special keys: Esc, Tab, arrows, Backspace, Enter.

Requirements and behaviour: [docs/SPEC.md](docs/SPEC.md). Why it is built this way:
[docs/decisions/](docs/decisions/README.md).

## Setup

Linux Mint / Cinnamon on X11, NetworkManager, Python 3.11+. The steps below use the conda
environment `phonepad` (see [Development](#development)).

### 1. Install

```bash
conda create -n phonepad python=3.12 && conda activate phonepad
pip install -e ~/dev/personal/phonepad
```

### 2. System setup (once, needs sudo)

Either run the script (read it first; it prints what it does):

```bash
sudo scripts/setup-system.sh          # undo: sudo scripts/setup-system.sh --remove
```

or do the same by hand:

1. Give the logged-in user access to `/dev/uinput` (for the virtual mouse). Create
   `/etc/udev/rules.d/70-phonepad-uinput.rules`, owner `root:root`, mode `0644`, with this line:

   ```
   KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
   ```

   Then run
   `sudo udevadm control --reload-rules && sudo udevadm trigger --sysname-match=uinput --action=change`.
   Check with `test -w /dev/uinput && echo ok` (or log out and in).
2. Open the port in the firewall for your home subnet only (find the subnet with
   `ip -4 route show dev wlp0s20f3 proto kernel`):

   ```bash
   sudo ufw allow from 10.0.0.0/24 to any port 8790 proto tcp comment 'phonepad'
   ```

Without step 1 phonepad still works, with the XTest pointer (scrolling then moves in notches).

### 3. Trust your home network, start, pair

```bash
phonepad trust              # while connected to the home Wi-Fi
phonepad service install    # start now and at every login (systemd user unit + autostart)
phonepad pair               # shows a QR code and a 6-digit code
phonepad doctor             # checks everything above
```

On the iPhone, scan the QR code with the camera: it opens the web app in Safari and pairs it.
For the full-screen app: Safari → Share → **Add to Home Screen**, open it from the home screen
and type a code there (home-screen apps have their own storage, so they pair separately; run
`phonepad pair` again for a fresh code).

Tip: reserve the laptop's IP address in the router (DHCP reservation); the home-screen app
remembers the address.

## What the setup changes

| Change                     | Path / place                                              | Made by                      |
| -------------------------- | --------------------------------------------------------- | ---------------------------- |
| conda environment          | `~/miniconda3/envs/phonepad`                              | step 1                       |
| udev rule (uinput access)  | `/etc/udev/rules.d/70-phonepad-uinput.rules` (root, 0644) | step 2 (sudo)                |
| firewall rule              | ufw rule with comment `phonepad`                          | step 2 (sudo)                |
| systemd user unit          | `~/.config/systemd/user/phonepad.service`                 | `phonepad service install`   |
| autostart entry            | `~/.config/autostart/phonepad.desktop`                    | `phonepad service install`   |
| state (devices, networks)  | `~/.local/state/phonepad/` (0700, files 0600)             | `trust`, `pair`, the server  |
| settings (optional)        | `~/.config/phonepad/config.toml`                          | you, by hand                 |
| on the iPhone              | home-screen icon, Safari site data for the laptop address | you                          |

Nothing else is written. The server changes the X keymap only while it runs (spare keycodes,
cleared on exit) and creates the virtual mouse only while it runs.

## Uninstall

In this order (the service first, so nothing recreates state while you delete it):

```bash
phonepad service uninstall                 # stops the server, removes the unit and autostart entry
sudo ~/dev/personal/phonepad/scripts/setup-system.sh --remove   # udev rule + ufw rule
rm -rf ~/.local/state/phonepad ~/.config/phonepad                # paired devices, trusted networks, settings
conda env remove -n phonepad               # the Python environment
rm -rf ~/dev/personal/phonepad             # the code (only if you want it gone)
```

By hand instead of the commands:

1. Service: `systemctl --user stop phonepad.service`, then delete
   `~/.config/systemd/user/phonepad.service` and `~/.config/autostart/phonepad.desktop`, then
   `systemctl --user daemon-reload`.
2. udev: `sudo rm /etc/udev/rules.d/70-phonepad-uinput.rules && sudo udevadm control --reload-rules`.
   The access to `/dev/uinput` granted earlier ends at the next reboot.
3. Firewall: `sudo ufw status numbered`, then `sudo ufw delete <number>` for each line with the
   comment `phonepad`.
4. State, settings, conda environment and code: as in the commands above.
5. iPhone: long-press the phonepad icon → Delete Bookmark; Settings → Apps → Safari → Advanced
   → Website Data → remove the laptop's address.

`phonepad doctor` before step 4 shows what is still in place.

## Commands

| Command                                     | What it does                                             |
| ------------------------------------------- | -------------------------------------------------------- |
| `phonepad pair`                             | new pairing code + QR code (5 minutes, one phone)        |
| `phonepad devices`                          | paired phones                                            |
| `phonepad revoke ID` / `--all`              | unpair (the phone is disconnected within seconds)        |
| `phonepad trust` / `untrust NAME`           | trust or stop trusting a network                         |
| `phonepad networks`                         | trusted and active networks                              |
| `phonepad service install/uninstall/status` | autostart at login                                       |
| `phonepad serve`                            | run in the foreground (`--help` for development options) |
| `phonepad doctor`                           | check the setup, with hints                              |

Logs: `journalctl --user -u phonepad -f`. Settings (optional):
`~/.config/phonepad/config.toml` with `port`, `pointer_backend` (`auto`/`uinput`/`xtest`) and
`advertise_host`. State: `~/.local/state/phonepad/` (paired devices as token hashes, trusted
networks, pending code; files mode 0600).

## Security

- Only phones that paired with a one-time code (6 digits, 5 minutes, 5 tries) can connect;
  each has its own revocable 256-bit token, stored on the laptop as a hash.
- The server listens on the LAN only while connected to a trusted network, and only on that
  network's address. The firewall rule limits the port to the home subnet.
- Plain HTTP on the home network: someone sniffing your Wi-Fi could copy a token. See
  [ADR-0004](docs/decisions/0004-pairing-code-and-device-tokens.md).

## Development

Agents (and humans) working on the code: start with [AGENTS.md](AGENTS.md).

```bash
conda create -n phonepad python=3.12 && conda activate phonepad
pip install -e . --group dev     # pytest, ruff, mypy, pre-commit (needs pip >= 25.1)
npm install                      # Biome (JS/CSS lint + format), puppeteer-core (e2e)
pre-commit install

make check    # format check, lint, types, Python + JS unit tests, e2e (headless Chrome)
make xtest    # real XTest typing against a throwaway Xephyr server
make fmt      # apply formatting
make icons    # redraw the app icons
```

Versioning follows [SemVer](https://semver.org); changes are listed in
[CHANGELOG.md](CHANGELOG.md), releases are git tags `vX.Y.Z`. The version lives only in
`src/phonepad/__init__.py`. Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org).
