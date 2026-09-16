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

## Canonical preview and durable consent core (continuation)

- Observed missing-behavior failures before implementing canonical contracts,
  preview/consent storage and staged estimation. Current trusted-input core is not
  an HTTP authority boundary and cannot yet start a worker or authorize dispatch.
- Canonical digests cover exact economic outputs and wallet/network/asset/session
  identity, normalize Decimal representations and deterministic ordering, and
  exclude transient estimates and intermediate selected coins.
- Staged estimates distinguish exact unsigned from projected costs/count ranges,
  price conservative upper counts, retain provider observation/expiry, recheck age
  after transport and separate retained fee-coin principal from spending.
- Immutable previews and consent are replacement-resistant. Concurrent duplicate
  confirmation produces one approval/version; conflicting budgets fail. Missing,
  stale or unavailable guidance and insufficient fee funding cannot create consent.
- Expanded schema checks initially exposed UDF-dependent SQLite CHECK constraints:
  ordinary `integrity_check` failed even on empty metadata tables. Digest validation
  now uses insert guards; canonical schema and raw SQLite integrity checks pass.
  The legacy fixture now accurately removes future-only preview metadata before
  simulating the old PR #218 schema; no production history was removed.
- Independent review reproduced a consent-budget gap when prior cancellation holds
  exhausted total capacity. A literal regression failed before the fix. Confirmation
  now checks preparation plus cancellation against total remaining as well as the
  separately protected preparation allowance and available funding.
- A failing signed-zero regression demonstrated equivalent zero headroom yielding
  different digests. Zero Decimal values now normalize to `"0"`.
- Fresh post-fix combined run passed 368 tests in 82.97 seconds. Ruff and
  `git diff --check` passed. Independent re-review found no Critical/Important
  core findings.
- Thirteen consent-validation regressions failed before implementation. Read-only
  validation now requires durable preview consent and current canonical contracts,
  rejects changed/superseded approvals and generic ledger approvals, preserves holds
  through restart/quote expiry and explicitly returns `dispatch_authorized=False`.
  Focused validation/storage run: 31 passed in 10.76 seconds. Independent review
  found no Critical/Important validator-core findings. Final expanded run passed
  381 tests in 82.89 seconds, including validator, preview, ledger, authoritative
  recovery, canonical schema, replacement capacity, estimation and direct planner
  regressions. Ruff and `git diff --check` also passed.

Actual runtime wallet/configuration collection, shared execution-plan factoring,
unsigned construction, HTTP/native endpoints and all dispatch/GUI integration
remain incomplete. Mocked trusted stage costs are not proof of unsigned construction.
No wallet actions, package reload, main merge or release occurred in this continuation.

## Shared atomic targets and executable unsigned inspection (continuation)

- Missing-helper tests failed before implementation. Shared target conversion now
  enforces exact counts, integer bounds, CAT rounding and XCH-only fee funding;
  the worker uses these same targets, target contracts and unsigned actions.
- Actual CLVM inspection exposed an inherited summary/executable binding gap.
  Independent review appended an extra valid spend while retaining the matching
  summary; the first implementation incorrectly labelled its cost exact.
  A focused regression reproduced this failure before the fix. Further failing
  regressions covered false input amounts, false output IDs and XCH disguised
  as CAT. No real wallet transactions were involved.
- The new strict inspection path now joins every executable input and per-parent
  addition to the validated summary, proves actual fee and destination-derived
  coin IDs, and recognizes CAT2 module/TAIL identity and outer puzzle hashes.
  Unknown/uninspectable effects are unavailable, never an exact heuristic.
- Real XCH cost is 2,892,020; a pinned synthetic CAT2 ring costs 27,359,224.
  Complete ephemeral chains pass; hidden spends, redirected outputs and false
  fee/asset/identity evidence fail. Tests require no Chia Python runtime dependency,
  signing, submission, journals, claims or fee holds.
- Fresh expanded planner, Sage unsigned, Offer-wire, fee core, ledger/recovery,
  replacement capacity and canonical schema regressions: 456 passed in 99.33s.
  Subsequently expanded unsigned/decoder tests: 42 passed in 8.19s. Ruff and
  `git diff --check` passed. Independent re-review found no Critical/Important
  issue in this scoped inspection core.
- Runtime economic configuration collection, server HTTP/native preview/approval,
  final dispatch adoption, GUI confirmation, fresh package and live genuine-budget
  acceptance remain open. The legacy cost-only helper is not effect proof, and
  the running package has not been changed. No main merge or release occurred.

## Outstanding acceptance gates (unchanged)

Runtime canonical plan preview, HTTP/native bridge consent,
all-path dispatch enforcement, authoritative settlement/recovery integration, GUI confirmation/E2E,
full regression testing, fresh Windows build and live operator-approved fee acceptance
remain incomplete. These tests do not prove the entire feature ready.

The live package was not reloaded or changed, no wallet mutations were performed,
and no release or main merge was made during this checkpoint.
