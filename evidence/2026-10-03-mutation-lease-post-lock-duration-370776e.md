# Mutation lease timing after delayed durable writes

Draft PR #220 source commit: `370776e53b957c57e3b77ed12b4060f540b22521`.
The exact source includes `6298872e4333f3e8b9e442fed4c70dae4f83659d`
and its compatibility correction in `370776e`.

## Live finding

The operator-started, exact `e99cbf2` primary TEST 7 process remained on the
original profile. At 2026-10-03 13:50:53 UTC it switched to read-only with
`HEARTBEAT_FAILED`. The bot remained stopped. Read-only safety status showed
zero operation blockers, but mutation authority was denied. The durable lease
recorded `heartbeat_at=2026-10-03T13:50:13.306777Z` and
`expires_at=2026-10-03T13:50:24.342434Z`: only 11.035657 seconds remained
after that heartbeat, versus the 30 seconds requested by the mutation gate.
The critical stop is in
`C:\Users\t_you\AppData\Roaming\Catalyst\bot_superlog_20261003_144550.log`
line 176. Sage RPC was temporarily unreachable in nearby logs. The observed
delay between the request timestamp and the durable write shortened the stored
lease; the exact source of that delay was not established. The subsequent
fail-closed stop was correct and had no wallet effect.

## Root cause and correction

The database captured the requested expiry before obtaining its write lock,
then stored a later post-lock heartbeat/acquisition timestamp with that
unchanged expiry. A 15-second injected delay made two focused regressions
fail: heartbeat and acquisition stored 15 seconds of a requested 30-second
lease. A third regression confirmed an already expired lease remains denied.

The first patch also exposed a compatibility case: direct database callers
may specify an absolute expiry with a historical request timestamp. A wider
recovery test failed because deriving a duration from that absolute interval
would extend the lease too far. The final source therefore requires an
explicit `lease_duration_seconds` from the mutation gate for acquisition,
heartbeat, and recovery successor adoption. Those three paths preserve the
requested duration after a delayed write, provided the original requested
expiry has not already passed. Existing absolute-expiry callers retain their
expiry unchanged. Recovery successor adoption also had a red regression
before this correction; it now stores the full 30-second duration. An expired
lease still cannot be resurrected.

The affected long-gap recovery and mutation-gate selection passed **316
tests**. Ruff check, formatting, and diff checks passed. The complete local
Windows backend run passed **7,163 tests**, with **209 skipped** (including
208 opt-in browser tests) and **427 subtests passed** in 32m 29s. All **208
Chromium tests** passed separately, and all **11 PR checks** passed on
`370776e`.

## Clean Windows package

The detached build at `E:\catalyst-lease-6298872-build` was checked out at
`370776e` before packaging. Its executable SHA-256 is
`13BB1838887876FDD8C701F555B54BBF2A4498B2F65B557B3FD80313B94968C0`;
bundled UI SHA-256 is
`575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7`.
The 206-entry ZIP SHA-256 is
`2500C8437EE05204CA8FA80383A4B369AD12A31B84C5D94943DAD6BD98EAD58A`;
the unsigned public installer SHA-256 is
`8F6F93E9C6BAE32A4EFA417765C1379DF794FCB1EC78E9C12035AD8C6D016F28`.

Packaged API, synthetic Sage RPC, publication recovery, native clean and
duplicate launch, persisted-profile relaunch, and native safety smokes
passed. ZIP CRC and extracted-app API passed. A unique-AppId current-user QA
installer passed clean install, installed API/Sage, same-version upgrade from
the verified `e99cbf2` package, rollback, restore, and uninstall. The
installed EXE hash matched the intended version at every transition; the
QA directory and registration were absent afterward. Defender custom scans
of the bundle, ZIP, and unsigned installer reported zero matching detections.
These synthetic and isolated checks did not touch the original TEST 7 profile.

The ZIP and installer are pinned to artifact commit
`8ae48499f13fac0ce4a3124eb422d20efb956f06`; a separate artifact
manifest is at `8121ab8`. Independent HTTP downloads of both pinned binaries
matched the local SHA-256 values above:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8ae48499f13fac0ce4a3124eb422d20efb956f06/acceptance-artifacts/CATalyst-370776e-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8ae48499f13fac0ce4a3124eb422d20efb956f06/acceptance-artifacts/Catalyst-Setup-370776e-1.4.0.exe)

## Still open

The original TEST 7 process is still the superseded `e99cbf2` EXE and remains
read-only after its safety stop. `370776e` has not run against the original
profile. No new campaign or fee approval has been received; the older
approval must not be reused. Live restart/recovery and wallet lifecycle,
full interactive UI, both 24-hour windows, and independent secondary
acceptance remain open.
PR #220 stays draft. There is no main merge, tag, release, or public-readiness
claim.
