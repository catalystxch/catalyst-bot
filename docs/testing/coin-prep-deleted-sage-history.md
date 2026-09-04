# Coin Prep recovery after deleted Sage history

Deleting expired offers from Sage can leave CATalyst's durable offer intents
and local open-offer projection behind. Offer absence alone must not release
their reservations or erase their history.

For an exact registered offer missing from a complete Sage history response,
reconciliation now gathers additional read-only evidence:

- The stored signed offer must match the immutable intent's SHA-256. Sage
  `view_offer` inspects it again without importing, signing, or submitting it.
  Its asset IDs, atomic amounts, and signed expiration must match the intent.
- Fresh wallet identity, transaction history, and targeted owned-coin reads
  retain their existing completeness and freshness requirements.
- Coinset must return every selected coin. Reconstructing each coin's name
  binds the chain response to its parent, puzzle hash, and amount. Its amount
  and spent height must agree with Sage.
- Unspent inputs require a synced chain transaction-block timestamp beyond
  signed expiry. This avoids treating Sage's wall-clock expiry as chain proof.
- Spent inputs require their exact spending blocks and the preceding
  transaction blocks. The previous transaction block's timestamp must be
  beyond expiry: that is the clock Chia uses to validate offer time bounds.
- Where a Dexie listing is available, its exact trade ID and expired status
  must agree. A missing listing or unavailable provider supplies no proof.

The new chain-backed fallback is limited to mainnet and timestamp-expiring
Sage offers. Unsupported, missing, stale, malformed, mixed spent/unspent, or
contradictory evidence remains nonterminal. The normal Coin Prep guard stays
in place; retrying can recover after a temporary provider failure.

Successful recovery uses the existing proof-bound database transaction.
Offer intents, journal entries, offers, and coin records remain present.
Unspent inputs receive a released outcome; inputs spent after expiry receive
the existing permanent spent outcome and can never become reusable through
this recovery path. CATalyst's database records these externally established
facts rather than deciding current offer or coin state from its own cache.

Regression coverage lives in `tests/test_offer_reconciliation.py`, under
`deleted_history` and `deleted_sage_history`. It includes real isolated-database
terminal commits, spent/released dispositions, original-offer corruption,
provider contradictions, stale observations, chain identity mismatches, and
the transaction-block expiry boundary. Tests make no live wallet mutations.

The built-app restart check also exposed a separate completion-display defect:
saved asymmetric plans were checked using the shared maximum tier counts for
both assets. Restart verification now checks each saved side's own count map
against fresh spendable wallet coins, falling back to shared counts only for
older plans without side maps. Disjoint matching still rejects missing coins,
wrong sizes, unavailable wallet evidence, and overlapping fee/sniper shortages.
Coverage is in `tests/test_coin_prep_restart_verification.py`.
