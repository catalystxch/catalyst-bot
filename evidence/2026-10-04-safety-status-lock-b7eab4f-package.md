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

## Exact-package read-only UI and independent secondary check

The exact `b7eab4f` process remained PID `20784`, the sole `127.0.0.1:5000`
listener, with EXE SHA-256
`9EB27A8DFCB15B026318F75B797B6FAD628A9D46AB44DFC49C9CE2F9AACF3C8A`.
Its browser UI on the original TEST 7 profile rendered Dashboard, Offers,
P&L, Market Intelligence, Settings Setup/Live, Logs, Data Reset, Help and
About. The Dashboard showed a stopped bot and inactive Bootstrap. Offers
showed zero active and three historical fills; P&L showed three confirmed
historical buys, zero sells and zero realized P&L. After refresh, Market
Intelligence showed three Dexie bids and 29 asks, matching the read-only API
order book. No setting, reset, campaign, fee, offer or wallet mutation was
made. Logs backfilled Sage login, MZ selection and order-book refresh. The
on-demand Doctor passed nine checks with one expected warning for the stopped
optional Splash daemon; Sage RPC, signing, sync, CAT identity, Dexie, database
and Spacescan configuration passed. Native UI control remains separately open
because the Windows UI helper lost activation of the window.

The independent secondary PC checked the exact source and pinned ZIP,
installer, EXE and UI hashes. Eight focused mutation-lock/heartbeat tests and
26 safety API/diagnostic tests passed. In a new isolated profile its package
started with one port owner; 20 concurrent safety-status calls all denied as
expected with no failures (maximum 302 ms), a duplicate launch exited, and
graceful shutdown left no process or listener. The isolated database had zero
offers, campaigns, Coin Prep operations, approvals, journals and effect claims.
Its original Harvestr profile was untouched and no wallet action occurred.
The secondary report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\2026-10-04-pr220-secondary-b7eab4f.md`.
This passes the delegated isolated secondary scope; a secondary original-profile
live lifecycle has not been run.

The primary read-only 60-second monitor was still alive at sample 9 on
2026-10-04T21:14:27Z: safety allowed, bot stopped, zero open offers, Sage
synced, lease owned and renewing while Windows Backup remained running. This
is an observation in progress, not a completed 24-hour stability window.

## Original-profile concurrent read-only safety check

While the exact original-profile process and Windows Backup were running,
20 concurrent `GET /api/safety/status` calls all returned HTTP 200, safety
allowed and the lease owned by this run. None failed; response times ranged
from 992 to 1451 ms (mean 1185.5 ms). A subsequent safety read retained an
active, owned lease at version `166811` and zero blockers. The monitor's next
60-second sample at 2026-10-04T21:22:34Z recorded version `166814`, safety
allowed, Sage synced, bot stopped and zero open offers. The raw summary is
`E:\catalyst-stability-monitor-b7eab4f\live-readonly-stress-2026-10-04.json`
(SHA-256 `647A106E3931DB7530528BEC62C3A304ED2F10675575E166F130231382D663AC`).
The live profile was not mutated by this read-only stress check.

## Original-profile native read-only UI traversal

The Windows native UI helper subsequently attached to the same exact-hash
`b7eab4f` process without restarting it. In the visible native window, Sage
fingerprint `736588221` was selected, optional Splash was skipped, the
configured Spacescan key was continued, and Monkeyzoo Token (`MZ_XCH`) was
selected with the native CAT selector. The Dashboard then showed Sage synced,
the bot stopped, no active Bootstrap campaign, RED expired offer-book
confidence, and the expected `138.4703` XCH and `780212.284` MZ balances.
The Dashboard's Start path remained disabled pending setup review.

Native Offers showed zero active buy/sell offers and three historical fills.
PnL showed three confirmed historical buys, zero sells, three unmatched buy
legs, and zero realized PnL. Market Intelligence showed Dexie ready, Splash
unavailable, Sage ready, and RED confidence. Settings Setup displayed the
selected fingerprint and exact MZ pair; its live safety panel was ALLOWED,
with zero unresolved operations, reservations and publications and a renewing
owned lease. Settings Live correctly said the bot must start before controls
are enabled. Logs backfilled current Sage login, MZ selection and order-book
events. Data Reset described its three separate confirmation-protected reset
choices. Help and About opened and closed in the native shell. The app was
left on Dashboard. No settings were saved, no reset or bot start was invoked,
and no campaign, fee, offer, or wallet effect occurred.

At the accompanying read-only process check the sole `Catalyst.exe` and port
5000 owner was still PID `20784` from the clean exact-hash build. The monitor
remained alive at sample 28 (`2026-10-04T21:33:45Z`): safety allowed, owned
renewing lease, synced Sage, stopped bot and zero open offers while Windows
Backup was running. The full 24-hour trace and live financial lifecycle remain
open; this traversal closes only the native read-only view check.
