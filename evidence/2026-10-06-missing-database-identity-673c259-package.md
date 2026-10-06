# Missing database and profile identity: exact `673c259` candidate

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220),
integrated from draft [#250](https://github.com/catalystxch/catalyst-bot/pull/250).
Exact runtime/source: `673c259720e94dcee304e98710c5f23891ee1e2b`.

## Defect and correction

An established profile whose `bot.db` disappeared was treated as a first
launch. A different but healthy SQLite database could also pass the integrity
check. Either case could lose local offer, mutation, and fee authority while
Sage still held wallet effects. The recovery gate now rejects a missing DB
when durable profile evidence exists. Successful initialization pairs a
random database identity stored in SQLite with a database-adjacent marker;
subsequent startup rejects a missing or mismatched pair before migrations.
A genuinely new profile, including one with a preconfigured `.env`, still
creates its first database. The marker is a continuity check, not an
adversarial tamper-proof seal; legacy profiles obtain it on successful
initialization.

## Exact-source verification

- Red/green missing-file and healthy-replacement regressions passed.
  Focused recovery/startup suite: 32 passed.
- Full serial local Windows backend: **7,297 passed, 232 skipped, 433
  subtests passed** in 22m 39s (`python -m pytest tests -q -n 0`).
- Repository-wide Ruff check and format passed across 624 files.
- Bundled `bot_gui.html` SHA-256
  `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574`;
  bytes are unchanged from the prior candidate whose complete 231-test
  Chromium suite passed.
- All **11 PR #220 checks passed** on the exact source and its evidence-only
  child `7f97cae2695431bd5d1fd87b9023af8d913e517b`, including unit tests,
  both Python CodeQL analyses, security scans, and lint. The earlier
  docs-only head's CodeQL code-quality Python SARIF upload failure did not
  recur.

## Detached Windows package

The clean detached worktree was checked out at exact `673c259`. The EXE is
`E:\catalyst-missing-db-673c259-build\dist\Catalyst\Catalyst.exe`, SHA-256
`1C4D4E0BB986A3257C2DBB9CB9B8145BB2434268C4B3B62D6AA84CE555685347`.

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8a55986c1bae69dbcfc18b0474fe54e4d58c14d5/acceptance-artifacts/CATalyst-673c259-primary-acceptance.zip): SHA-256
  `08BFF24B030D0B8FDEC158989ACF0D90C9A3FB206E376765E79C7FADEDE1FE5B`.
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8a55986c1bae69dbcfc18b0474fe54e4d58c14d5/acceptance-artifacts/Catalyst-Setup-673c259-1.4.0.exe): SHA-256
  `D29474DA27DAC6E1825A59E6EB642007C30E82152C991D679FE591122F96D9D8`.
- [Pinned SHA manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8a55986c1bae69dbcfc18b0474fe54e4d58c14d5/acceptance-artifacts/SHA256SUMS-673c259.txt).
  Independent HTTP downloads of both binary artifacts matched these hashes.

Package API, synthetic Sage RPC, native clean/duplicate/persisted/safety,
isolated native missing DB with marker, legacy backup without marker, valid
replacement database identity mismatch, packaged upgrade publication
recovery, 192-entry ZIP CRC/forbidden-file audit, extracted ZIP API,
unique-AppId QA installer clean install/installed API and Sage/uninstall,
and Defender scans (zero new detections) passed. These isolated tests did
not use the original TEST 7 profile.

## Live state and open gates

The prior `bbf94f0` original-profile process shut down normally through the
native UI with the offer-cancellation checkbox unchecked, while the bot was
already stopped and there were zero active offers. Its 61 clean stopped
samples from `2026-10-06T19:40:41Z` through the intentional shutdown are
historical.

The exact `673c259` EXE is now the sole original TEST 7 process, PID
`150260`, and port 5000 owner. Its process hash matched the packaged EXE.
The native UI acknowledged the testing Risk Disclosure, connected Sage,
selected fingerprint `736588221` and Monkeyzoo Token (MZ/XCH), continued
without optional Splash, and retained the configured Spacescan setting.
Read-only Dashboard, Offers, P&L, Market Intelligence, Settings Setup/Live,
Logs, Data Reset, Help, and About traversal passed without a wallet effect
or settings save. Post-traversal API checks showed Sage mainnet, CAT wallet
ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, unchanged `138.470301476875` XCH and `780212.284` MZ,
zero open offers, bot stopped, inactive Bootstrap, and safety ALLOWED with
an owned lease. The legacy original-profile database has its new
`bot.db.initialized` marker.

A new exact-PID/path/hash stopped-profile monitor began at
`2026-10-06T20:48:11Z` in
`E:\catalyst-stability-monitor-673c259\trace-60s.jsonl`. Its first three
samples were clean. The 24-hour gate cannot pass before
`2026-10-07T20:48:11Z` plus a complete trace and end-state review.
Active-offer lifecycle and recovery, secondary original-profile acceptance,
the stopped and active final-candidate 24-hour windows, and final review
remain open. No new campaign or fee approval exists. Keep PR #220 draft;
do not merge, tag, release, or claim public readiness.
