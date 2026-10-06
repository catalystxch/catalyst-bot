# Exact `673c259` stopped-profile heartbeat failure

On 2026-10-06 the original TEST 7 profile ran the exact clean `673c259`
EXE from `E:\catalyst-missing-db-673c259-build\dist\Catalyst\Catalyst.exe`.
Its SHA-256 was
`1C4D4E0BB986A3257C2DBB9CB9B8145BB2434268C4B3B62D6AA84CE555685347`.
The process was PID `150260`, the sole port 5000 owner. The bot was stopped,
Bootstrap inactive, and there were zero open offers.

The read-only monitor at
`E:\catalyst-stability-monitor-673c259\trace-60s.jsonl` began at
`20:48:11Z`. Sample 12 at `20:59:46.3479598Z` was safety allowed with
lease version `183880` and expiry `21:00:09.422602Z`. Sample 13 at
`21:00:48.7261315Z` reported `HEARTBEAT_FAILED`, with lease version
`183882` and expiry `21:00:29.444840Z`. The durable lease snapshot
recorded its last heartbeat at `20:59:59.444840Z`: it had the requested
full 30 seconds, but was not renewed before expiry. Samples 14–16 remained
failed. The monitor's 24-hour acceptance window is **failed**, regardless
of later samples.

Windows Application Event Log event `VSS/8231` records a snapshot start at
`20:59:48.0171434Z` by `taskhostw.exe -RegisterDevice -Periodic`. Windows
Backup's task state was `Ready` when the minute monitor later sampled it;
that state does not exclude this VSS activity. A Windows time-service sync
adjusted the clock backwards about 1.2 seconds at `21:00:01Z`; that small
adjustment alone does not explain the roughly 19-second missed-renewal gap.
The VSS event is a second correlation with the earlier failed candidate,
not proof that VSS blocked SQLite or Python.

The application superlog
`%APPDATA%\Catalyst\bot_superlog_20261006_214454.log` reported several
Sage RPC connection errors at `21:00:38Z`. Concurrent `get_chia_health`
calls took about 27.7, 33.8, and 40.4 seconds. The
`mutation-lease-heartbeat` thread logged its terminal read-only safety stop
at `21:00:48.445Z`. Windows Backup was `Ready` in the failing monitor
sample. The existing log does not show when the heartbeat began waiting,
whether it waited on the gate lock or SQLite, or the database
result/exception. Root cause is
still open; a longer lease alone would be an unproven workaround.

After failure, read-only `/api/safety/status` showed the terminal
`HEARTBEAT_FAILED` fence, an expired same-run lease, and zero durable
blockers. `/api/health` reported `bot_running=false` and a synced Sage
wallet. `/api/bootstrap/status` showed inactive Bootstrap and the expected
mainnet fingerprint `736588221`, CAT wallet ID `2`, and exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
`/api/offers` returned zero buys and sells. This demonstrates fail-closed
behavior, not live stability. No wallet action, offer, new campaign, or fee
approval occurred during this investigation.

Do not merge PR #220 or claim public readiness. Keep the failed process
read-only while gathering diagnostics. Determine why the heartbeat missed
renewal, verify a correction on an exact packaged candidate, and restart
the required 24-hour acceptance window from that candidate.

## Follow-up diagnostic work

The source branch now records a bounded timing event for each heartbeat in
the normal in-memory debug ring. A slow heartbeat writes a warning; a
failed one writes an error after dispatching the stop callback. The event
separates local gate-lock wait from each SQLite attempt and records the
result, exception type, and numeric SQLite error code. Exception messages
are omitted. This instrumentation is for a future recurrence; it cannot
retroactively identify this failure's blocked boundary and is not a fix.
The mutation-gate, stability-schema, and startup-recovery suites passed
**414 tests** with the diagnostic change. The original failed process
was shut down cleanly from the local UI with offer cancellation off. Its
monitor trace was retained. The clean detached diagnostic build is source
`cfa42f376c1e53f69280e0cf5ce983a1e39d2acb` with EXE SHA-256
`7891AFDCF91F66A0323FFD88A023824FD4D17FD6FA929297B7395E4F1BF6164B`.
At `21:18:42Z` the exact diagnostic EXE ran as sole PID `137816` and port
5000 owner on the original TEST 7 profile. Read-only checks verified
mainnet fingerprint `736588221`, CAT wallet ID `2`, the exact MZ asset,
synced Sage, stopped bot, inactive Bootstrap, zero open offers and an
allowed renewing lease. Its exact PID/hash one-minute monitor is
`E:\catalyst-stability-monitor-cfa42f3\trace-60s.jsonl`; the first
sample passed. This run is intended to identify the blocked heartbeat
boundary if the failure recurs, not to support public readiness.

## Postmortem logging correction

The failed candidate emitted its safety stop through `slog(...,
level="critical")`, but `super_log.LEVELS` did not recognize `critical` and
silently ranked it as `info`. This explains why the old safety stop did not
flush the in-memory debug context. It does **not** explain the missed lease
renewal. Commit `e694dab2a02801f5f0337c389888e5f5b9eb665e` recognizes
`critical` above `error`, so future critical safety stops persist even at an
error file threshold and dump preceding debug context. The two focused
regressions failed before the correction and passed afterward. The combined
super-log, mutation-gate, stability-schema and startup-recovery suite passed
**449 tests**; Ruff and `git diff --check` passed. The already-running
diagnostic EXE remains source `cfa42f3`; its explicit heartbeat failure
timing event uses `error` and is available independently of this subsequent
logger fix. The current PR source has not yet been packaged or accepted live.
