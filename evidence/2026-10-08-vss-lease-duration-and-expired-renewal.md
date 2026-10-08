# Snapshot-length lease stall and expired-renewal correction

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220).
This is an interim safety investigation, not public-readiness approval.

## Observed need

The original TEST 7 profile failed closed during two Veeam-overlap windows.
Independent process sampling recorded a 37-second gap in one event and earlier
gaps of 42–45 seconds around Windows snapshot activity. A 30-second mutation
lease with a 10-second heartbeat cannot survive such a host pause. The exact
blocked instruction remains unproven. A longer lease is acceptable only if
durable ownership, expiry and action-time mutation checks remain fail closed.

## Red regressions

Before the runtime change, a simulated 45-second database-stage pause after
10 seconds caused the default lease heartbeat to expire. A 90-second lease
also stretched the default heartbeat cadence to 30 seconds. These focused
tests failed as expected.

The concurrency proof exposed a separate expired-renewal gap. When an UPDATE
or COMMIT paused until after the **prior** lease expired, the durable
heartbeat could return success because it checked the replacement expiry
but did not recheck the prior expiry. Same-run acquisition had the same gap.
The regression found this even with the longer lease; it is a safety defect
independent of the duration choice.

## Correction and evidence pending

The default lease is 90 seconds while the default heartbeat cadence stays
10 seconds. Heartbeat and same-run acquisition recheck the prior lease expiry
after the durable write and after commit. A precommit expiry rolls back; a
postcommit expiry returns failure so the process fences itself. Existing
action-time status checks still read durable owner, version and expiry.
Delegated Coin Prep worker authorization retains a 30-second maximum age for
the parent heartbeat, independent of the longer process lease. The worker
checks the parent heartbeat and both delegation and lease expiries again
after its single durable authorization snapshot returns; a delayed read
cannot authorize an effect using the earlier timestamp. After 31 seconds
without a heartbeat, the parent can remain available for recovery but its
worker delegation fails closed until a fresh parent heartbeat.
If the parent process actually dies, takeover may now wait up to 90 seconds
for lease expiry and still requires proof that the prior PID is dead. This is
an availability cost; the worker's action-time authority retains the prior
30-second bound. An active Coin Prep worker encountering a snapshot pause
longer than that bound will fail closed and require normal reconciliation;
the live active-worker recovery path remains to be accepted.
Focused regressions pass for a 45-second pause, for 85-second pauses during
UPDATE and COMMIT, for mutation calls waiting behind the heartbeat lock, and
for denial after true expiry and refusal of takeover while the prior PID is
alive. Worker freshness and delayed-authorization-read regressions passed.
The final affected mutation-gate, long-gap-recovery and offer-journal suite
passed **561 tests**. The complete serial local Windows backend passed
**7,425 tests, 246 skipped, 455 subtests** in 20 minutes 45 seconds. Ruff
check, Ruff format check and `git diff --check` passed. Runtime/source commit
`7ce8ffafef3ac8e14c269348c5285a2e268e2734` was pushed to draft PR
#220. All **11** exact-source PR checks passed, including unit tests,
CodeQL, Semgrep, lint, and secret scanning. Original-profile live acceptance
is pending.

## Exact detached Windows package

Built from clean detached source `7ce8ffa` in
`E:\catalyst-vss-lease-7ce8ffa-build`; the build-generated `_version.py` is
the only tracked change in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `47198CA321C9E36692929D9661EEF99D51037743AB5EAB71D42022DDE3C92B77` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `B755796AE4327B941C10EB4B0E44097FD4FE95A20AAEDCAD01219AFE963522A4` |
| Unsigned installer | `42B7439C67628FE5ECC02D2555246B490714131159A3EB63A7072596A511FDE3` |

Packaged API, synthetic Sage RPC worker, interrupted-publication recovery,
and clean/duplicate/persisted native launch smokes passed. The ZIP has 192
files and 242 entries, passed CRC, and contains the exact EXE hash; its
extracted EXE passed the API smoke. An isolated QA installer with a unique
AppId and name installed the exact EXE to a distinct current-user Programs
directory, passed installed API and synthetic Sage smokes, then uninstalled
with its registration and EXE absent. Its `/DIR` override did not take effect,
but the unique AppId and name kept the installation separate. Defender
antivirus and real-time protection were enabled; custom scans of the bundle,
ZIP, and installer completed with the six prior detection records unchanged.

An additional isolated same-version upgrade check installed the prior exact
`96d5908` QA installer under `E:\catalyst-7ce8ffa-upgrade-qa\installed` using
the separate QA AppId `EA982408-C540-41A0-9866-4E89D051401E`. Its installed
EXE matched SHA-256 `99EFA45E430F7BBE8C49EAB9EEB735395762B0631A0CD66FA4B84C2F18D61664`.
A QA variant compiled from the exact `7ce8ffa` bundle with the same QA AppId
and uninstall key upgraded that installation in place with exit code zero.
The installed EXE then matched `47198CA321C9E36692929D9661EEF99D51037743AB5EAB71D42022DDE3C92B77`,
the registry retained the isolated E: install path, and an in-directory
sentinel survived. The upgraded EXE passed the packaged API and synthetic
Sage RPC smokes. The QA uninstaller returned zero, removed the EXE and its
HKCU entry, preserved the sentinel, and left the original TEST 7 process
running from its separate path. Test logs and the QA script are retained in
`E:\catalyst-7ce8ffa-upgrade-qa`. This verifies the installer upgrade path in
isolation; it does not establish original-profile live recovery.

The binaries and manifest were pinned at artifact commit
`09d851342dcd0094e2ded1679db63f2e55d01438`:
[ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/09d851342dcd0094e2ded1679db63f2e55d01438/acceptance-artifacts/CATalyst-7ce8ffa-primary-acceptance.zip),
[unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/09d851342dcd0094e2ded1679db63f2e55d01438/acceptance-artifacts/Catalyst-Setup-7ce8ffa-1.4.0.exe),
and [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/09d851342dcd0094e2ded1679db63f2e55d01438/acceptance-artifacts/SHA256SUMS-7ce8ffa.txt).
Independent HTTP downloads of both binaries matched their hashes; the
downloaded ZIP passed CRC and contained the same EXE hash.

The older TEST 7 app remains in its read-only `HEARTBEAT_FAILED` fence. No
wallet effect, campaign start, or existing-profile restart was performed by
this investigation. The earlier failed 24-hour traces stay failed.
