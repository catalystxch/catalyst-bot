# User data directory fail-closed fix and package checkpoint

## Defect and correction

On source `cb6bfc8`, an isolated `CMM_DATA_DIR` beneath a regular file made
`user_paths.data_dir()` return the installation directory. It selected the
install-side `.env` and `bot.db` paths and created `.migration_complete` there.
Both `config.py` and `database.py` also caught path-resolution errors and
independently selected install-side profile files. This could silently start
with a different profile if the expected user data directory was unavailable.

Source commit `19ded8889582d0ede56a6cd49c8e327db84f99a0` removes all three
profile fallbacks. `data_dir()` raises a clear `OSError`; config and database
imports propagate it. The red regression failed on the original behavior and
passed after the fix, including blocked `config` and `database` imports and the
absence of an install-side migration marker.

## Source verification

- Full serial local Windows backend: 7,281 passed, 232 skipped, 433 subtests
  passed in 1,129.94 seconds.
- Repository-wide Ruff check and format check passed (620 files formatted).
- The bundled HTML is byte-identical to source (SHA-256
  `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574`).
- Draft PR #220 passed all 11 CI checks on this source head, including
  `unit-tests`.

## Clean detached Windows package

Built from detached exact source at `E:\catalyst-user-data-failclosed-build`.
The EXE SHA-256 is
`001EFDD68314D335470A421721569E16043119CA415F4FF6093FE1569124B6D6`.
The 192-entry ZIP SHA-256 is
`2D6A58226F45257F5A007D842783367D6896DD15983390DFE338989349626D80`;
CRC passed, its EXE hash matched, and it contains no `.env`, `bot.db`, WAL, SHM,
or migration marker. The unsigned installer SHA-256 is
`0D3B5567E519C7C8F4049B337CF5EE3C6885AE1A9A4B89EF34CD56BECDAD4FC6`.
The ZIP, installer, checksum manifest, and checkpoint note are pinned to
artifact commit `129ff234c1e6b2d257143bfe603114908e06f38f`.
Independent HTTP downloads of both binaries matched the local hashes.
Pinned downloads: [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/129ff234c1e6b2d257143bfe603114908e06f38f/acceptance-artifacts/CATalyst-19ded88-primary-acceptance.zip)
and [unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/129ff234c1e6b2d257143bfe603114908e06f38f/acceptance-artifacts/Catalyst-Setup-19ded88-1.4.0.exe).

Packaged API, synthetic Sage RPC, publication recovery, and native
clean/duplicate/persisted/safety smokes passed. The downloaded ZIP extracted
to 192 files with the expected EXE hash and passed the packaged API smoke.
With an intentionally unavailable isolated data path, the package entered
read-only diagnostics; its isolated process was stopped, and no install-side
profile file, migration marker, or test listener remained. A unique-AppId
current-user QA installer installed the exact EXE in an isolated E: path. The
installed API smoke passed. Uninstall removed the EXE and QA registration.
Defender custom scans of the bundle, ZIP, and installer added zero detections.

## Live and release status

The previous `6e2dcef` original-profile process shut down normally while
stopped with zero offers. Its monitor is historical for this new runtime.
The exact `19ded88` EXE then started on the original TEST 7 profile as the
sole `Catalyst.exe` and port 5000 owner, PID 157976, with its process path
and SHA-256 independently rechecked. Risk Disclosure was acknowledged for
testing in the native UI. Sage wallet TEST 7 fingerprint `736588221` was
selected in the UI, and the MZ/XCH pair was selected. Live read-only APIs
then reported mainnet Sage, CAT wallet ID 2, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, unchanged 138.470301476875 XCH and 780212.284 MZ balances,
bot stopped, zero open offers, inactive Bootstrap, and safety ALLOWED with
an owned renewing lease. No campaign or wallet action was taken.

An exact-PID/hash 60-second stopped-profile monitor started at
`2026-10-06T18:45:21Z` in
`E:\catalyst-stability-monitor-19ded88\trace-60s.jsonl`. Its first sample
was clean. The 24-hour gate cannot be counted before
`2026-10-07T18:45:21Z` and a complete trace and end-state review. The separate
active-offer 24-hour window has not started. Active-offer lifecycle and
recovery, secondary original-profile acceptance, final installer/update
acceptance, and final review remain open. No new campaign or fee approval
exists. PR #220 remains draft; do not merge, tag, release, or claim public
readiness.
