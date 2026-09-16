# Coin Prep fee approval implementation checkpoint

The user explicitly approved the written design and cleared the previous goal.
A new active implementation-and-verification goal and the existing hourly heartbeat
now track the full workflow. No repeated design approval is required.

Branch: `codex/coin-prep-fee-approval`.

## Strict estimation foundation

- Initial normalization tests: 46 intended failures before implementation.
- Provider integration tests: four failures demonstrated missing observation metadata
  and the existing node/Coinset defect that treated missing estimates as valid zero fees.
- Read-only quote integration: four missing-interface failures before implementation.
- Explicit zero-second target: one regression failed because the old estimator sent 300.
- Implemented strict raw-response normalization, original observation/expiry metadata,
  stale/future rejection, upward integer rounding, and invalid-request transport gating.
- Fresh combined run: 92 passed (`test_fee_estimation`, `test_tx_fees`,
  `test_coin_prep_batch_plan`, `test_coin_prep_direct_batch`); Ruff checks passed.

## Outstanding acceptance gates

Durable approval ledger integration, canonical plan preview, HTTP/native bridge consent,
all-path dispatch enforcement, authoritative settlement/recovery, GUI confirmation/E2E,
full regression testing, fresh Windows build and live operator-approved fee acceptance
remain incomplete. These tests do not prove the entire feature ready.

The live package was not reloaded or changed, no wallet mutations were performed,
and no release or main merge was made during this checkpoint.
