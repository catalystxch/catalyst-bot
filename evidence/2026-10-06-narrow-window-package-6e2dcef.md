# Narrow-window layout and exact Windows package

Draft PR #220 exact source: `6e2dcefd60ea11479f58ac3a8d7605ff6baaf921`.

At 390–480 px, the Dashboard Quick Start grid let a long real CAT option set the grid's intrinsic minimum width. The title and Refresh control extended past the window. At 390 px, the Settings flex child also retained an intrinsic width wider than its view, clipping the Setup tab and wallet-session controls. Focused Chromium regressions reproduced both failures before the CSS changes and passed after `minmax(0, 1fr)` on the compact grid and explicit `width: 100%; min-width: 0` on the Settings container. The complete Chromium suite passed 231 tests. Ruff check, format, and diff check passed. All 11 PR checks passed on this exact head.

The backend is unchanged from `676028287b4fba1948de4542567abd2ab0a3a020`. The complete serial local Windows run on exact source `6e2dcef` passed 7,278 tests, with 232 skipped and 433 subtests passed, in 38m40s. Its command was `python -m pytest tests -q --tb=short`; exit code was zero and the full log is `E:\catalyst-responsive-6e2dcef-build\full-backend-6e2dcef.log`.

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

The original TEST 7 profile was rolled from the stopped `6760282` process to the exact `6e2dcef` EXE through the native UI. The earlier monitors ended intentionally at `2026-10-06T16:41:11Z`; they are historical and do not count toward this candidate's 24-hour gate. The new sole process was PID `153252`, with its path and SHA-256 verified against the clean build and port 5000 owned by that PID. The operator-authorized Risk Disclosure was acknowledged in the native UI. Sage connected to mainnet TEST 7 fingerprint `736588221`, CAT wallet ID `2`, and exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`. The app was stopped, synced, safety allowed with its lease owned, Bootstrap inactive, and wallet balances unchanged at `138.470301476875` XCH and `780212.284` MZ. Fresh Sage and database offer reads found zero open offers and zero pending wallet transactions. The old campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` remained stopped with zero authoritative fee spend and no linked Coin Prep approval.

Fresh exact-PID/hash stopped-profile monitoring started at `2026-10-06T16:51:55Z` for safety, health, and offers, with port-owner monitoring from `16:51:51Z`, in `E:\catalyst-stability-monitor-6e2dcef`. An initial port-monitor invocation under Windows PowerShell failed because that shell lacked `Get-FileHash`; the visible failed sample was retained, and both monitors were restarted under PowerShell 7. First valid samples confirmed safety allowed, bot stopped, synced wallet, zero open offers, and one matching port owner. The 24-hour gate cannot complete before `2026-10-07T16:51:55Z` plus complete-trace and end-state review. Active-offer lifecycle and recovery, secondary original-profile acceptance, the active-profile 24-hour window, and final review remain open. No new campaign or fee approval exists. PR #220 remains draft; this is acceptance evidence, not a release.

The exact native app's Dashboard, Offers, P&L, Market Intelligence, Settings, Logs, Data Reset, Help, and About views were opened read-only after this rollover. Offers showed 0 buy and 0 sell, P&L distinguished three historical confirmed fills from current exposure, Settings showed TEST 7 and the MZ pair, Logs backfilled the current Sage startup and pair-selection events, and Dashboard returned to stopped Follow mode. No reset, settings save, bot start, offer action, or campaign action occurred.
