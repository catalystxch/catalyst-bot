# Third-Party Notices

CATalyst is licensed under the MIT License. That license covers this project's
own source code. It does not grant rights to third-party names, logos,
trademarks, services, or artwork referenced by the app.

The assets below are included so the app can identify the services it connects
to and guide operators through setup. Their presence does not imply sponsorship,
endorsement, partnership, or ownership by CATalyst.

| Asset | Local path | Project or owner | Public-use status |
| --- | --- | --- | --- |
| Dexie logo | `assets/dexie_logo_official.png`, `assets/dexie_logo_official.ico` | [Dexie](https://dexie.space/) | Integration identifier only. No separate trademark licence is granted by this repository. |
| Sage logo | `assets/sage_logo_official.png` | [Sage Wallet](https://sagewallet.net/) | Integration identifier only. No separate trademark licence is granted by this repository. |
| Sage RPC screenshot | `assets/sage_rpc_advanced.png` | Sage Wallet UI screenshot | Documentation screenshot for local RPC setup. Review and replace if Sage's UI or screenshot policy changes. |
| TibetSwap logo | `assets/tibetswap_logo_official.png` | [TibetSwap](https://v2.tibetswap.io/) | Integration identifier only. No separate trademark licence is granted by this repository. |
| Spacescan logo | `assets/spacescan-logo-192.webp` | [Spacescan](https://www.spacescan.io/) | Integration identifier only. No separate trademark licence is granted by this repository. |
| MonkeyZoo logos | `assets/monkeyzoo-logo-1.gif`, `assets/MonkeyZoo_Logo.png` | MonkeyZoo | Token/project branding used by the current maintainer. Confirm permission before using in third-party marketing or redistributed artwork. |
| CATalyst icons | `assets/bot_icon_new.png`, `assets/bot_icon_new.ico`, `assets/favicon.ico` | CATalyst project | Project artwork. Safe to use for this repository and release packages. |
| README screenshot | `docs/screenshots/catalyst-dashboard.png` | CATalyst project | Generated from an isolated local E2E run with no wallet data or secrets. |
| Architecture diagrams | `docs/diagrams/*.svg`, `docs/diagrams/*.png`, `docs/diagrams/*.mmd` | CATalyst project | Generated documentation diagrams. |
| Web fonts | Referenced by `bot_gui.html` / CSP for Google Fonts | Google Fonts | Loaded from Google Fonts at runtime. Font licences are managed by Google Fonts; do not redistribute font files from this repository unless their individual licences are included. |
| Live token icons | Loaded from `https://icons.dexie.space/...` at runtime | Dexie/token projects | Not vendored in this repository. Used only as runtime metadata for the selected trading pair. |

Third-party service names such as Dexie, Sage, TibetSwap, Spacescan, Splash, and
Chia are used for compatibility and operator clarity. They remain the property
of their respective owners.

If an asset owner asks for an image or name usage to be changed, replace the
asset with a text label or a neutral local icon before the next release.

## Embedded source-code material

### Pieter Wuille Bech32m reference implementation

`src/catalyst/sage_offer_wire.py` adapts the Bech32m checksum, HRP expansion,
decode, and bit-conversion algorithms from Pieter Wuille's reference
implementation at <https://github.com/sipa/bech32/tree/bip-bech32m>.

Copyright (c) 2017 Pieter Wuille. Licensed under the MIT License; the complete
copyright and permission notice is retained in
`licenses/Pieter-Wuille-bech32-MIT.txt` and bundled with CATalyst releases.

CATalyst changes require exact lowercase `offer` HRP text, reject surrounding
whitespace and noncanonical padding, and apply explicit encoded-size bounds.

### Chia Network chia-blockchain 2.5.7

`src/catalyst/sage_offer_wire.py` embeds the cumulative version-6 puzzle
compression dictionary from Chia Network's `chia-blockchain` 2.5.7
`chia.wallet.util.puzzle_compression` module. The exact 7,827 embedded bytes
have SHA-256
`7c2632368f37f21a33b179c9bfd07c383d23c12fb48b47a9b24fa5029f8690a1`.

Copyright Chia Network Inc. and contributors. Licensed under Apache License
2.0; the complete license text is retained in
`licenses/Chia-Network-chia-blockchain-Apache-2.0.txt` and bundled with
CATalyst releases. The Chia 2.5.7 wheel used to verify this material did not
ship a separate NOTICE file.

CATalyst changes store the bytes as base64, pin their hash and version offsets,
apply bounded canonical zlib stream checks, and pass the decompressed bytes to
the separately declared `chia_rs` runtime dependency for exact SpendBundle
parsing and byte-for-byte round-trip validation. No Chia Python runtime code is
copied into or required by this parser.
