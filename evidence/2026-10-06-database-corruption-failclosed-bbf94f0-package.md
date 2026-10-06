# Database corruption must preserve trading authority

Draft PR #220 exact runtime/source: `bbf94f0f379fe7965ad079009b68e9cdfec380d7`.
The focused fix was tracked in draft PR #249 before its non-force
fast-forward into the feature branch.

## Defect and correction

On the preceding candidate, a malformed `bot.db` caused
`attempt_db_recovery()` to return `recovered` with `fallback=fresh_start` after
deleting the live database. A dump that skipped individual SQL statements
could also replace the live database with partial authority. The desktop
startup path ignored recovery failure, and `main()` repeated recovery after
startup authorization. The standalone `scripts/recover_db.py` likewise
removed the live file before a replacement that could fail. These paths could
discard offer, mutation, or fee records while Sage still held wallet effects.

The exact source now preserves `bot.db` and its sidecars whenever integrity
fails. It saves a forensic backup and, when possible, a separate recovered
candidate. A readable dump does not prove all authority rows survived, so
normal startup enters read-only diagnostics until an operator reconciles the
database with Sage. The standalone script also leaves the live database
untouched, discards incomplete candidates, and requires a separate reviewed
replacement. The duplicate post-authorization recovery call was removed.

Red/green regressions covered malformed startup, partial SQL salvage, the
post-authorization repeat, a readable dump from an integrity-failed source,
and the standalone script. The affected startup/mutation/recovery suite passed
281 tests before the last standalone-script guard; its final focused suite
passed 24. Exact-source full serial Windows backend passed **7,287 tests,
232 skipped, 433 subtests** in 1,338.98 seconds. Repository-wide Ruff check
and format passed across 623 files. Bundled HTML is byte-identical to the
preceding candidate, whose complete 231-test Chromium suite passed. All 11
exact-source PR checks passed, including `unit-tests`.

## Clean Windows package

Built from a detached exact-source checkout at
`E:\catalyst-db-recovery-bbf94f0-build`.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `DD680692E00612BE9314B1FFCFB7CBCCB78568BCD1A434EF14284BB9980B9331` |
| Bundled `bot_gui.html` | `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574` |
| Acceptance ZIP | `9E5115475CF5E09F8DFA760D9E9102979BB463401B966AFDA66AB0C511451957` |
| Unsigned installer | `31E9326D6D5DD2B3A3AA4404D1917DA67383BC5CB61CD2142EBF5997FDC705EA` |

The 192-file ZIP passed CRC, excluded `.env`, `bot.db` and sidecars, and its
extracted EXE matched the source bundle hash. Package API, synthetic Sage,
publication recovery, native clean/duplicate/persisted/safety, and extracted
ZIP API smokes passed. An isolated packaged corrupt-profile launch entered
read-only diagnostics with safety denied and preserved malformed `bot.db`
byte-for-byte. A unique-AppId and unique-name QA installer clean-installed to
an isolated E: directory, passed installed API and Sage smokes, and uninstalled
with its registration gone. The original TEST 7 process was unaffected.
Defender custom scans of the bundle, ZIP, and installer added zero detections.

The ZIP, installer, manifest, and checkpoint are pinned at artifact commit
`6b05b13aa4b7397eaaf14514af9a3754840fb92a`. Independent HTTP downloads
of the pinned ZIP and installer matched the listed hashes.

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/6b05b13aa4b7397eaaf14514af9a3754840fb92a/acceptance-artifacts/CATalyst-bbf94f0-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/6b05b13aa4b7397eaaf14514af9a3754840fb92a/acceptance-artifacts/Catalyst-Setup-bbf94f0-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/6b05b13aa4b7397eaaf14514af9a3754840fb92a/acceptance-artifacts/SHA256SUMS-bbf94f0.txt)

## Live and release status

The preceding exact `19ded88` original-profile process shut down normally
while stopped with zero open offers. Its 47 stopped-profile samples from
`2026-10-06T18:45:21Z` to `19:33:56Z` had zero failures and are historical.
The exact `bbf94f0` EXE became the sole original TEST 7 process and port 5000
owner as PID `66924`, with the expected path and hash. The native UI selected
Sage mainnet TEST 7 fingerprint `736588221` and MZ/XCH. Read-only API and UI
checks found CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
unchanged balances of `138.470301476875` XCH and `780212.284` MZ, synced
Sage, zero open offers, stopped bot, inactive Bootstrap and safety ALLOWED
with an owned lease. No wallet effect, campaign, or fee approval occurred.

A fresh exact-PID/path/hash stopped-profile monitor began at
`2026-10-06T19:40:41Z` in
`E:\catalyst-stability-monitor-bbf94f0\trace-60s.jsonl`; its first sample
passed. The 24-hour gate needs the complete trace and end-state review no
earlier than `2026-10-07T19:40:41Z`. The exact native Dashboard, Offers, P&L,
Market Intelligence, Settings Setup/Live, Logs, Data Reset, Help, and About
views passed read-only traversal. Post-traversal API checks retained the sole
expected PID/hash/port owner, selected TEST 7/MZ identity, unchanged balances,
synced Sage, stopped bot, zero open offers, inactive Bootstrap, and allowed
safety. The first three monitor samples had zero failures. Independent Sage
RPC reads found zero pending transactions and zero fillable offers after
normalizing the complete 4,095-offer history; Sage ignored its
`include_completed=False` filter, so the adapter applied the status filter.
Active-offer lifecycle and recovery, secondary original-profile acceptance,
both final 24-hour windows, final review, and release authorization remain open. Keep
PR #220 draft; do not merge to main, tag, release, or claim public readiness.
