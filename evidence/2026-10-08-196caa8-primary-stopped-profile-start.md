# Exact 196caa8 original TEST 7 stopped-profile start

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) remains open against `main`. Exact runtime/source is `196caa890ebf97ed08435ac492edd6edd553f9e9`; its detached Windows package and checks are recorded in [the package evidence](2026-10-08-coin-prep-private-status-196caa8.md). This is a read-only live start, not active-offer lifecycle or a 24-hour pass.

## Preflight and normal rollover

At approximately 2026-10-08T06:57Z, the older `eadb82a` process was PID `120856`, owned `127.0.0.1:5000`, and remained stopped in `HEARTBEAT_FAILED`. App reads showed no active Bootstrap campaign and zero DB open offers. Direct read-only Sage mTLS calls reported mainnet TEST 7 fingerprint `736588221`, CAT wallet ID `2`, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, XCH selectable `138470301476875` mojos, MZ selectable `780212284` atomic units, zero pending transactions, and complete 28,359/28,359 coin and 6/6 file sync. Sage returned 4,095 terminal offers: 3,326 cancelled, 538 completed, and 231 expired, with no active status.

The old window was closed normally with `CloseMainWindow()` after confirming stopped bot, zero offers, and inactive Bootstrap. It exited; port 5000 became free. No forced kill or offer cancellation was used. `CMM_DATA_DIR` was unset. The exact detached EXE at `E:\catalyst-auth-read-196caa8-build\dist\Catalyst\Catalyst.exe` was rehashed to `B350C448350961613A3C57020AC66D992F7FDD319036629CAABA009DD376A8E9` and launched visibly against the original profile.

At approximately 2026-10-08T07:00Z, PID `91988` was the sole `Catalyst.exe` and sole port-5000 owner at that exact path and hash. Read-only app APIs showed safety `ALLOWED` with an owned renewing lease, bot stopped, Bootstrap inactive with no attention required, and zero buy/sell DB open offers. A repeat direct Sage snapshot at 07:00:37Z matched the preflight balances, sync, zero pending transactions, and terminal-offer counts. No campaign, Coin Prep, or wallet action was started.

## Exact stopped-profile monitor

The read-only 60-second monitor at `E:\catalyst-stability-monitor-196caa8-clean\monitor.ps1` began its trace at **2026-10-08T07:02:14.4198631Z** in `trace-60s.jsonl`. Its start record binds PID `91988`, executable path, and exact SHA-256. It samples process presence, loopback safety, owned lease, health, bot state, DB open-offer count, and Windows Backup task state. The first sample was safety allowed, lease owned, bot stopped, zero offers, and no read error. An audit of 12 samples through 07:13:24Z found zero failing samples, and monitor PID `32852` remained alive. These early samples do not satisfy the full 24-hour gate.

The earliest duration checkpoint is **2026-10-09T07:02:14Z**. Acceptance requires the complete trace, uninterrupted exact process and port ownership, healthy end-state, direct Sage/DB reconciliation, and review of any backup overlap or errors. The previous candidate's failed Veeam-overlap window is historical evidence, not credit for this candidate.

Independent secondary-PC exact-candidate acceptance and both final 24-hour windows remain open. The secondary PC's older `a9fa741` trace has a separate checkpoint after 2026-10-08T08:17:37Z and cannot count as exact `196caa8` acceptance. Active-offer lifecycle/recovery requires separately approved campaign and fee scope; no such new approval was received. Keep PR #220 draft; do not merge, tag, release, or claim public readiness.
