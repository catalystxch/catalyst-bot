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

The application superlog
`%APPDATA%\Catalyst\bot_superlog_20261006_214454.log` reported several
Sage RPC connection errors at `21:00:38Z`. Concurrent `get_chia_health`
calls took about 27.7, 33.8, and 40.4 seconds. The
`mutation-lease-heartbeat` thread logged its terminal read-only safety stop
at `21:00:48.445Z`. Windows Backup was `Ready` in the failing monitor
sample, so an active backup is not established as the cause. The existing
log does not show when the heartbeat began waiting, whether it waited on
the gate lock or SQLite, or the database result/exception. Root cause is
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
