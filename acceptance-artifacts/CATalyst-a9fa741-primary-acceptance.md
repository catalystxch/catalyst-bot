# CATalyst a9fa741 primary Windows acceptance package

Exact source: `a9fa74115c443657e289fa8a58f996774900d44d`. This is an unsigned test candidate for draft PR #220, not a public release.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `403ED21AFA906B5B54D2415AFA3F14E2AE45ABBC4B0228813663298EA8123DA9` |
| Bundled `bot_gui.html` | `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781` |
| `CATalyst-a9fa741-primary-acceptance.zip` | `E9BE9CEDCD61568C857C12EAFF467D734FC3E1C5BF44C58FBDF44A6509CA2596` |
| `Catalyst-Setup-a9fa741-1.4.0.exe` | `06D65A3BD639134C68B44ECA44D0353D7B74C220DC7227A3BF851275E36B499A` |

The full serial Windows backend suite passed **7,342 tests, 241 skipped, 436 subtests passed**. The clean detached build passed packaged API, synthetic Sage RPC, publication recovery, and native clean/duplicate/persisted/safety launch smokes. ZIP CRC and embedded EXE identity passed across 192 files. A separate unique-AppId QA installer passed clean install, installed EXE hash, installed API and synthetic Sage, and uninstall with its EXE and registration removed. Defender real-time protection remained enabled and recorded no new detections during scans of the bundle, ZIP and unsigned installer.

Original TEST 7 live acceptance, active-offer lifecycle, both final-candidate 24-hour windows and final review remain open. No new campaign or fee approval exists. Keep PR #220 draft; do not merge, tag, release or claim public readiness.
