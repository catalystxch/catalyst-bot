# Exact 61be438 primary TEST 7 read-only rollover

On 2026-10-06 UTC, the primary original TEST 7 profile was moved from the
stopped `cbd7d08` process to exact runtime/source
`61be438d67c015c6f49ee4d401c34266cb6e8091`. The old process was the
sole `Catalyst.exe` and port 5000 owner, with safety allowed, an owned lease,
zero open offers, a stopped bot, and no active Bootstrap campaign. The app's
clean `/api/shutdown` path was invoked with `cancel_offers:false`; it exited,
released port 5000, and did not request wallet-wide cancellation.

The clean detached EXE at
`E:\catalyst-quarantine-fallback-61be438\dist\Catalyst\Catalyst.exe` has
SHA-256 `78E32799968BC132B4CD3FA39733B45206F1BE08B8DF2354A5B80318B9C71576`.
After launch, PID `163972` was the sole `Catalyst.exe` and port 5000 owner;
the running path and hash matched the exact package. The testing Risk
Disclosure was acknowledged in the native UI under the operator's standing
authorization. Sage `TEST 7` fingerprint `736588221` and the Monkeyzoo
`MZ_XCH` pair were selected in the native UI. Splash was skipped for this
read-only window; the configured Spacescan key was retained without exposing
or changing it.

The live API then reported Sage mainnet, fingerprint `736588221`, CAT wallet
ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
a synced wallet, `138.470301476875` XCH and `780212.284` MZ spendable and
total, a stopped bot, zero DB open offers, inactive Bootstrap with no current
campaign, safety `ALLOWED`, an owned lease, and zero blocker counts. The
balances match the pre-rollover values. No campaign or fee approval was
created, and no wallet mutation was requested.

The connected native UI was traversed without Save, Start, Cancel, or Reset.
Dashboard showed TEST 7/MZ and Follow mode with the bot stopped. Offers showed
zero active buy/sell offers and three historical fills. P&L showed the three
historical confirmed buy fills and zero pending verification. Market Intel
reported RED attributable offer-book confidence, no tradable range, and
Splash unavailable as expected after skipping it. Settings showed fingerprint
`736588221`, the MZ pair, and safety `ALLOWED` with an owned lease. Current
session Logs backfilled Sage login and MZ selection. The native Doctor report
passed nine checks and showed one expected Splash-unreachable warning; wallet
RPC, sync, signing, CAT mapping, Dexie, database, configuration, and
Spacescan checks passed. The TibetSwap check was explicitly skipped as a
retired dependency. This is read-only UI and diagnostic evidence, not an
active-offer or trading lifecycle result.

A fresh exact-PID/hash monitor, PID `115476`, began at
`2026-10-06T03:50:36Z` using
`E:\catalyst-stability-monitor-61be438\monitor.ps1` and
`trace-60s.jsonl`. Its first four 60-second samples through
`2026-10-06T03:53:39Z` were clean: process alive, safety allowed, lease owned
and renewing, Sage synced, bot stopped, and zero open offers. This is an
early checkpoint only. The prior `cbd7d08` trace is historical; the new
24-hour stopped-profile gate cannot be assessed before
`2026-10-07T03:50:36Z` and a full trace and end-state audit.

Draft PR #220 remains unmerged. The secondary PC has independently passed
isolated exact-package acceptance and has been asked to perform its own
original-profile read-only rollover. Live active-offer lifecycle/recovery,
both exact-candidate 24-hour windows, and final review remain open. The
proposed new TEST 7 campaign and fee scope have no approval; there was no
mainnet wallet effect in this rollover.
