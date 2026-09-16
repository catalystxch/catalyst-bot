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

## Durable ledger groundwork (continuation)

- Reused PR #218 functions and 13 tests from commit
  `9508ae849cdb5f6e5b80907979965ad7b7172d4c`, after observing 13 missing-behavior
  failures on this branch. The PR itself has not been merged.
- Added fee approvals, holds and immutable terminal evidence to canonical stability
  schema validation, including an indexed scope query and exact integer constraints.
- Six failing regressions demonstrated mutable economics, fractional durable amounts,
  unchecked index shape and an approval ceiling below earlier commitments.
- Exact PR #218 migration failed before implementation; the supported upgrade now
  preserves fee holds. Invalid amounts/unknown shapes fail closed without refunds.
- Recovery tests exposed a real integration incompatibility: actual operation IDs
  are `coin-prep:<digest>`, not bare SHA-256. Both supported canonical forms are now
  validated. Replay returns explicit idempotent accounting state, not fresh dispatch consent.
- Four authoritative-settlement tests failed before implementing journal-bound
  settlement. Unknown effects remain held, confirmed fees remain spent across versions,
  exact no-effect evidence releases once, and wrong evidence cannot settle a hold.
- A further failing regression prevented decreasing cancellation protection under
  a later approval. Caller-provided no-effect flags are also verified not to refund fees.
- A combined run initially found ten failures from cross-importing another test file.
  Root cause was this repository's per-collector module isolation, not a production
  change. Recovery fixtures are now self-contained. The rerun passed 256 combined
  ledger/recovery/capacity/schema/estimation regressions. A subsequent focused recovery
  run passed five tests, including the new caller-flag case. Ruff passed.
- A fresh expanded regression run then passed 290 tests. Reset/restart preservation
  and near-SQLite-limit exact accounting checks passed without production changes.
- Independent review reproduced SQLite `INSERT OR REPLACE` bypassing delete
  triggers with recursive triggers disabled. Two approval/reservation regressions
  and two journal outcome regressions failed before replacement-resistant insert
  guards were added. The reviewer independently verified all three tables and the
  approval scope/version uniqueness conflict are now fenced.
- A failing literal readback regression found preparation capacity displayed as
  80 mojos when cancellation commitments left only 50 mojos total. Readback now
  uses the smaller of total remaining and protected non-cancellation remaining,
  matching actual reservation enforcement.
- Two further failing regressions demonstrated direct unbound outcome inserts
  could refund holds. A journal/evidence/hash/claim/exact-fee/state insert guard now
  also enforces settlement binding at the schema boundary. Public settlement
  validation was already fail-closed. Focused ledger/recovery run: 36 passed.
- The expanded combined run after replacement/readback fixes passed 295 tests.
  Final post-journal-guard regression run passed 296 in 60.09 seconds. A fresh
  focused ledger/recovery run passed 36 in 13.63 seconds, additionally preserving
  settled outcome evidence through history/counter reset and restart. Ruff and
  `git diff --check` passed. Independent re-review found no Critical/Important
  foundation issues, including the journal binding guard and migration compatibility.

Canonical server-owned scope/plan preview integration and full dispatch/recovery
hook coverage remain outstanding. This is still groundwork, not live enforcement.

## Outstanding acceptance gates

Durable approval ledger integration, canonical plan preview, HTTP/native bridge consent,
all-path dispatch enforcement, authoritative settlement/recovery, GUI confirmation/E2E,
full regression testing, fresh Windows build and live operator-approved fee acceptance
remain incomplete. These tests do not prove the entire feature ready.

The live package was not reloaded or changed, no wallet mutations were performed,
and no release or main merge was made during this checkpoint.
