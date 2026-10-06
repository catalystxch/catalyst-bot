# CATalyst 6e2dcef primary acceptance package

Source: `6e2dcefd60ea11479f58ac3a8d7605ff6baaf921`, draft PR #220 targeting `main`.

This candidate fixes narrow-window clipping in the Dashboard Quick Start grid and Settings Setup view. The two browser regressions failed before the CSS change and passed afterward at 390 and 480 pixels. The complete Chromium suite passed 231 tests. Backend code is unchanged from source `676028287b4fba1948de4542567abd2ab0a3a020`, whose complete Windows backend passed 7,278 tests, 229 skipped, and 433 subtests. Exact-head CI unit tests were still running at this package checkpoint.

The clean detached Windows 1.4.0 build passed packaged API, mock Sage RPC, interrupted publication recovery, and clean/duplicate/persisted/native safety smokes. The 192-file ZIP passed CRC and contained the exact clean EXE. A unique-AppId current-user QA installer installed an identical EXE to an isolated E: directory; uninstall removed its EXE and QA registration without affecting the original TEST 7 process. Defender scans of the bundle, ZIP, and unsigned installer added zero detections.

| Artifact | SHA-256 |
| --- | --- |
| Clean `Catalyst.exe` | `0B24F9AC5071681DB9570DD1C8EB1583D39FC80DCFC422BE268A00DB77AAA082` |
| Bundled `bot_gui.html` | `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574` |
| `CATalyst-6e2dcef-primary-acceptance.zip` | `CECC3F6E806B86F2D7DCAE83E1F1EABA5D779E5E1E3E8D43265728C5E157DE34` |
| `Catalyst-Setup-6e2dcef-1.4.0.exe`, unsigned | `0DEE105CD25DF2511DB422B8F852F5FECB9FB0435FB597838DDD2B907D0FE727` |

The original TEST 7 profile still runs the previous `6760282` EXE in stopped, read-only acceptance. This new EXE has not run against that profile. Its live stopped-profile 24-hour window, active-offer lifecycle and recovery, secondary original-profile acceptance, active-profile 24-hour window, and final review remain open. No new campaign or fee approval exists. Keep PR #220 draft; this package is acceptance evidence, not a release.
