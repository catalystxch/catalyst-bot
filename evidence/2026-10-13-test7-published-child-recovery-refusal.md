# TEST 7 published-child recovery refusal (2026-10-13)

## Exact candidate and live boundary

- Source: `8a0b63b138d95d6fd5a5da221394bd87f1593a7d` on draft PR #268; all 11 exact-head checks passed.
- Windows onedir EXE SHA-256: `D204683197A18834C36FBA2ACD4F9EA0D1B2D0EEF519DAAB3739FCE9DC144A87`.
- The native app started as sole PID 143184 on port 5000 after the older diagnostic window closed. Its restricted *Fenced offer recovery* view showed mainnet TEST 7 fingerprint 736588221, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, zero pending transactions, an owned renewing lease, and the two active Sage trade IDs below. The bot stayed stopped and safety stayed tripped.
- Parent intent `4afb4a8ed67485fd71b42d950fcf6a06099c35bbbdcb054e393238c186844135` has a submitted, unconfirmed cancellation for trade `4d9e0b37ba019ba18e5bfb409adf588c2c54fd6477a9ec307b89cfb92836c8c7`. Sage reported the parent cancelled; CATalyst still retained its blocker.
- Sage active trades: `9d4f362014532262ca7da19636a05a407a331c970c927ff89e29004bcec5331e` and replacement child `ab93cacc6da604ac5b0213befea1d7758f779300d1a8869981f03aa837f3901b`.

## Reproduction and cause

The native recovery page selected the latest stopped same-wallet campaign `99b5a1c87d894b5ca151b4822e51f5323efa6e0b058fc95195d6f584522cb701`. Two proof-only *Verify parent cancellation* attempts, including one after *Refresh proof*, returned `abort_authority_changed`. There was no cancellation dispatch or new fee spend. A read-only check found zero `offer_refresh_aborts` rows after both attempts.

The endpoint deliberately hides the exact refusal. Running `database.begin_refresh_abort()` on a disposable SQLite backup with the observed immutable IDs, latch generation 667, lease owner/version, and complete two-trade Sage book reproduced the inner exception: `ValueError: replacement publication has ambiguous dispatch` at `database.py:31283`. This is a correct fail-closed check. The child intent `52de45fbed1743b99d75195140c0b5d6c34b4f4f65b2d4e4c15bd87cbbbe31ce` was still `created` with `first_visible_at=NULL`, but its Splash publication outbox row was already `succeeded` with a `SPLASH_HTTP_ACCEPTED` HTTP 200 acknowledgement at 2026-10-13T08:54:50Z. Its Dexie row remained queued. HTTP acceptance does **not** prove a separate peer received the offer, but dispatch means the child cannot safely be treated as unpublished.

The current abort path requires an unpublished child at entry, successor lease adoption, and final completion. A simple retry or relaxation of the one entry predicate would leave those other checks inconsistent. The source ordering is create-child-first; publication can advance while independent peer discovery and the `first_visible_at` registry boundary have not completed.

## Disposition

Keep TEST 7 fenced. Do not start a bot, force-mark child visibility, suppress the succeeded Splash row, replay the parent cancellation, or invoke ordinary Cancel All. A recovery path for a possibly published child needs exact external/registry proof and/or explicit cancellation of the complete active book, with separate Task 9 and fee evidence. A second-PC read-only check of its independent Splash node found seven peers and other received offers, but no retained incoming row or matching fingerprint for exact offer `3400270bcb816b978fd3f194f9e5eceefb3437957803228a580f6b6cef2dc06a`. This is inconclusive: absence from that node's retained data cannot prove no peer received it. The first PC's local Splash HTTP 200 remains dispatch evidence, not independent receipt evidence. No general-readiness claim follows from the green candidate checks.
