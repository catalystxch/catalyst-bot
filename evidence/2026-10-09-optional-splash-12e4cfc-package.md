# Optional Splash exact package — 2026-10-09

## Scope and identity

Exact runtime and package source: `12e4cfc4e8655e5a4b17a6b0126537eb8b0e33cb` on draft PR #220 into `main`. Splash remains an optional offer broadcast path, off for new installs. Outbound broadcast can run without inbound receive. Dexie and Splash repost outcomes are independent, and local Splash submission is not proof of remote peer delivery. This source corrects the zero-peer warning for outbound-only users: it recommends checking connectivity, peer discovery, and the configured P2P firewall setting without claiming that an inbound port is mandatory.

## Exact verification

- Complete serial Windows backend: **7,507 passed, 259 skipped, 455 subtests passed** in 1660.99 seconds. Log: `E:\catalyst-splash-12e4cfc-full-backend.log`.
- Complete Chromium: **258 passed** in 163.11 seconds. Log: `E:\catalyst-splash-12e4cfc-chromium.log`.
- Focused Splash/repost tests: **39 passed**. Repository-wide Ruff check and format check passed. All **11 exact-head PR #220 checks** passed, including unit tests and security scans.
- A clean detached PyInstaller build, packaged API, synthetic Sage RPC, publication recovery, and extracted ZIP API smokes passed. The ZIP has 192 files and 50 directory entries, safe `Catalyst/` paths, no duplicate names, valid CRCs, and exact embedded executable/UI hashes.
- The production 1.4.0 installer compiled and remains unsigned. A unique-AppId current-user QA variant passed isolated clean install, installed API/Sage smokes, exact comparison of all 192 bundle files, and uninstall. Only the two Inno uninstaller files were extra.
- Windows Defender custom scans of the exact executable, ZIP, and installer reported zero matching detections.
- ZIP, installer, and manifest were independently downloaded by HTTP from immutable artifact commit `231063d00d1c77114e75941a00a40a1d6a5c4728`. Downloaded lengths and SHA-256 hashes matched the local builds and manifest.
- The saved Splash binary on primary TEST 7 and the independently checked secondary PC had SHA-256 `52FAAEF54CE5F38BCC7E174125E2A0FC725B75895B3E45CF8693121E278991B8`, matching the official Splash 0.2.0 AMD64 sidecar. Neither machine had a running Splash daemon during the read-only checks.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-splash-12e4cfc-build\dist\Catalyst\Catalyst.exe` | `A53AE21F80A71ABA4CE3BD8E835A9C0A2A17B3059B418B96F401FEA828686363` |
| Bundled `bot_gui.html` | `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/231063d00d1c77114e75941a00a40a1d6a5c4728/acceptance-artifacts/CATalyst-12e4cfc-primary-acceptance.zip) | `2F89F7CAF8125E408827F8191FF19363EED0A22CCAFFD5570B8B0750EE5F91C3` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/231063d00d1c77114e75941a00a40a1d6a5c4728/acceptance-artifacts/Catalyst-Setup-12e4cfc-1.4.0.exe) | `AD3A953EFB0460DBE266734ED3E39A5B2493F695D28F9430FF9B09875A09FA96` |

## Live state and remaining acceptance

At the last read-only preflight, original TEST 7 was running the historical `515b41c` executable as a single process, with a stopped bot, no active campaign or open/unresolved offers, no pending wallet transactions, an owned renewing lease, and unchanged balances. Its saved configuration enables Splash including inbound receive, but that historical executable keeps the release-level Dexie-only fence and no Splash daemon was running. The historical stopped-profile monitor is not evidence for `12e4cfc`.

An earlier automatic approval review rejected an isolated Splash daemon launch as `blocked by policy`. The exact package has not been launched against the original profile, and programmatic launch under the saved Splash-enabled configuration must not be used to route around that rejection. A normal operator close and manual launch of the exact executable is required before fresh read-only identity/safety preflight and exact-PID/hash monitoring. No new campaign or fee scope has been specifically approved. The prior TEST 7 campaign is stopped with zero authoritative fee spend; its old approval is invalid for a new campaign.

Remote peer delivery, active-offer lifecycle and recovery, full original-profile native UI, secondary original-profile live acceptance, both exact-candidate 24-hour windows, and final review remain open. PR #220 and website PR #89 remain draft; no beta is deployed and no merge, tag, release, or public-readiness claim has been made.
