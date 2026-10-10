# Optional Splash combined candidate — 2026-10-09

## Scope and source

Exact runtime and package source: `615b65a8a47b561170f7b1b98f049d9e9cb569c5` on draft PR #220 into `main`. Splash remains an optional offer broadcast path. It is off for new installs; outbound broadcasting can be enabled without inbound receiving. The app reports Dexie and Splash repost outcomes separately. A successful local Splash submission is not proof that a remote peer received an offer.

The combined source includes the independent outbound-only health fix from draft PR #256 (`faa50c57e283082caee299d8f16ca1b7ea9fbd34`). It checks daemon reachability and peer availability when inbound receiving is disabled; inbound hook delivery is checked only when enabled. Startup also broadcasts Dexie-mapped open offers over Splash, retrieving a missing bech32 offer from Sage when needed. Dexie publish failure does not suppress an independent Splash attempt.

## Exact verification

- Full serial Windows backend: **7,507 passed, 259 skipped, 455 subtests passed** in 1378.50 seconds.
- Complete Chromium suite: **258 passed** in 155.59 seconds.
- Repo-wide Ruff check and format check passed. All **11 PR #220 exact-head CI checks** passed, including unit tests and security scans.
- Clean detached PyInstaller build, packaged API, synthetic Sage RPC, and publication recovery smokes passed.
- Acceptance ZIP: 192 files and 14 directory entries, CRC passed, safe paths; extracted executable and UI hashes matched the source package; extracted API smoke passed.
- The production 1.4.0 installer compiled and remains unsigned. A unique-AppId current-user QA variant passed isolated clean install, installed API/Sage smokes, exact comparison of all 192 bundle files, and uninstall. Only Inno uninstaller files were extra. The product's existing registration and user data were not used.
- Windows Defender custom scans of the exact executable, ZIP, and installer reported no new detection.
- ZIP, installer, and manifest were downloaded independently by HTTP from the immutable artifact commit. Downloaded ZIP and installer SHA-256 hashes matched the local builds and manifest.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `97A0519413F1F221FB63D88164244A49D92457368DD3F612979178C91FBCE699` |
| Bundled `bot_gui.html` | `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/82159d7bac7997f39166bd9b2dd9ead95e8d17af/acceptance-artifacts/CATalyst-615b65a-primary-acceptance.zip) | `2DCB4CD66BA9C3CED66EF3CE6D1288A6B98296E9588508582B52FB630975FAF2` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/82159d7bac7997f39166bd9b2dd9ead95e8d17af/acceptance-artifacts/Catalyst-Setup-615b65a-1.4.0.exe) | `BFA604CBB7ED54D39E5F0E9DD3D2D97D37EB208F08127E9707C78EB5204FCC96` |

## Acceptance still open

There is no verified remote Splash peer delivery. The exact `615b65a` package has not completed original-profile TEST 7 or secondary original-profile live acceptance. Active-offer lifecycle and recovery, full native UI, two exact-candidate 24-hour stability windows, final review, and website beta deployment remain open. The prior TEST 7 campaign is stopped with zero authoritative fee spend; its approval is invalid for a new campaign. No new campaign or fee scope has been specifically approved. PR #220 and website PR #89 remain draft; no merge, tag, release, or public-readiness claim has been made.
