# Exact Splash lifecycle candidate `60eed8c`

## Source and review

- Runtime/source: `60eed8c1376587bb94b44de2ac359553a9b0ef34` on draft PR #220, targeting `main`.
- Splash remains optional for offer broadcasting and receipt. The fixes in `9965762`, `170ac11`, `a2f6e3d`, and `60eed8c` keep stop/start ownership and UI listening state truthful when shutdown, manager join, or listener startup is incomplete.
- Regressions were observed failing before their fixes, then passing afterward. The affected local Splash/bot-stop suite passed **114 tests**. An independent secondary static review found the stop-path gaps, then reported no remaining finding in the final `a2f6e3d..60eed8c` patch.
- The full isolated Chromium suite passed **259 tests** on this source. Changed-file Ruff and formatting passed. All **11** exact-head PR checks passed, including CI unit tests.
- The complete serial local Windows backend passed **7,561 tests, 260 skipped, and 455 subtests** in 25m07s with exit code zero. The log is `E:\catalyst-pr220-60eed8c-backend.log`; the Chromium log is `E:\catalyst-pr220-60eed8c-browser.log`.

## Clean Windows package

- Detached clean source checkout: `C:\catalyst\.superpowers\pr220-60eed8c-package` at the exact SHA above. `python build.py` completed successfully.
- EXE: `C:\catalyst\.superpowers\pr220-60eed8c-package\dist\Catalyst\Catalyst.exe`, SHA-256 `23471807DE650C317C700ABB9DD51442042D28F6CFE7BD56FEC9ECF88AD49B9D`.
- Source and bundled `bot_gui.html` both SHA-256 `FA188E86E5277CB321C4B1940E4A44C7F990F1F64B14E782657BF03A5D841B09`.
- ZIP: `CATalyst-60eed8c-primary-acceptance.zip`, SHA-256 `3255E23B20BCF111D05AF41075CFCBCE34CCEF95AB3EBD2A519CF47B7ABF3C99`. Its 192 file paths are unique and exactly match the bundle; CRC and every extracted byte hash passed.
- Unsigned production installer: `Catalyst-Setup-60eed8c-1.4.0.exe`, SHA-256 `D98AA71B4197BD0A5C373541A30F5A2A21560C5678D33EEF8BBCB1B4ECE38E33`.
- The ZIP, installer, and manifest are pinned at artifact commit `10f19af3d4e7ea6e587d1508279e1da8d5fda524` on `codex/coin-prep-fee-approval-artifacts`. Independent HTTP retrievals of both binaries matched the hashes above.

Packaged API, synthetic Sage RPC, upgrade publication recovery, and native clean/duplicate/persisted/safety launch smokes passed. The extracted ZIP passed packaged API and synthetic Sage RPC smokes. A unique-AppId QA installer installed to an isolated directory, its installed EXE matched the clean build, its API and Sage smokes passed, and its uninstaller removed the directory and registration with exit zero. Defender custom scans of the bundle, ZIP, and installer completed without a matching detection.

## Live status and remaining gates

At the package checkpoint the original TEST 7 profile still ran the prior `b10cfa3` binary. On 2026-10-09, the old stopped app was closed through its native window after verifying its path, hash, zero open offers and active campaigns, and allowed safety state. Its historical read-only monitor was ended for a planned candidate rollover and earns **no** 24-hour credit.

The exact `60eed8c` EXE was launched against the original default profile as sole PID `183912` and port-5000 owner. The fresh read-only, PID/path/hash-bound monitor `E:\catalyst-stability-monitor-60eed8c-primary\trace-60s.jsonl` started at **2026-10-09T17:48:57.546623Z**. Its first sample had zero alerts: bot stopped, zero DB open offers/active campaigns/unresolved operations, safety allowed with an owned renewing lease, Sage mainnet TEST 7 fingerprint `736588221`, synced wallet, no pending or nonterminal offers in the complete 4,095-offer history, unchanged XCH `138470301476875` mojos and MZ `780212284` atomic units. The 24-hour gate cannot be credited before **2026-10-10T17:48:57.546623Z** and an end-state review. No `60eed8c` wallet effect, new campaign, or network-fee approval is claimed. The old campaign remains stopped and the older fee approval must not be reused.

Exact-candidate live offer creation/receipt and restart recovery, a second Splash peer observing identical active `offer1` bytes, full original-profile native UI, independent secondary original-profile acceptance, both exact-candidate 24-hour windows, and final review remain open. The secondary PC had about 1.0 GiB free, below its documented 2 GiB post-staging floor. A separate cache/temp cleanup was automatically rejected before execution with reason `blocked by policy`; no files were removed. PR #220 and the website beta remain draft; no public-readiness claim or release is made.
