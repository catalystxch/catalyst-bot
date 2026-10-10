# Secondary C: capacity plan — read-only inventory

At 2026-10-09T11:29Z the independent secondary PC had **973,803,520 bytes
(0.907 GiB)** free on C:. No other writable local volume was attached.
Exact `6e579f4` original-profile staging and endurance testing have not
started there. This is an operator **manual** recovery plan; no file was
deleted, moved, compressed, installed, extracted, or launched during the
inventory. Earlier automated cleanup of CATalyst scratch data was rejected
before execution by automatic approval review (`blocked by policy`), so that
action must not be retried through another tool.

The common root for workspace entries below is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc`.
The paths and byte counts were measured read-only; no process referenced the
listed disposable directories. These are candidate **manual** recovery
targets, not instructions for automatic deletion.

| Path | Bytes | Classification |
| --- | ---: | --- |
| `C:\Users\M920q\AppData\Local\Temp\pytest-of-M920q` | 782,576,251 | Pytest temporary data |
| `<root>\tmp` | 179,340,021 | Test/reproduction scratch |
| `<root>\work\catalyst-review-f73a2bd\dist` | 78,228,091 | Generated package output |
| `<root>\work\catalyst-review-f73a2bd\build` | 34,778,072 | Generated build output |
| `<root>\work\catalyst-pr220-6e4d61d\dist` | 72,432,052 | Generated package output |
| `<root>\work\catalyst-pr220-6e4d61d\build` | 37,620,968 | Generated build output |
| `<root>\work\catalyst-pr220-a266464\dist` | 72,424,948 | Generated package output |
| `<root>\work\catalyst-pr220-a266464\build` | 37,615,739 | Generated build output |
| `<root>\work\catalyst-pr220-review\dist` | 78,240,515 | Generated package output |
| `<root>\work\catalyst-pr220-review\build` | 34,808,109 | Generated build output |

Those ten Tier A targets total **1,408,064,766 bytes (1.311 GiB)**. The four
worktrees are clean and only their ignored `build`/`dist` subdirectories
qualify; preserve every worktree root and shared Git store.

Five inactive September 30 startup-bug test-profile copies offer another
**1,312,623,552 bytes (1.222 GiB)**. Archive them to an external drive first
if their reproductions may still be needed:

| Path under `<root>\acceptance-data` | Bytes |
| --- | ---: |
| `startup-bug-fix-repro-20260930-215716` | 262,558,480 |
| `startup-bug-default-profile-20260930-215054` | 262,525,712 |
| `startup-bug-fix-safe-20260930-224700` | 262,513,576 |
| `startup-bug-fix-final-20260930-232300` | 262,513,099 |
| `startup-bug-fix-startup-20260930-215716` | 262,512,685 |

Manual recovery of all listed material would yield roughly **3.441 GiB**
free before new writes. Tier A plus two of the five copies would yield about
**2.706 GiB** free; the additional headroom from the full set is prudent
given recent pagefile/backup growth. Verify actual free space afterward
before staging exact `6e579f4`.

**Preserve:** the live Harvestr profile at
`C:\Users\M920q\AppData\Roaming\Catalyst`, Sage data at
`C:\Users\M920q\AppData\Roaming\com.rigidnetwork.sage`, the currently running
exact-`196caa8` package under `<root>\acceptance-artifacts\196caa8-secondary-isolated`,
all authoritative backups and evidence, `<root>\work\catalyst-pr214\.git`,
and the active `<root>\work\catalyst-venv312` test runtime. The secondary
must recheck process, wallet, campaign, safety, and disk state before any
exact-candidate switch.
