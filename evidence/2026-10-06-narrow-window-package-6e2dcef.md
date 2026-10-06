# Narrow-window layout and exact Windows package

Draft PR #220 exact source: `6e2dcefd60ea11479f58ac3a8d7605ff6baaf921`.

At 390–480 px, the Dashboard Quick Start grid let a long real CAT option set the grid's intrinsic minimum width. The title and Refresh control extended past the window. At 390 px, the Settings flex child also retained an intrinsic width wider than its view, clipping the Setup tab and wallet-session controls. Focused Chromium regressions reproduced both failures before the CSS changes and passed after `minmax(0, 1fr)` on the compact grid and explicit `width: 100%; min-width: 0` on the Settings container. The complete Chromium suite passed 231 tests. Ruff check, format, and diff check passed. All 11 PR checks passed on this exact head.

The backend is unchanged from `676028287b4fba1948de4542567abd2ab0a3a020`, whose complete serial local Windows suite passed 7,278 tests, with 229 skipped and 433 subtests. An exact-head serial Windows run is in progress at this package checkpoint.

The clean detached 1.4.0 PyInstaller build passed packaged API, mock Sage RPC, interrupted-publication recovery, and clean/duplicate/persisted/native safety smokes. Its bundled HTML matches the source HTML byte for byte. The 192-file ZIP passed CRC, contained the exact clean EXE, and passed the packaged API smoke again after extraction. A separate unique-AppId current-user QA installer installed the identical EXE to an isolated E: directory, then uninstalled and removed its QA registration without touching the running original TEST 7 process. Defender custom scans of the bundle, ZIP, and unsigned installer added zero detections. Independent HTTP downloads of both pinned binaries matched local SHA-256 hashes.

| Artifact | SHA-256 |
| --- | --- |
| Clean `Catalyst.exe` | `0B24F9AC5071681DB9570DD1C8EB1583D39FC80DCFC422BE268A00DB77AAA082` |
| Bundled `bot_gui.html` | `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574` |
| `CATalyst-6e2dcef-primary-acceptance.zip` | `CECC3F6E806B86F2D7DCAE83E1F1EABA5D779E5E1E3E8D43265728C5E157DE34` |
| `Catalyst-Setup-6e2dcef-1.4.0.exe`, unsigned | `0DEE105CD25DF2511DB422B8F852F5FECB9FB0435FB597838DDD2B907D0FE727` |

The ZIP, installer, acceptance note, and checksum manifest are pinned at artifact commit `e192703d5fa4cde90058d26fe263a24ae8ad4cc9`:

- ZIP: https://raw.githubusercontent.com/catalystxch/catalyst-bot/e192703d5fa4cde90058d26fe263a24ae8ad4cc9/acceptance-artifacts/CATalyst-6e2dcef-primary-acceptance.zip
- Installer: https://raw.githubusercontent.com/catalystxch/catalyst-bot/e192703d5fa4cde90058d26fe263a24ae8ad4cc9/acceptance-artifacts/Catalyst-Setup-6e2dcef-1.4.0.exe

The original TEST 7 profile continues to run the previous `6760282` EXE, stopped, with zero open offers and a clean interim exact-PID/hash monitor. The new EXE has not run against that profile. Its live rollover will reset the final-candidate stopped-profile 24-hour window. Active-offer lifecycle and recovery, secondary original-profile acceptance, the active-profile 24-hour window, and final review remain open. No new campaign or fee approval exists. PR #220 remains draft; this is acceptance evidence, not a release.
