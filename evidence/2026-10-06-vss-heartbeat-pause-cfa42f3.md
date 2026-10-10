# Exact diagnostic heartbeat failure during a Windows Update snapshot

The original TEST 7 profile ran the clean diagnostic source
`cfa42f376c1e53f69280e0cf5ce983a1e39d2acb` as the sole CATalyst process,
PID `137816`, from
`E:\catalyst-heartbeat-diag-cfa42f3\dist\Catalyst\Catalyst.exe`. Its SHA-256
was `7891AFDCF91F66A0323FFD88A023824FD4D17FD6FA929297B7395E4F1BF6164B`.
The bot was stopped, Bootstrap inactive, and there were no open offers.

The exact-PID/hash minute monitor at
`E:\catalyst-stability-monitor-cfa42f3\trace-60s.jsonl` began at
`21:18:42Z`. Samples 1–28 were allowed with a renewing lease. Sample 29 at
`21:48:23Z` could not read the safety endpoint (`WebException`); its separate
read-only health checks still showed a stopped bot and zero open offers.
Sample 30 at `21:50:51Z` showed terminal `HEARTBEAT_FAILED`, stopped bot,
zero offers, and an expired same-process lease. The trace ended there.
The trace SHA-256 is
`808532FC6A2C6CF4AFBDA7A54D765BFA4D3450D6584C4E95D5CC8D2C099EC5A0`.

The durable row after failure was version `184071`, heartbeat
`21:48:15.675432Z`, expiry `21:48:45.675432Z`. The diagnostic superlog
recorded one heartbeat call returning `heartbeat` at `21:49:04.662Z` after
**49.000 seconds**, entirely within its database attempt (`lock_wait_ms=0`).
It therefore reported success after its stored expiry had already passed.
The next heartbeat returned `lease_expired` at `21:49:49.938Z` after **35.266
seconds** in its database attempt (`lock_wait_ms=0`); CATalyst invoked the
terminal stop handler first. Concurrent Sage `get_chia_health` calls took
22.97–48.21 seconds. This confirms a false-success result after a delayed
heartbeat write or return, followed by the correct fail-closed stop. The
diagnostic timing does not identify which SQLite operation waited.

An independent five-second process sampler at
`E:\catalyst-stability-monitor-cfa42f3\os-timeline-5s.jsonl` recorded gaps
of **42.519 seconds** ending `21:49:09Z` and **45.254 seconds** ending
`21:49:54Z`. CATalyst CPU time advanced little across the first gap. Its
trace SHA-256 is
`17EB934E6DC32D3B53B14DC42EAFFE93A9AF8919B8F4FA6AB4F750DBD0FD78CC`.
Windows Update Operational events reported update downloads at
`21:47:44–21:47:49Z`; Application event `VSS/8231` recorded a snapshot
initiated by `svchost.exe -k netsvcs -p -s wuauserv` at `21:48:02Z`;
System event `Ntfs/98` reported its shadow-copy volume healthy at
`21:48:15Z`. These independent observations strongly associate the stalls
with Windows Update snapshot activity, but do not prove the exact blocked
instruction or that VSS alone caused the delay.

Read-only post-failure API checks confirmed process PID `137816` remained
alive in its terminal safety fence; Sage was synced, the bot stopped,
Bootstrap inactive, and open offers and unresolved blocker counts were zero.
The selected asset remained exact MZ wallet ID `2`, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Balances remained 138.470301476875 XCH and 780212.284 MZ. No wallet effect
was performed during this diagnostic run.

Two focused red/green regressions exposed the false-success path: an
in-transaction delay beyond expiry and a delay after the durable call returns
but before the gate handles its result. The source correction checks expiry
before and after durable commit and again when the gate receives the result.
Another red/green regression fences immediately if the background heartbeat
worker exits through an unexpected exception. These corrections improve
fail-closed accuracy; they do **not** make a 30-second lease survive the
observed 42–45-second stalls. Public-readiness and both exact-candidate
24-hour windows remain open. Do not count this diagnostic run as acceptance.
