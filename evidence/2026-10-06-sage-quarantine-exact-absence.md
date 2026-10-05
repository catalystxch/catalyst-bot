# Sage quarantine proof after offer history growth

Draft PR #220 source checkpoint. This is isolated source/test evidence; no new package or mainnet quarantine resolution was exercised.

Sage v0.13.0 `get_offers` returns its full local offer table without pagination. Its `get_offer` reads one exact ID from the database and raises `MissingOffer` for an absent row. The RPC maps that error to HTTP 404 with the rendered error text. See the tagged Sage [offer endpoint](https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage/src/endpoints/offers.rs), [error definition](https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage/src/error.rs), and [RPC status mapping](https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage-rpc/src/lib.rs).

The Sage transport now emits a distinct `SAGE_OFFER_NOT_FOUND` diagnostic only when the `get_offer` route returns HTTP 404 with the exact `Missing offer: <requested 64-hex ID>` body. Generic 404, another endpoint, another ID, extra body text, transport failure, and an existing offer cannot prove absence. The bounded wallet facade discards a partial set on any failed exact read.

Quarantine proof version 2 binds exact absent trade IDs to the durable quarantine requirements, reads Sage identity before and after, and checks the exact selected wallet coins for ownership and unlocked status. An empty quarantine probes the same endpoint with a fixed absent sentinel, so route availability is still established. Identity drift, missing or locked coins, incomplete reads, stale observations, and binding mismatch deny resolution. Non-Sage proof version 1 retains its full-history contract.

Windows verification:

- `tests/test_long_gap_recovery.py`: 63 passed.
- `tests/test_sage_exact_offer_evidence.py` plus Sage transport diagnostic tests: 49 passed and 342 subtests passed across the combined Sage guard run.
- Combined changed-area run: 113 passed and 342 subtests passed.
- Ruff check, format and `git diff --check`: passed.

The running original TEST 7 app is still the earlier `74da24c` package, stopped under a read-only monitor. This source has not yet been built, installed, or exercised against the live Sage 0.13.0 RPC. Real active-offer recovery, both exact-candidate 24-hour windows, live secondary lifecycle and final review remain open. PR #220 stays draft.
