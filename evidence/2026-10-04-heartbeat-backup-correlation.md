# Stopped-profile heartbeat failure: host backup correlation

The earlier exact `244da2e` TEST 7 app failed closed with `HEARTBEAT_FAILED`
while the bot was stopped and no offers were open. Its last durable heartbeat
was `2026-10-04T18:01:30.749034Z`, with a full 30-second lease expiring at
`18:02:00.749034Z`. The application logged three Sage RPC connection timeouts
at `18:01:56Z` and the safety stop at `18:02:07.689Z`. The heartbeat did not
renew before the durable expiry. This is a failed live stability window, even
though mutation safety correctly failed closed.

Read-only Windows Event Log inspection on the same host found a Windows Backup
start at **18:00:00 UTC** (19:00:00 local), targeting `H:\`, and a VSS snapshot
start at **18:00:49 UTC** (19:00:49 local). NTFS reported two healthy shadow
copy volumes at 18:01:02–03 UTC. Veeam power-policy events appeared nearby.
The backup and snapshot overlap the lease interruption and Sage timeouts. They
are a plausible shared load source, **not a proven cause**: no event or trace
yet attributes the missed heartbeat to VSS, SQLite, Sage, or process scheduling.

The current exact `13a842b` app remained safety-allowed at 20:28 UTC with a
renewing 30-second lease (version 166494, expiry 20:29:16.126754 UTC), bot
stopped, inactive Bootstrap, and zero open offers. Windows Task Scheduler still
reported `AutomaticBackup` running at that time; its last start was 19:00
local and its next scheduled start is **11 October at 19:00 local**. Thus the
new process has stayed live during the ongoing backup, but its current 24-hour
window will not include a second scheduled backup start. Continue the live
stability observation and record lease version/expiry, safety state, process
identity, wallet identity, offers, and Sage health. A recurrence requires
root-cause analysis before public readiness. No backup settings or wallet
state were changed here.

At 20:34 UTC a read-only 10-second stability sampler started as hidden
PowerShell PID `148212`. It verified the exact Catalyst PID `147840` and EXE
SHA-256 before writing to
`E:\catalyst-stability-monitor-13a842b\trace.jsonl`. The sampler script is
`E:\catalyst-stability-monitor-13a842b\monitor.ps1` (SHA-256
`31036BBE7F4C3C4A622F90C2F59939BB9F755CCC2EF4985FFE390FE298F19BB0`).
It reads only loopback safety status every 10 seconds and reads health,
open-offer count, and Windows Backup task state every minute. It logs UTC
timestamps, request latency, lease version/expiry and errors, and stops if the
target PID exits or after 25 hours. Its first two samples found successive
lease versions `166526` and `166528`, safety allowed, zero open offers, synced
Sage, and the backup still running. The trace must be reviewed before any
24-hour stability claim; starting the sampler does not pass that gate.

At 20:43 UTC the first sampler was stopped after 52 samples because the
`/api/safety/status` read holds the mutation-gate lock while it reads SQLite;
ten-second polling could add avoidable contention with lease heartbeats during
backup load. Those 52 samples had no safety failure, and the maximum observed
status latency was 1,566 ms. The trace ends with an explicit frequency-change
record. No CATalyst process was stopped or restarted.

A replacement sampler began at 20:43:23 UTC as hidden PowerShell PID `7880`,
using one read-only status, health, offer-count and backup-state sample per
minute. It writes
`E:\catalyst-stability-monitor-13a842b\trace-60s.jsonl`; its revised script
SHA-256 is
`D4E042C7EA9BDAF1067BE3F6F89BEBE32D2003499183FDF04BC1380AEBA2B7FD`.
The first new sample verified the same exact EXE hash, safety allowed, lease
version `166581`, bot stopped, Sage synced, zero open offers and backup running.
Review the complete one-minute trace at the 24-hour gate; the replacement
monitor itself is not a stability pass.
