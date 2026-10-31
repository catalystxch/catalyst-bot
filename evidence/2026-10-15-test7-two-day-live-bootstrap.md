# TEST 7 two-day live Bootstrap, 2026-10-15

This is an in-progress original-profile mainnet acceptance run. It does not establish a live fill, reciprocal Splash receipt, a 24-hour active run, or general public readiness.

## Exact build and preflight

- Source: `215854c504ce5f9b83299ff718c2fbbb9e0fca4b` in draft PR #268. The current PR head `e4cbdb225eb69f17bf72f0fa22e1c9c175ff9e1e` adds evidence only.
- Native EXE: `C:\Users\t_you\.codex\worktrees\live-acceptance-integration\catalyst\dist\Catalyst\Catalyst.exe`, SHA-256 `94FE45BD2F0EAFE1487D1275C6F97F8A696631DF5ADA80D85414C1B8BBECEC29`. At 16:29Z PID 218844 was the sole port-5000 listener and matched this hash.
- Sage: TEST 7, mainnet, fingerprint 736588221, CAT wallet 2, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`. Before Start Bot, its complete offer history had zero fillable offers and zero pending transactions. Runtime safety latch generation 668 was resolved; the mutation lease was owned and renewing.
- The earlier one-day campaign was stopped through the native UI after exact expiry verification. The new native preview used a two-day term, 10 XCH and 100,000 MZ market budgets, 0.05 XCH fee cap, 10% first deployment, 3 buys and 3 sells, anchor 0.000075 and corridor 0.0000375–0.00015 XCH/MZ. The operator separately confirmed Start Campaign and Start Bot. Coin Prep reused existing coins and sent no preparation transaction.

## First live observations

The new campaign is `bbce5ecd31f92f7deceb02f733ebf4233994423964e78cc59fbfe442dc80dc70`, created 2026-10-15T16:24:54.257912Z and expiring 2026-10-17T16:24:54.257912Z. It was active at revision 0, with zero authoritative fee spend, at the 16:29Z audit.

The native Dashboard completed cycles 0–4 with 3 buys and 3 sells active and reported no unknown offers. The native Offers tab showed six active entries and zero pending cancels. Sage's complete 4,129-offer history returned the same six exact active trade IDs, with zero pending transactions. The six newest durable registry intents were all `visible`, three per side, and the native UI reported exact Dexie rediscovery for each. Publication acknowledgement is provisional until independent discovery; the native UI still displayed Splash queued and Splash discovery pending.

The native Market Intelligence tab reported Splash connected and its node running, but zero peers, zero received/relevant offers, and zero local submissions. The current publication design defers Splash delivery until fresh positive peer evidence; this run has not proved broadcast receipt. Spacescan token context was not loaded and confidence was RED. The bounded Bootstrap campaign remained authorized; Follow exposure was withdrawn.

An exact-PID/hash read-only monitor started at 2026-10-15T16:28:58.9305969Z: `E:\catalyst-stability-monitor-215854c-active-20261015\trace-60s.jsonl`. Its first sample recorded PID 218844 alive, bot running, Sage synced, safety allowed and lease owned. The full active-campaign 24-hour gate cannot be evaluated before 2026-10-16T16:28:58Z and then requires a full trace and independent end-state offer/fee audit. This monitor samples loopback health and safety; Sage offer-book evidence must be audited separately.

## Interrupted run, 17:26–17:27Z

The full monitor trace has 57 clean running samples through 17:26:04Z. Sample 58 at 17:27:05Z found PID 218844 gone and ended the trace. It cannot pass the 24-hour gate.

The CATalyst log shows Sage RPC becoming unavailable at about 17:26:31Z. The market-refresh failure path attempted protective cancellation, but `cancel_offers` refused with `FEE_BUDGET_APPROVAL_REQUIRED`; the bot loop then exited cleanly. The GUI shutdown path backed up the database and closed the server by 17:26:59Z. Windows System Event 1074 records a restart initiated on behalf of the logged-in user at about 17:27:20Z, followed by further planned servicing restarts. There is no evidence here of a CATalyst crash.

At 18:04Z, neither CATalyst nor Sage was running and port 5000 was closed. Read-only database integrity was `ok`; the campaign remained active at revision 0 with fee spend 0, safety latch generation 668 resolved, and all six recent intents still `visible`. The exact campaign had no `coin_prep_fee_consent` approval because Coin Prep reused prepared coins and sent no transaction. The protective cancellation code requires that approval for Bootstrap offers. This is a release-blocking consent/workflow mismatch to resolve without bypassing the fee gate.

Direct read-only requests to Dexie's public `GET /v1/offers/{id}` returned `success: true`, `status: 0` (active) for all six exact offer IDs at 18:04Z. That establishes public marketplace exposure while the bot was closed; current Sage wallet status requires a fresh synced Sage read. The operator has been asked to approve reopening Sage and the exact verified CATalyst build for a proof-only audit. No restart, cancellation, or new wallet transaction was initiated by this investigation.

## Open gates

- A real third-party fill with exact Sage, CATalyst, Dexie, and chain reconciliation, followed by recovery, requote, or terminal handling.
- Exact native cancellation and restart on this candidate after a fill, without bypassing any safety latch.
- Harvestr original-profile recovery and independent second-PC live acceptance; its filled-offer receipt proof is a separate case.
- Reciprocal two-PC Splash receipt and correct MZ classification with positive peer evidence.
- Full active final-candidate 24-hour trace, end-state audit, complete native GUI review, final CI/review, website/update/release verification.
- Guarantee an explicit, campaign-bound cancellation fee approval before live Bootstrap offers can require protective withdrawal, including when Coin Prep needs zero transactions. Reproduce the observed failure in tests before implementing that change.
