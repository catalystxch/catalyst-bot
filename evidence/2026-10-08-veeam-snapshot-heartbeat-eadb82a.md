# Original-profile pre-startup heartbeat failure during Veeam snapshot

This is a read-only incident record for draft PR
[#220](https://github.com/catalystxch/catalyst-bot/pull/220). It concerns the
older `eadb82a` original TEST 7 app, not the packaged exact `60e2875`
candidate. No wallet action or campaign was started.

The sole app was PID `120856` from
`E:\catalyst-sage-tls-eadb82a-build\dist\Catalyst\Catalyst.exe`, SHA-256
`8E8EFDD7A175FE50D5BF168AF0EB4D6A4E7FB557BC8C6B68B2111C834356EF02`,
and owned loopback port 5000. Its bot was stopped and the app reported zero
open offers. At the final read-only API check it reported safety disallowed
with `HEARTBEAT_FAILED`, lease version `191145`, and an expired lease at
`2026-10-07T23:31:48.971579Z`. It remained in the safety fence.

The 60-second monitor at
`E:\catalyst-stability-monitor-eadb82a\safety-60s-prestartup.jsonl` recorded
allowed safety through sample 292 at `23:30:45.786Z`. Sample 293 began at
`23:31:46.884Z` and returned `HEARTBEAT_FAILED` after 4,462 ms. Later
samples retained the failure; sample 296 had a loopback `WebException`.

The app's `bot_superlog_20261007_191952.log` shows a successful heartbeat
at `23:31:08.969Z`, then the next heartbeat starting at `23:31:18.971Z`.
Its SQL `COMMIT` was logged at `23:31:18.977Z`; the heartbeat thread did not
return until `23:31:51.346Z`. Stage timing reported
`outcome=lease_expired`, `elapsed_ms=32281`, `lock_wait_ms=0`, and
`database_ms.finish=32285`. The 30-second lease expired before the durable
heartbeat could complete, and the app switched to read-only at
`23:31:51.265Z`.

Windows Application event VSS/8231 records a Veeam-initiated snapshot at
local `2026-10-08 00:31:00` (BST, `2026-10-07T23:31:00Z`). The independent
5-second OS trace at
`E:\catalyst-stability-monitor-eadb82a\os-timeline-5s.jsonl` has a
37,328 ms gap from `23:31:18.944Z` to `23:31:56.273Z`; app CPU advanced by
only about 1.03 seconds across that gap. This strongly correlates the
heartbeat stall with the snapshot. The traces do not prove which specific
VSS or storage operation stalled the SQLite commit.

This is a second snapshot-overlap fail-closed heartbeat on the original
profile, following the `f0e1e97` event recorded in
`evidence/2026-10-07-veeam-snapshot-heartbeat-f0e1e97.md`. Both stopped bot
monitor windows failed. No live 24-hour gate can be credited from either.
The app must not silently regain mutation authority merely because the
snapshot completed. A reliability change requires mutation-fencing proof and
new exact-candidate acceptance; extending the lease duration alone would
weaken the safety boundary without that proof. Exact `60e2875` has not run
against the original profile, and its own live lifecycle and both 24-hour
windows remain open.
