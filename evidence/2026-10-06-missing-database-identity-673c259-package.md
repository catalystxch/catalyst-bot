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
- Draft PR #220 CI on the integrated source is pending at this checkpoint.
  Its preceding docs-only head had 10 successful checks and a CodeQL code
  quality Python SARIF upload failure. Do not count the gate until all 11
  exact-source checks pass.

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

At this checkpoint the original TEST 7 profile still runs the prior
`bbf94f0` EXE in a stopped, read-only monitor. It has zero open offers and
no new campaign or fee approval. The exact `673c259` package has not yet
run against that profile. Its old monitor trace is historical after a
candidate rollover; a new exact-PID/path/hash trace must begin for this
candidate. Active-offer lifecycle and recovery, secondary original-profile
acceptance, both final-candidate 24-hour windows, CI, and final review
remain open. Keep PR #220 draft; do not merge, tag, release, or claim public
readiness.
