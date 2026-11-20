# Decision records

Architecture and product decisions, one per file, in [MADR 4.0.0](https://adr.github.io/madr/)
format. New record: copy [adr-template.md](adr-template.md) to the next free number, fill it in,
add a row below. Replaced decisions stay, with status `superseded by ADR-NNNN`.

| ADR                                                              | Decision                                                            | Status   |
| ---------------------------------------------------------------- | ------------------------------------------------------------------- | -------- |
| [0001](0001-record-decisions-as-madr.md)                         | Record decisions as MADR files in docs/decisions                    | accepted |
| [0002](0002-web-app-served-by-aiohttp.md)                        | A web app served from the laptop, with an aiohttp server            | accepted |
| [0003](0003-uinput-pointer-and-xtest-keyboard.md)                | uinput pointer, XTest keyboard, behind backend interfaces           | accepted |
| [0004](0004-pairing-code-and-device-tokens.md)                   | One-time pairing code, then a device token; plain HTTP on the LAN   | accepted |
| [0005](0005-listen-on-trusted-networks-only.md)                  | Listen only on trusted networks (plus loopback)                     | accepted |
| [0006](0006-autostart-via-xdg-autostart-and-systemd-user-unit.md) | Autostart: XDG autostart entry starts a systemd user unit          | accepted |
| [0007](0007-live-typing-by-prefix-diff.md)                       | Live typing as "backspaces + insert" from a prefix diff             | accepted |
| [0008](0008-pointer-acceleration-in-the-web-app.md)              | Pointer acceleration in the web app, flat profile on the laptop     | accepted |
