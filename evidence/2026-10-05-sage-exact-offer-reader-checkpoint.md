# Exact Sage offer reader checkpoint

Sage's [`get_offers` implementation](https://github.com/xch-dev/sage/blob/main/crates/sage/src/endpoints/offers.rs) reads the complete local offer table and does not use pagination. Its `get_offer` implementation indexes one `offer_id` and returns one offer record. The request schema in [`sage-api`](https://github.com/xch-dev/sage/blob/main/crates/sage-api/src/requests/offers.rs) requires only `offer_id`.

CATalyst now has a bounded read-only wallet facade method for at most 256 distinct exact Sage offer IDs. It strips encoded offer text, normalizes the summary, verifies every returned identity, and discards the entire partial cohort on any missing, mismatched, malformed, or failed read. Four network-blocked tests passed after the missing-method red state; Ruff and diff checks passed.

This method is not yet selected by Task-9 reconciliation. The current full-history loader still fails closed above 4,096 rows. Before this can be used for terminal proof, reconciliation must derive and bind the complete durable cancellation cohort, collect all exact rows, and replace the 4,096-row transaction-history dependency with bounded selected-coin/height evidence. Full active-book and quarantine contracts require separate treatment. No package or live acceptance is claimed for this checkpoint, and PR #220 remains draft.
