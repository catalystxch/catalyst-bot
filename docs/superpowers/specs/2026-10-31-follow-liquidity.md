# Follow liquidity recovery and one-time fee consent

## Intent

CATalyst should let a user bring liquidity to a thin Chia market with 24 BUY and 24 SELL Follow offers after a clear native review. A RED confidence state caused by thin depth may be overridden for that exact run and duration. Current price evidence, hard price bounds, wallet identity, the cumulative fee cap, and exact offer accounting remain enforced.

## Observed state

- TEST7 wallet 736588221 on mainnet has two Sage-active SELL offers and no pending transaction. CATalyst stopped after a third creation became `creation_unknown`; latch 694 blocks Cancel All. The third selected CAT coin is unspent and has no offer binding, and the complete Sage book has no offer with its unique requested amount.
- The live EXE predates the code fix that classifies a Sage pre-send safety rejection as no effect. A new build is necessary before another live run.
- The Follow review form defaults to 0.005 XCH although TEST7's current approved cumulative ceiling is 0.05 XCH. That mismatch causes an avoidable return to fee review.
- RED passive quote support exists in PR272, but its live attempt produced two SELL offers before the creation latch; a 24/24 ladder has not been proven.
- The second original-profile PC is not currently reachable through the remote task host. Its state must be freshly verified before launch.

## Required behavior

1. Read the current approved cumulative fee ceiling into the Follow review. Suggest a fresh bounded ceiling only when no adequate approval exists. One explicit native acceptance records that fee scope; unchanged terms reuse it without another fee screen. Actual fee spends and holds remain wallet-wide and never exceed 0.05 XCH per original-profile PC.
2. For this exact TEST7 `creation_unknown`, offer a native, read-only no-effect review only after two complete Sage-book observations, exact wallet identity and sync, no pending transactions, stopped and quiescent bot, and the selected coin still unspent and unbound. The reviewed final action may record a no-effect journal event, release only that intent's coin reservation, and resolve only the matching latch generation. Any changed proof refuses. It sends no wallet transaction.
3. Once the latch is resolved, use the normal fee-ledger-backed native cancellation review for exactly the two remaining SELL offers. Show the suggested current fee and cumulative headroom. Submit only after action-time user confirmation, then prove both offers terminal from Sage and the database.
4. RED consent may waive thin independent-depth and single-provider policy for passive quotes in the reviewed 0.0000375–0.00015 XCH/MZ hard band and up to 72 hours. It must revalidate current attributable price evidence at the wallet effect boundary; unknown, stale, contradictory, or out-of-band prices wait without sending. The user sees why an offer is waiting. A RED approval for one run cannot authorize another.
5. After a normal production build passes tests, verify its exact SHA-256 and run that identical build on both original-profile PCs. Human wallet selection and action-time financial confirmation precede trading. Verify 24 BUY and 24 SELL live on each PC, then observe both for 48 hours. Keep bot PR272 and site PR93 OPEN/DRAFT/unpublished.

## Approaches considered

- Direct Sage RPC cancellation would bypass CATalyst's mutation lease and fee ledger. It is unsuitable for normal recovery.
- Waiting for natural expiry avoids a wallet transaction but leaves active offers and the creation latch unresolved for hours. It remains a fallback if exact cancellation cannot be priced safely.
- The chosen approach uses a proof-bound, DB-only recovery for the third creation, then CATalyst's existing reviewed cancellation and fee machinery for the two real offers.

## Acceptance evidence

Focused tests for changed code; full Python suite; browser review tests; normal PyInstaller build and hash; exact PR head and CI; Sage identity, sync, pending and full book; CATalyst DB and runtime safety; native GUI; independent verification of both PCs; and a timestamped 48-hour observation after both real ladders exist.
