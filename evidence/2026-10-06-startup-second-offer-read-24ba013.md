# Fail closed when the worker's second startup offer read is stale

Draft PR #220 runtime/source: `24ba013a974e627e3c75f49b174d13923e3b9bb1`.

The synchronous `BotLoop.start()` gate required a fresh Sage offer book, but
the background `_startup_sync()` performed a second, unpaired wallet read.
If that second read failed, `OfferManager.sync_from_wallet()` returned its
cached book without freshness context. Startup could then seed fill state,
attempt publication recovery, and continue. Separately, `_run_loop()`
continued releasing workers and draining publication work even if startup
set `_running=False` after a failure.

Two tests reproduced the defects before the changes:

- A stale, cached second wallet read seeded the startup fill baseline.
- A failed startup still enabled the durable outbox and drained publication.

The worker now uses the paired offer result and freshness metadata and rejects
stale, cached, or malformed results before baseline/recovery. After a failed
startup, `_run_loop()` releases the worker wait gate only so workers can exit;
it does not enable or drain publication work. The 107 focused preflight and
publication tests passed, as did Ruff check, Ruff format, and diff checks.

## Exact clean Windows package

A detached checkout at `E:\catalyst-24ba013-build` produced the following
unsigned artifacts. The 192-entry ZIP passed CRC, included `.env.example`,
and held an EXE byte-identical to the clean build. Packaged API, synthetic
Sage RPC, publication-recovery and native clean/duplicate/persisted/safety
smokes passed. A unique-AppId, separate-name current-user QA installer
clean-installed the same EXE; installed API and Sage checks passed, then
uninstall removed its EXE and QA registration. Defender custom scans of the
bundle, ZIP and installer added zero detections (six historical detections
before and after).

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `A34AF33FA85B63F7CB1A162E7F235A4AD7C75E78E9FC728B7954B8906F0B03D1` |
| `CATalyst-24ba013-primary-acceptance.zip` | `C280EE6EF71BC5F5F478D0460C13E8B8511BEB166F41A9C5020B1826FEE91FF6` |
| Unsigned `Catalyst-Setup-24ba013-1.4.0.exe` | `8FECA4FA19403DFBF1CA76C6A0F3A2EA67E6BD8CB0437419F2997AACFE426F3A` |

The complete serial Windows backend passed 7,270 tests (227 skipped, 431
subtests) in 19m30s. All 11 exact-source PR checks passed. The ZIP and
installer were pinned at artifact commit
`5dc28455dddc2e7a1aaf52f38c207fdb7353a42d`. Independent HTTP
downloads matched both published SHA-256 hashes:

- [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5dc28455dddc2e7a1aaf52f38c207fdb7353a42d/acceptance-artifacts/CATalyst-24ba013-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5dc28455dddc2e7a1aaf52f38c207fdb7353a42d/acceptance-artifacts/Catalyst-Setup-24ba013-1.4.0.exe)

## Original TEST 7 read-only rollover

The preceding `6876f0f` app shut down through its native UI with the
cancel-offers checkbox unchecked after zero app and wallet offers were
observed. It exited and released port 5000. The exact `24ba013` EXE then
launched through the native UI and connected Sage mainnet TEST 7 fingerprint
736588221. Testing Risk Disclosure was acknowledged under the operator's
existing authorization; Splash was skipped and the existing Spacescan key
retained. Monkeyzoo Token MZ/XCH was selected.

The new app ran as sole PID 153748 and sole port 5000 listener from the
expected path, with the EXE hash above. Read-only status showed CAT wallet 2,
the expected asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced Sage, unchanged 138.470301476875 XCH and 780212.284 MZ balances,
zero app and wallet open offers, stopped bot, inactive Bootstrap, and allowed
safety with an owned renewing lease. No campaign or wallet action was started.

An exact-PID/path/hash stopped-profile monitor began at
`2026-10-06T10:19:23Z` in
`E:\catalyst-stability-monitor-24ba013\trace-60s.jsonl`; its first sample
showed a matching hash, synced wallet, stopped bot, zero offers, allowed
safety, and owned lease. The preceding trace is historical. The 24-hour gate
cannot pass before `2026-10-07T10:19:23Z` plus full trace and end-state
review. Both final-candidate 24-hour windows, active-offer lifecycle/recovery,
secondary original-profile acceptance, and final review remain required.
PR #220 stays draft.
