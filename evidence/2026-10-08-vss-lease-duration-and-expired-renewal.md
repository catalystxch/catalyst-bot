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
check, Ruff format check and `git diff --check` passed. Exact package, CI,
and original-profile live acceptance are pending.

The older TEST 7 app remains in its read-only `HEARTBEAT_FAILED` fence. No
wallet effect, campaign start, or existing-profile restart was performed by
this investigation. The earlier failed 24-hour traces stay failed.
