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

The current exact `13a842b` app remained safety-allowed at 20:26 UTC with a
renewing 30-second lease (version 166477, expiry 20:26:25.939908 UTC), bot
stopped, inactive Bootstrap, and zero open offers. Keep its original-profile
24-hour observation running through the next scheduled backup; record lease
version/expiry, safety state, process identity, wallet identity, offers, and
Sage health around that time. A recurrence requires root-cause analysis before
public readiness. No backup settings or wallet state were changed here.
