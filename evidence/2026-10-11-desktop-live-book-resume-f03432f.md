# Desktop live-book resume, TEST 7

## Finding and fix

The native UI sent `{ "resume_existing_offers": true }` when the operator chose **Start Bot Now** for a restored six-offer session. `AppBridge.start_bot` discarded its body and invoked `/api/bot/start` with `{}`. The backend consequently returned `needs_coin_prep`, although the existing campaign coins were locked by those six live offers. No Coin Prep transaction was approved or dispatched during the failed attempt.

Runtime commit `f03432f5500588588f59de69ef2912a5441f863f` forwards only an exact boolean `resume_existing_offers: true` through the native bridge. All other body fields are discarded. The backend's existing fail-closed proof still requires a nonempty, identical trade-ID set in the current campaign's durable intents, the local open book, and a fresh complete Sage offer snapshot before bypassing free-coin readiness.

The new bridge regression failed twice before the fix and passed afterward: absent, false, string, and extra-field inputs cannot request resume. The bot-start endpoint tests passed `59` tests and `4` subtests; the mutation-gate suite passed `285` tests. Ruff and formatting passed. The clean detached Windows EXE built from this exact commit has SHA-256 `378E7F36ED914F2344F04DEE9F502044660AAB9AEBD76ABEB95A57D74A5A55A3`. Isolated packaged API, synthetic Sage RPC, and native first-launch smokes passed.

## Original-profile acceptance

The previous TEST 7 app was stopped with six live offers. It was shut down through its native UI with **Cancel all currently active wallet offers before shutdown** unchecked. The replacement was the sole `Catalyst.exe` and port-5000 owner. Its native UI connected to Sage mainnet fingerprint `736588221` and selected CAT wallet `2`, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.

Immediately before resume, Sage reported zero pending transactions and a complete offer snapshot with three active MZ buys and three active MZ sells. The local database had six open offers for that asset. Campaign `99b5a1c87d894b5ca151b4822e51f5323efa6e0b058fc95195d6f584522cb701` was active at revision `0`, with zero authoritative fee spend. The safety endpoint reported `allowed: true`, an owned renewing lease, and zero blocker counts. The native UI showed the same six-offer restored session and the configured `0.05 XCH` campaign fee cap.

After **Start Bot Now** in the native restored-session dialog, the exact app logged `bootstrap_existing_offer_resume_ready` for this campaign, revision `0`, offer count `6`, followed by `bot_starting` and `bot_started`. No additional Coin Prep transaction was requested. The native Dashboard changed to **Running**. Startup recovery reported no unknown offers and cycle `#0` completed with `3b/3s active`. A fresh complete Sage snapshot still showed three active MZ buys and three active MZ sells, zero pending transactions, and an allowed safety state with an owned lease and zero blockers. This proves the bridge and first recovered-book trading cycle, not long-window stability.

All 11 pull-request checks passed on runtime commit `f03432f`.

The native GUI was traversed while the bot ran. Offers rendered `Active 6`, three buys and three sells, matching Sage; each visible row showed Dexie publication and explicitly marked Splash peer broadcast unverified. P&L showed three historical confirmed buy fills, zero realized round trips, and the open-leg inventory mark. Market Intelligence showed Dexie ready, Sage ready, RED confidence, and Splash degraded with zero peers. Settings displayed running live controls; Data Reset actions were disabled while running; Logs showed successive completed cycles; Help and About opened and described Dexie as the primary offer book and Splash as optional. No settings or reset action was applied during this traversal.

Cycles `#0` through `#5` completed with `3b/3s active` and the live safety endpoint continued to report an owned renewing lease and zero blockers. A read-only 60-second monitor for this exact PID and EXE hash began at `2026-10-11T16:46:17.6916432Z`: `E:\catalyst-stability-monitor-f03432f-active\trace-60s-v2.jsonl`. Its first sample showed the process alive, bot running, Sage synced, safety allowed, and lease owned. The full 24-hour active-book gate cannot be counted before `2026-10-12T16:46:17.6916432Z` plus a complete trace and end-state audit. The prior short trace sampled a token-protected offer-count endpoint and recorded an expected HTTP error; it is not the acceptance trace. Offer counts are audited separately from Sage and the native UI.

The durable campaign expiry is `2026-10-12T15:31:46.533868Z`, about 74 minutes before that monitor reaches 24 hours. Consequently this run cannot satisfy a continuous 24-hour **active-campaign** gate, even if every sample remains healthy until the campaign stops. Preserve it as a bounded live-book/restart observation; a fresh campaign and separately timed trace are required for the full gate. At the read-only check on 2026-10-11, the campaign was still active, the authoritative fee spend remained zero, and no renewal or cancellation was performed.

Harvestr on the other PC remains separately safety-fenced after its confirmed Coin Prep transactions and a heartbeat SQLite lock failure. This TEST 7 bridge fix does not address that failure.

## Overnight read-only observation

At `2026-10-12T02:58:14Z`, the exact-PID/hash monitor had recorded `604` clean samples with the bot running, Sage synced, safety allowed, and the lease owned. The native Offers view showed six open MZ offers: three buys and three sells. All six rows showed exact Dexie discovery; Splash rows said local submission was acknowledged but peer broadcast was unverified. The current app log reported cycle `#802` complete with `3b/3s active` and an empty Splash queue.

The existing local Splash process was PID `197208`, listening for offers on `127.0.0.1:4000` and exposing metrics on `127.0.0.1:4001`. A read-only metrics request at approximately `03:00Z` returned `peers: 0`, `offers_broadcasted: 0`, `offers_received: 0`, and `total_connections: 0`. This confirms local Splash operation but provides no independent peer-delivery evidence. The earlier rejected two-node launch was not retried. No offer, wallet, campaign, or node setting was changed during this check.
