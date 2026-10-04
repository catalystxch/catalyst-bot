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
