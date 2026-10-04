# Read-only safety diagnostics lease contention

Draft PR #220 exact runtime/source `b7eab4f263409c0b4c846d6a506b21e16335ee37`.

The earlier stopped-profile `244da2e` process failed closed after its
durable 30-second heartbeat lease expired during the same period as Windows
Backup/VSS activity and Sage RPC timeouts. The backup is correlated, not a
proven cause. Source review found a separate avoidable contention path:
`MutationGate.read_only_status()` held the local gate lock across a durable
SQLite safety snapshot. A slow safety GET could then block the heartbeat
thread, which needs the same lock to renew its lease.

A controlled regression first blocked the diagnostic durable read and showed
the heartbeat could not complete until that read returned. Exact `b7eab4f`
releases the local lock during the read. It retries once when a concurrent
heartbeat advances the local lease version before the snapshot returns. A
persistently stale diagnostic snapshot stays denied without installing a
local mutation fence. Acquisition, renewal and mutation-boundary durability
checks retain their existing locking. The red/green regression and negative
stale-snapshot regression passed; the complete mutation-gate file passed
257 tests. The full local Windows backend suite passed **7,197 tests,
213 skipped, 431 subtests**. Ruff check, format, diff validation and all
**11** PR CI checks passed on the exact source.

## Exact Windows package

Built cleanly from a detached checkout at exact `b7eab4f`; generated version
metadata was confined to that checkout. The bundled UI SHA-256 remains
`1FD778D4CC109562FF69942BD705D6CB107067017445C9B5E65E3514EC50A001`,
byte-identical to the previous 212-pass Chromium candidate.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-safety-readonly-b7eab4f-build\dist\Catalyst\Catalyst.exe` | `9EB27A8DFCB15B026318F75B797B6FAD628A9D46AB44DFC49C9CE2F9AACF3C8A` |
| `CATalyst-b7eab4f-primary-acceptance.zip` | `D7E5066C33477A60A944EF6E2EB7A8FA4E2E583BC0CA58E44DC83584D533050D` |
| Unsigned `Catalyst-Setup-b7eab4f-1.4.0.exe` | `4F68B683BB1FFE0D8495E5A546A29C08E71ED2310DD48C724C9670002C0E871B` |

Packaged API, synthetic Sage RPC, interrupted-publication recovery, and
native clean/duplicate/persisted/safety smokes passed in isolated profiles.
The ZIP passed CRC and embedded EXE byte comparison. A separately compiled
unique-AppId QA installer installed to an isolated E: directory; the installed
EXE matched the clean hash and its packaged API passed, then uninstall removed
the installed EXE and HKCU registration. Defender custom scans of the bundle,
ZIP and unsigned installer added zero detections. Independent HTTP downloads
of both pinned artifacts matched their local hashes.

Artifact commit `390729bcba2a7c5eef7ddafaf62589e7f231eab8`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/390729bcba2a7c5eef7ddafaf62589e7f231eab8/acceptance-artifacts/CATalyst-b7eab4f-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/390729bcba2a7c5eef7ddafaf62589e7f231eab8/acceptance-artifacts/Catalyst-Setup-b7eab4f-1.4.0.exe)

## Initial original-profile live check

The previous stopped `13a842b` process shut down through its visible UI with
offer cancellation unchecked. Its 60-second monitor logged 20 safety-allowed
samples, then its process-exit/end records. Exact `b7eab4f` started at
2026-10-04T21:02:32.893332Z as PID `20784`, sole Catalyst process and port
5000 owner, with the exact clean EXE hash. Testing Risk Disclosure was
acknowledged in the native window. The Windows UI helper then lost activation
of that window; the same app's browser UI completed Sage TEST 7 selection,
Splash skip and configured Spacescan startup. This is an initial live check,
not a full native UI pass.

At 21:06 UTC read-only API state showed mainnet Sage fingerprint `736588221`,
CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced healthy wallet, balances `138.470301476875` XCH and `780212.284` MZ,
stopped bot, inactive Bootstrap, zero open offers, safety allowed and a
renewing lease. No campaign, fee approval, offer or transaction was made.

A read-only 60-second monitor began at 21:06:19 UTC for the exact PID/hash.
Its script is `E:\catalyst-stability-monitor-b7eab4f\monitor.ps1`, SHA-256
`F7210B6E530544521A324021401E2950B43888C27CB96FAD8BFE68E84706BE13`,
and its trace is `trace-60s.jsonl`. The initial sample passed. The complete
24-hour trace, live wallet lifecycle, independent secondary acceptance and
final review remain open. PR #220 stays draft; public readiness is not claimed.
