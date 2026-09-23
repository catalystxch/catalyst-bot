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

## Fresh Sage wallet snapshot boundary (continuation)

- Confirmed the existing persistent goal and hourly heartbeat remain ACTIVE;
  no duplicate goal or automation was created. Full approved scope is unchanged.
- The new read-only collector verifies current identity before and after reads,
  actual CAT metadata/precision, unchanged economic configuration, selectable
  inventory and its declared total, stable coin-ID pagination, existing checked
  receive address and DB reserve/reconciliation protection. It never signs,
  submits, launches prep, resets counters or creates fee/effect reservations.
- Official pinned Sage v0.13.0 `CoinRecord`, `Amount`, `TokenRecord`, request and
  endpoint implementations exposed a fixture/collector mismatch: selectable
  records carry P2 addresses and integer-or-string atomic amounts, not raw parent
  and outer puzzle fields. Complete schema-correct fixtures reproduced rejection
  of valid inventory before the correction. Raw coin/effect identity must still
  be proven by the separate executable unsigned inspector before dispatch.
- After the schema correction, 11 regressions failed because missing, malformed,
  truncated or changed totals and unstable ordering were incorrectly accepted.
  The collector now requires a bounded exact total, full page counts, consistent
  totals and strictly ascending unique normalized IDs. Empty inventory is valid
  only with a zero total. A further failing regression covered Sage's optional
  native-asset metadata (`asset_id=null`); it no longer hides the actual CAT.
- Expanded snapshot, unsigned, preview, consent, estimation, ledger/recovery,
  storage/contract and planner run: 257 passed in 55.23s before the final optional
  native-metadata correction. Fresh final snapshot run: 48 passed in 15.75s.
  Ruff and `git diff --check` passed after that correction. These are scoped
  regression receipts, not full-feature/build/live acceptance or independent
  review of the whole implementation.
- Runtime economics/stage collection, HTTP/native preview and consent endpoints,
  all-path final-fee dispatch enforcement, GUI confirmation, fresh package and
  genuine-budget live acceptance remain open. No live wallet/package action,
  main merge or release occurred.

Primary schema evidence:
- https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage-api/src/records/coin.rs
- https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage-api/src/types/amount.rs
- https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage-api/src/records/token.rs
- https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage-api/src/requests/data.rs
- https://github.com/xch-dev/sage/blob/v0.13.0/crates/sage/src/endpoints/data.rs

## Frozen economic recipe and runtime collection (continuation)

- The persistent fee-approval goal and existing hourly heartbeat were verified
  ACTIVE. No duplicate goal or automation was created; the approved full scope
  remains unchanged.
- Added shared exact economics for tiered/uniform settings, live counts and
  spares, generated sell-ladder CAT sizing, reverse buy positions, one-sided
  operation, reserves, headroom and retained dedicated fee-coin principal.
  Worker CAT sizing and XCH headroom now consume the shared sizing helpers.
  Tiered preparation retains its historical counts rather than claiming that
  the optional uniform-mode coin multiplier changes those cohorts.
- The read-only runtime economic collector derives these outputs from verified
  current wallet/configuration snapshots, resolves existing Bootstrap authority,
  rejects client economic authority and missing price/campaign fallback, and
  rechecks configuration, fee pool, identity and campaign after collection.
  It creates no approval, consent, hold, effect claim or wallet dispatch.
- Two focused failures exposed a real Bootstrap contract mismatch: fresh
  campaigns have authoritative revision 0, but fee contracts required revision
  1 or later. The validator now accepts and binds revision 0 without inventing
  a newer revision. Four additional failing regressions showed legacy fee-pool
  helpers silently coerced invalid raw counts/sizes; the preview collector now
  rejects those settings before using the legacy derived fee-pool plan.
- Fresh economics/snapshot/contract/one-sided worker/direct batch/planner/preview/
  storage/consent/ledger/recovery/estimation/transaction-fee regressions:
  315 passed in 56.26s. Ruff and `git diff --check` passed. An earlier runtime
  test queried a nonexistent table; correcting it to the real approval/consent
  tables preserves the no-mutation assertion. These receipts are scoped tests,
  not full feature, independent review, fresh build or live acceptance.
- Runtime staged costs/funding, HTTP/native preview/consent endpoints, final
  dispatch adoption and every-path fee holds, GUI confirmation/E2E, fresh
  package and genuine-budget live acceptance remain open. CLI overrides alone
  do not prove frozen output ordering; execution must adopt that exact contract.
  No live package/wallet action, main merge or release occurred.

## Exact next-batch pricing and retained funding (continuation)

- The existing persistent goal and hourly heartbeat remain ACTIVE; full approved
  scope is unchanged. No duplicate goal/automation, live action or release.
- Added read-only four-round cost/fee convergence using actual validated unsigned
  effects and fresh cost-specific guidance. Fee-induced input/change changes are
  rebuilt; unavailable/oscillating paths return no usable bundle. Zero guidance
  stays zero. A one-mojo unsigned-only collision seed is not a fee floor or a
  spending authorization, and an unbuildable final zero fee still refuses.
- Retained funding includes all requested principal and the greater physical or
  declared reserve. Exact reusable denominations are assigned once. Dedicated
  fee-coin face value is principal, not transaction spending. Journal-protected
  funds cannot count toward reserve floors or fees; focused failures reproduced
  the prior conflation with permanent reserve designations before correction.
- Runtime collection rereads inventory/protection, identity, configuration,
  economic recipe and campaign after unsigned pricing. Focused failing tests
  exposed the need to recheck whole-plan fee capacity and original quote expiry
  after that reread; both now fail closed without returning pricing evidence.
- Independent bounded review found no Critical/Important/Minor defect in this
  groundwork. It did not review or certify the unfinished full workflow.
- The earlier expanded run passed 385 tests in 66.42s. An additional real CAT2
  executable bundle with separate XCH fee input passes cost/fee repricing;
  fresh pricing run: 25 passed in 0.89s. Fresh final expanded snapshot/funding/
  pricing/unsigned/economics/worker/planner/preview/storage/consent/ledger/
  recovery/estimation/transaction-fee run: 386 passed in 71.55s. Ruff and diff
  checks passed. These are scoped receipts, not full-feature acceptance.
- Full multistage projection, public HTTP/native APIs, operator confirmation,
  exact holds and all-path dispatch enforcement, GUI/E2E, fresh Windows build
  and genuine operator-budget live acceptance remain open. Available internal
  evidence never grants dispatch permission. Current live package is preserved.

## Server-owned runtime confirmation and HTTP/native consent (continuation)

- The persistent goal and existing hourly heartbeat remain ACTIVE with the full
  approved scope. No duplicate goal or automation was created.
- Confirmation accepts a persisted server preview ID plus the operator's exact
  maximum and protected cancellation allowance. It rereads current verified
  wallet identity, actual asset, economic outputs, campaign and retained funding;
  caller-supplied scope, plan, cost or funding cannot substitute for that evidence.
  New consent checks principal and fresh fee funding together with prior scope
  commitments inside the serialized database transaction.
- Focused failing tests exposed two confirmation defects before their fixes:
  pending inputs must not prevent idempotent readback of an existing consent,
  and a quote can expire while waiting for the database write lock. Existing
  consent now returns held/spent accounting without granting redispatch, while
  runtime freshness is sampled after BEGIN IMMEDIATE has acquired the lock.
- Added authenticated, mutation-protected HTTP and native approval surfaces.
  They require a closed payload, reject malformed/coerced amounts and client
  economic authority, and create no fee hold, effect claim, worker or wallet
  transaction. Both return decimal-string monetary accounting. Two failing
  tests at 9,007,199,254,740,993 mojos reproduced the previous JavaScript JSON
  precision hazard before the shared response boundary was corrected.
- Combined-test failures were traced to imported test fixtures retaining a
  different file's project-module instances under conftest isolation. Shared
  helpers now live in a non-test utility module and bind current dependencies
  at setup. An earlier diagnostic setup performed read-only real Sage metadata
  reads because its transport mock targeted the wrong module instance; no
  signing, submission or production database mutation occurred. Reverse-order
  isolation smoke: 8 passed. This test-harness issue is not a live app defect.
- Fresh final confirmation/API/storage/consent/ledger/recovery/wallet snapshot/
  preview/funding/pricing regressions: 253 passed in 78.47s. Separate local API
  guard/economics/unsigned preview/estimation/transaction fee regressions:
  139 passed in 10.31s. HTTP/native confirmation alone: 35 passed in 14.83s.
  Ruff and git diff --check passed. Independent bounded review found no
  remaining Critical/Important/Minor finding in this scoped groundwork.
- Full staged projection and public preview, frozen dispatch adoption and all-
  path exact holds, authoritative settlement integration, GUI/E2E, fresh Windows
  package and genuine operator-budget live acceptance remain incomplete. No
  live package reload, wallet mutation, main merge or release was performed.

## Matched exact-effect quote preservation (continuation)

- The existing persistent goal and hourly heartbeat remain ACTIVE; the full
  approved scope is unchanged. No duplicate goal or automation was created.
- The internal stage aggregator now accepts collector-owned matched quotes.
  It preserves the fee/cost-consistent quote from exact unsigned pricing rather
  than making a second request that could sever the inspected effect's fee from
  its displayed cost. Remaining stages still request fresh network guidance.
  Original source/observation/expiry survive aggregation and persistence.
- Cost, target, source, exact integer fee and original 60-second lifetime are
  revalidated. Invalid matched guidance makes the preview unconfirmable without
  substituting another quote. Readback drops extra fields and derives XCH text
  from integer mojos using Decimal. No effect authority or dispatch is created.
- Red receipt: 15 new missing-interface failures, 13 prior preview tests passed.
  Initial green preview receipt: 28 passed in 9.44s. Expanded verification then
  exposed inconsistent clocks between aggregation and validation (11 failed,
  263 passed). A single-case confirmation reproduced FEE_ESTIMATE_UNAVAILABLE.
  The shared validator now accepts a trusted internal observation time and the
  aggregator supplies its current clock per check; no client timestamp is accepted.
- Corrected focused confirmation/preview/pricing receipt: 54 passed in 13.03s.
  Fresh expanded preview/pricing/estimation/contracts/confirmation/HTTP-native/
  storage/consent/ledger/recovery command: 274 passed in 62.09s. Ruff and git
  diff --check passed. Independent bounded review found no Critical/Important/
  Minor finding, including the observation-clock correction.
- This is internal Task 3 groundwork, not a completed multistage runtime preview,
  stable standalone-session lifecycle, public preview route, GUI or dispatch
  enforcement. Full acceptance remains open. No live wallet mutation/package
  reload, Windows build, main merge or release occurred in this continuation.

## Durable standalone session ownership (continuation)

- Full approved scope, persistent goal and hourly heartbeat remain ACTIVE. Work
  remains isolated on codex/coin-prep-fee-approval; unrelated artifacts and the
  live package are preserved.
- Closed canonical wallet identity resolves one server-generated standalone
  session. BEGIN IMMEDIATE serializes concurrent collectors. Immutable ownership
  records bind identity digests and survive refresh, genuine restart, terminal
  history reset and observability-counter reset. Campaign scope does not mint a
  standalone session. A changed plan in the same session retains earlier fee
  commitments rather than resetting the allowance.
- Confirmation requires current persisted standalone ownership before any
  wallet read. Unknown or foreign session IDs cannot acquire consent. Ownership
  readback validates canonical schema and grants no spending authority, worker,
  fee hold or wallet effect.
- Red receipts: initial missing-resolver assertions; a true restart of a pre-fee
  installation reproduced `stability migration watermark contradicts schema`;
  confirmation of an unowned preview failed to raise before the ownership gate.
  Tests explicitly invalidate the init path cache for genuine migration restart.
- Added a separate fee-schema completion watermark. Genuine upgrades preserve
  old stability markers and held fees. Missing fee tables after marked migration
  completion remain fatal; this is not permission to erase durable accounting.
- Focused ownership/confirmation verification: 46 passed in 24.76s. Additional
  unknown/foreign ownership cases: 2 passed in 3.16s. Expanded fee preview,
  pricing, estimation, contracts, confirmation, HTTP/native, storage, consent,
  ledger and recovery command: 300 passed in 88.52s. Ruff and git diff --check
  passed. Independent bounded review found no Critical/Important/Minor finding
  and independently reproduced the 46-test focused result.
- Separate stability-schema, post-TibetSwap migration, database-unit and boost-
  migration regressions: 205 passed in 84.91s.
- Later-generation session completion is intentionally NOT implemented. A new
  generation is refused until journal-proven completion transitions are added.
  This is initial ownership groundwork, not the full lifecycle, public preview,
  GUI or dispatch enforcement. No live wallet mutation, package reload, Windows
  build, main merge or release occurred in this continuation.

## Executable future-stage cost projection (continuation)

- Added an internal standard-P2/CAT2 projection component for future stages
  whose real input coins do not exist yet. It executes an explicit synthetic
  CLVM profile through the wallet cost facade, without RPC, signing or submission.
  Synthetic spends are never returned, persisted as effect evidence or treated
  as dispatch authority. Exact real unsigned effects still require final pricing.
- Closed count bounds and recognized module/key checks refuse unknown puzzles,
  malformed profiles and unusable consensus costs. The disclosed assumptions
  include maximum-width amounts, one 32-byte hint per output, concurrent-spend
  mesh and linked CAT rings with maximum-width nonzero subtotals. This is an
  envelope for the represented standard shape, not arbitrary delegated programs,
  extra memos or wallet extensions; integration must enforce that distinction.
- Initial missing-module tests observed 14 failures. Fixture investigation found
  that uncurrying the published P2 module stripped its pre-curried constants;
  reconstructing the complete module fixed the fixture. Initial model: 14 passed.
  Boundary regressions then observed three failures (aggregate output limit,
  over-consensus cost and output integer width), followed by 22 passing tests.
- Independent review identified a valid linked CAT2 counterexample: 80,743,184
  executable cost versus the independent-ring projection of 80,647,152. A focused
  regression observed that underestimation before changing the model. Linked
  rings and concentrated returns fix it, with a new explicit assumption.
- Final focused verification: 32 passed in 1.69s, including independently rebuilt
  first/last/distributed linked CAT returns with 2, 3 and 23 CAT inputs, smaller
  actual native spends, maximum native/bulk-cancel profiles and fail-closed bounds.
  Independent re-review reproduced 32 passing tests and found no remaining issue.
- Ruff and git diff --check passed. This component is not yet wired to the staged
  runtime collector or public preview; no full-feature readiness claim is made.
  Fresh expanded projection, wallet snapshot, pricing, unsigned effect, batch
  planner, funding, preview, confirmation and HTTP/native regressions after the
  CAT correction: 285 passed in 70.73s.
  No live wallet mutation, package reload, Windows build, main merge or release
  occurred during this continuation. The full goal and hourly loop remain active.

## Bounded staged runtime preview and HTTP/native surfaces (continuation)

- Connected the verified current economic/wallet snapshot to the exact first
  unsigned batch and its original cost/fee-consistent network quote. Future
  native preparation and individual cancellation protection are explicitly
  projected standard-P2/CAT2 profiles, not prebuilt future transactions.
- Native repeated denominations may need intermediate in-bundle spends. The
  projected native envelope now includes disclosed ephemeral spend coverage.
  Four new profile tests were observed failing before implementation; all 36
  projection tests subsequently passed.
- Cancellation cover uses frozen replacement output counts (including spares),
  with the explicit assumption `one_individual_cancel_per_prepared_replacement`.
  Fee-coin face value remains retained principal, separate from fee spending.
- Added guarded POST `/api/coin-prep/fee-preview` and the native bridge surface.
  Choices only are accepted; scope, costs, stages and funding cannot be supplied
  by clients. Readback recursively serializes mojo integers as decimal strings,
  including nested stage quotes. Preview creates no consent, fee reservation,
  operation journal, signing, submission or worker launch.
- Initial staged tests observed seven missing-service failures. Initial API/
  native tests observed 14 missing-surface failures and four passing safety
  guards. Missing explicit native access classification was then caught during
  collection and corrected without weakening the inventory check.
- A real unsigned bare-hex Sage response reproduced a projection-template parse
  failure (`bytes object is expected to start with 0x`). Normalize only the
  already-executable-validated spend copy for chia_rs JSON parsing. Original
  wallet effect data and evidence remain unchanged. The focused regression then
  passed. Slow final quotes cannot renew observation age or persist a usable
  stale preview. Buy-only and sell-only cases exclude irrelevant protection.
- Bounded independent review identified an understated future-native count:
  total funds could suffice while the largest 50 roots could not fund the
  pending native principal. An actual CLVM/Sage-summary fixture reproduced the
  omission with 61 roots of 2b mojos and 112b frozen native principal.
- Future amount analysis now excludes protected/reused roots, removes the
  consumed CAT fee root and incorporates its validated fee change. If needed,
  the preview prices 50-root-to-one-output bounded consolidation prerequisites,
  with upper count ceil((N-50)/49), before the final projected native stage.
  All upper-count fees are covered. Positive merge and final funding checks
  refuse unrepresentable progression; no future selectable IDs are invented.
  Optional projected work can show lower count zero without dropping the upper
  budget. Exact unsigned stages still require a positive exact count.
- Verification covers one prerequisite, three prerequisites and a >50-root
  inventory where no consolidation is needed. Independent re-review found no
  remaining finding in the bounded deltas and reproduced 97 focused passes.
  Full dispatch/compatibility support is NOT established by this projection.
- Final broad regression command covered preview API, confirmation API, staged
  runtime, projection, wallet snapshot, pricing, funding, aggregation, canonical
  contracts, confirmation, unsigned preview, batch planner, Sage executable
  effects and Bootstrap mutation protection: 368 passed in 87.51s, exit 0.
  Ruff checks over all changed Python files and git diff --check passed.
  No live wallet mutation, package reload, Windows build, main merge or release
  occurred. The full goal and hourly loop remain active.

## Atomic consent/journal-bound final prep hold (continuation)

- Added internal `database.reserve_coin_prep_fee_for_dispatch`, with deliberate
  preview-backed consent and latest version, exact PREPARED operation, bound
  constructed outputs and active undispatched effect claim checked inside the
  same IMMEDIATE transaction as the fee hold. A generic ledger approval is not
  operator consent. Original quote freshness is sampled after acquiring the
  write lock; manual, unavailable, malformed, future or expired quotes cannot
  hold a fee. The quoted fee must equal the journal's exact final fee.
- Holds preserve the cancellation allowance, match wallet backend/fingerprint/
  network/CAT asset and normalize exact source and external fee cohorts.
  Existing or previously dispatched operations cannot gain replay authority.
  Two competing workers produce one hold. Existing ledger arithmetic is shared
  without changing its conservative accounting and idempotent read semantics.
- Initial fixture investigation found a test clock double omitted `time_ns`,
  causing claim setup failure. Corrected only the clock fixture. The complete
  initial 15-test red run then failed on the missing atomic boundary. Initial
  implementation passed all 15; added contention/identity/version checks extend
  verification of existing implemented branches rather than new functionality.
- Independent review found that the existing prepared-operation API did not
  bind its separate external-fee cohort to the claim. A normal-API isolated
  fixture reproduced a target for fee coin 2 with a claim for fee coin 9;
  the focused regression failed with DID NOT RAISE. The hold now rejects the
  mismatch before insertion. Success tests caught bare-hex versus canonical
  `0x` source comparisons during that fix; normalized both expected cohorts.
  No production safety check or test assertion was weakened.
- Fresh broad regression run: 190 passed in 80.39s, exit 0, covering the new
  hold, ledger/recovery, preview/confirmation, consent validation/storage/session
  ownership and existing direct batches. Fresh independent re-review reproduced
  58 hold/ledger/recovery passes, exit 0, with no remaining findings in this
  bounded delta. Fresh stability-schema suite: 133 passed in 47.45s, exit 0.
  Ruff and git diff --check passed.
- This is a fee-hold primitive, NOT completed dispatch enforcement: it never
  signs/submits and always returns dispatch_authorized=false. The trusted fee
  service must validate actual unsigned executable cost/effects and frozen
  economics/configuration before calling it, then use the existing effect fence.
  Worker integration, every compatibility family, cancellation dispatch and
  automatic recovery/accounting remain unfinished. No live wallet mutation,
  reload, package build, main merge or release occurred.

## Frozen approved execution readback (continuation)

- Runtime previews now persist a private server binding of lossless typed
  configuration, receive address and exact prepared sizing arguments. Pure
  validation reconstructs these targets and matches approved canonical outputs,
  reserves and liquidity mode. Original headroom/multiplier metadata is retained
  without applying it to the already-adjusted prepared sizes a second time.
- Approval confirmation rejects changed execution settings/address even when
  canonical output amounts happen to remain unchanged. Older core-only preview
  fixtures can still record consent but cannot provide frozen execution readback.
  Runtime previews always include the validated private binding; no client gets
  configuration/CLI authority from the public response.
- The new approved snapshot reader refreshes actual identity/asset/selectable
  inventory, verifies configuration/address/session or campaign/latest consent,
  and consumes frozen targets without market-price reads. Inventory changes
  neither resize the plan nor constitute proof of intermediate transaction
  completion. Actual funding, executable effect proof, Bootstrap financial caps,
  final pricing/holds and effect dispatch fences must still be enforced by the
  not-yet-integrated worker. dispatch_authorized is always false here.
- Initial nine focused tests failed on missing binding/readback behavior before
  implementation. Three more confirmation regressions failed with DID NOT RAISE
  on fee-mode/manual-fee/expected-name changes; a zero-exponent canonicalization
  regression also failed before its fix. Decimal fixed-point size is now bounded
  before formatting; compact enormous exponents cannot allocate huge strings.
- Expanded focused suite: 23 passed in 17.37s, exit 0. Independent read-only
  review reproduced 74 frozen/confirmation/staged/HTTP-native preview passes,
  exit 0, with no findings in this bounded groundwork. Ruff and diff whitespace
  checks passed. Wider suite covering frozen execution, staged preview,
  HTTP/native preview/confirmation, canonical contracts, pure target economics,
  wallet snapshots and atomic dispatch holds: 324 passed in 103.25s, exit 0.
  That run included the original 13 frozen tests; the final 23-test focused run
  additionally covers invalid/huge Decimal values, changed identity/inventory/
  receive address and resized CLI rejection.
- No live wallet mutation, reload, package build, main merge or release occurred.
  The full implementation goal and hourly continuation loop remain active.

## Exact frozen pricing-to-hold service (continuation)

- Added internal price_approved_prep_batch: trusted frozen consent and current
  selectable inventory feed real executable unsigned inspection and bounded
  network fee/cost convergence. Fresh context and durable accounting are reread
  after slow work. Unknown holds remain counted; price increases inside the
  remaining preparation allowance may proceed to claiming, while provider loss,
  unfunded principal/fees and over-budget fees expose no usable bundle.
  Manual mode cannot bypass unavailable network guidance.
- Added reserve_approved_prep_dispatch: reconstructs the saved exact pre-claim
  plan under current frozen economics, recomputes actual executable cost/effects,
  compares the current original-age quote and exact fee, derives the operation
  ID, binds actual additions, then joins the existing atomic journal/claim-bound
  hold. It returns no signing/dispatch authority; retrieval cannot authorize
  operation replay. No worker path invokes these helpers yet.
- Six focused regressions failed before the pricing service existed; four more
  failed before the executable/journal-to-hold boundary existed. Independent
  review then reproduced a disappeared CAT root still obtaining a cached-bundle
  hold. Missing-root and changed-amount regressions failed DID NOT RAISE before
  the fix. Full inventory is now compared before and after executable inspection;
  only exact process-current own-claim protection labels may be normalized.
  Inventory amount/asset/selectability, other protections and funding changes
  cannot be ignored. Recovery-list APIs are not used because they latch state.
- An explicit non-creating getter regression failed before its fix; new
  get_coin_prep_fee_dispatch_claim now uses read-only SQLite. Review also found
  a reserve designation race after service checks: a normal set_coin_designation
  regression failed DID NOT RAISE. The final hold now checks the exact selected
  cohort's reserve designations inside BEGIN IMMEDIATE, without the availability
  filter that hides own claimed roots from unrelated planners.
- A combined run initially produced 23 fixture errors because the shared
  approval fixture held a prior test file's database/clock module after conftest
  restoration. Rebinding current project modules fixed the fixture without
  changing production freshness rules. A subsequent 135-test regression passed;
  final corrected regression (pricing-to-hold, frozen execution, exact pricing,
  atomic holds, funding, ledger and authoritative recovery): 137 passed in
  63.10s, exit 0, including all 19 newest boundary tests. Ruff and
  git diff --check passed.
- Independent final read-only review found no remaining findings in this
  bounded groundwork; reproduced 62 pricing/frozen/hold passes and two latest
  missing-database/atomic-reserve passes. Full implementation gates remain open.
  No wallet mutation, live reload, build, main merge or release occurred.

## Outstanding acceptance gates

Session completion lifecycle, remaining compatibility/prerequisite-family canonical plan preview,
all-path dispatch enforcement, authoritative settlement/recovery integration, GUI confirmation/E2E,
full regression testing, fresh Windows build and live operator-approved fee acceptance
remain incomplete. These tests do not prove the entire feature ready.

The live package was not reloaded or changed, no wallet mutations were performed,
and no release or main merge was made during this checkpoint.

## Protected cancellation allowance and resumed verification (22 September 2026)

- Coin Prep's Sage Cancel All path now constructs and validates one exact unsigned
  cancellation transaction, prices its real CLVM cost with current guidance,
  reserves the exact final fee only from the approval's protected cancellation
  allowance, rechecks context/freshness, and submits those same sealed bytes.
  It never falls back to the ordinary static-fee Cancel All path.
- Durable one-to-500-member cancellation manifests bind roots, fee input,
  reservation and wallet-effect evidence. Confirmed cohorts charge the fee once;
  authoritative all-member no-effect releases it; ambiguity preserves the hold.
  Startup recovery retries unsettled outcomes idempotently. Existing databases
  with earlier two-member bounds migrate by canonical table copy without SQLite
  trigger/foreign-key retargeting.
- A single remaining live offer is valid. A genuinely available zero-fee quote
  remains zero and has no fabricated fee input, while retaining the same manifest
  and recovery guarantees. Ordinary/legacy cancellations without a protected
  manifest are not charged to Coin Prep approvals.
- The HTTP route requires the exact typed Coin Prep approval shape. A resumed
  acceptance audit found that the PyWebView bridge discarded that payload; a
  failing native regression reproduced `{}` reaching the route. The bridge now
  forwards the exact JSON body. Chromium verifies the GUI sends only
  `source=coin_prep` and the confirmed 64-hex approval ID.
- Focused evidence: cancellation/recovery baseline 138 passed; reconciliation
  and stability 449 passed; complete protected cancellation/API set 261 passed;
  Chromium fee-approval E2E 9 passed; final cancellation/API/native/browser gate
  216 passed. Ruff over all changed Python files passed and whitespace was
  corrected after `git diff --check` identified one trailing space.
- The broad affected run completed with 1,706 passes and two diagnostics child
  startup timeouts. Both failures reproduced only while Windows Defender cold-
  scanned each new SQLite snapshot (measured near 19 seconds); both tests passed
  individually in 8-9 seconds once warm. No production timeout or safety rule was
  changed to conceal this host condition.
- Sage RPC is listening again after the PC restart. CATalyst remains stopped;
  no wallet transaction or fabricated operator confirmation has occurred. Fresh
  full regression, Windows package verification, isolated packaged GUI exercise,
  genuine TEST 7 operator-approved live acceptance, final audit/commit and any
  integration decision remain Task 6 gates. Main and release remain untouched.

## Full-suite compatibility cleanup (22 September 2026)

- The first serial full-suite run after protected cancellation completed with
  6,868 passed, 99 skipped and 422 subtests passed. Ten failures were isolated:
  six older Coin Prep/crash fixtures omitted the now-required fee approval,
  two market-history assertions used fixed 20 August fills that had crossed the
  production 30-day boundary, and two cold diagnostics children exceeded their
  ten-second test-only readiness allowance while Windows scanned fresh SQLite
  snapshots. None represented duplicate wallet work or escaped fee authority.
- Legacy Coin Prep unit fixtures now exercise an approval-shaped launch or the
  deliberate `FEE_DISPATCH_UNSUPPORTED` pause. Already-prepared completion is
  explicitly approval-bound. The crash route still tests state reset, but first
  passes the same server-side approved-dispatch gate as production.
- Market-history tests now mint recent authoritative receipt timestamps instead
  of depending on the calendar date; the production 30-day query remains
  unchanged. The diagnostics helper remains bounded but uses a 30-second cold-
  start allowance consistent with the other standalone server helpers; no
  production timeout or diagnostic safety behavior changed.
- All eight corrected failure cases passed together. The four affected test
  modules then passed 154 tests, the two diagnostics parameter cases passed,
  and the five changed files pass Ruff formatting/lint plus `git diff --check`.
  A new full serial run, E2E/build and genuine operator-approved live acceptance
  are still required before readiness can be claimed.
- The subsequent hermetic serial run disabled unintended external Coinset access
  at the environment boundary and completed with 6,878 passed, 99 skipped and
  422 subtests passed in 1,061.51 seconds. There were no failures, cold-start
  diagnostics timeouts or Windows socket exceptions. Intentional Coinset tests
  continued to use their explicit mocked configuration and responses. Browser,
  fresh package and live operator-approved acceptance gates remain open.

## Complete Chromium gate after restart (22 September 2026)

- The first full opt-in Chromium run completed with 92 passes and six failures.
  All six were older browser fixtures that predated the fail-closed fee contract:
  five supplied no `estimated_total_fee_mojos`, so client-side cap validation
  correctly refused to record consent or trigger Coin Prep; one attempted a
  protected Coin Prep cancellation without its 64-hex approval ID, so no cancel
  request was sent.
- The fixtures now carry the same displayed total and approval identity required
  by production. The six previously failing cases passed together, including
  both parameter variants. The corrected async cancellation/recovery case then
  passed independently.
- The complete real-Chromium E2E suite passed 98 tests in 73.17 seconds with
  external Coinset lookup disabled. Production code and fail-closed validation
  were not weakened. Fresh Windows package and genuine operator-approved live
  acceptance gates remain open; CATalyst is still stopped and no wallet action
  occurred.

## Fresh Windows package gate (22 September 2026)

- A clean `python build.py` from commit `723ab6f` completed successfully with
  PyInstaller 6.21.0 and Python 3.12.6. The build verified bundled HTML assets
  and the certifi CA bundle. The isolated executable is version 1.4.0, size
  11,232,145 bytes, SHA-256
  `45DC07C1FEDCF1AF50476C7765DC66816660C0D26424667176CDDA4613D8FE13`.
- The packaged API smoke passed health, mock-Sage startup, config validation,
  diagnostics, self-test and doctor endpoints. The packaged worker authenticated
  to an isolated mock Sage server with mutual TLS and passed its read-only RPC
  probe. Neither test used the live wallet.
- The packaged Windows desktop smoke passed clean first launch, duplicate-window
  handoff, persisted relaunch and the branded fail-closed native safety fallback.
  Temporary test data and ports were isolated; the installed/live package and
  user data were not replaced.
- The remaining acceptance gate is a real TEST 7 preview and genuine operator
  confirmation of the displayed maximum fee, followed by bounded live Coin Prep
  and restart/recovery verification. No such consent or wallet mutation has yet
  occurred. Main and release remain untouched.

## Live read-only acceptance and GUI corrections (22 September 2026)

- The packaged candidate was connected to Sage TEST 7 fingerprint 736588221,
  mainnet wallet 2 and MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
  The bot was stopped and no offers were open. A prior Bootstrap campaign was
  stopped using its GUI; one cancellation entered the ambiguous-submission
  safety gate, then the app's reconciliation-only Cancel All path resolved it.
  The runtime safety gate returned ALLOWED with zero unresolved operations.
- A local preset `pre-fee-live-acceptance` retained the original 97-field
  configuration. For a bounded test, the saved Follow-mode setup was reduced
  to three offers per side, 0.1 XCH base size and untiered prep. This is a
  temporary live test configuration, not a restored trading strategy.
- A fresh GUI estimate from the packaged build exposed a client bug: entering
  zero prep headroom displayed zero in Settings but `saveConfig()` used `|| 10`
  and silently persisted 10 percent. Wallet verification also treated zero
  as ten percent. Two Chromium regressions reproduced the mismatch; both
  client paths now use the shared zero-preserving headroom helpers. A third
  red/green regression fixes the live fee-screen ticker `MZ_XCH/XCH` to
  `MZ/XCH`. All 12 focused browser cases passed. The first post-edit full
  browser run had 100 passes and one isolated localhost navigation error
  (`ERR_NO_BUFFER_SPACE`) during concurrent live Sage/Splash activity; the
  affected startup test passed alone, then the complete 101-case Chromium
  suite passed on rerun. `git diff --check` is clean.
- The old package was shut down cleanly with no offers left behind. The updated
  source server was started on port 5000; Sage v0.13.0 reconnected to TEST 7,
  and the MZ pair/asset were reselected. Splash started. The operator chose
  Spacescan free-tier mode for this session, avoiding retransmission of the
  stored API key. The bot remains stopped and runtime safety ALLOWED.
- The updated live GUI now agrees end-to-end on zero headroom: six XCH outputs
  at 0.1 XCH and six MZ outputs at 1,333 MZ. The fresh Coinset quote showed
  two preparation transactions, one exact unsigned and three projected stage
  profiles, 300-second target, 0.000718705906 XCH estimated total including
  0.0000764193 XCH protected cancellation allowance, and 0.05 XCH fee-coin
  principal rather than a fee. The quote is time-sensitive and not an approval.
  A read-only status check after refresh confirmed zero open offers, zero
  blockers and unchanged spendable XCH/MZ balances. No new fee-budget consent
  or Coin Prep transaction has occurred. The operator has been asked to review
  and personally confirm a fresh displayed maximum through CATalyst before
  live spend testing; that acceptance gate remains open.

## Expiring preview browser regression (22 September 2026)

- The live GUI displayed a fixed age after rendering a fee quote. An expired
  estimate could therefore appear recent and leave the confirmation button
  enabled, although the backend would reject it. The browser now advances the
  displayed source/age every second, marks an expired quote explicitly, and
  disables confirmation until refresh. Refresh hides stale fee and cap details
  while a replacement quote is requested.
- A second regression showed expiry during the history-choice dialog could
  still reach the approval endpoint. The launch handler now revalidates both
  freshness and the unchanged operator maximum immediately before recording
  consent. Closing the modal stops the age timer. The new browser tests were
  observed failing before production changes and now pass.
- Four older smoke fixtures were updated to include valid live expiry fields;
  production fail-closed behavior was not weakened. All 14 focused fee browser
  tests and the full 103-case Chromium suite pass. The relevant fee backend
  suite passed 570 tests in 210.22 seconds; during it, Windows emitted noisy
  network exceptions while some test paths attempted external Coinset access,
  so the previously recorded hermetic full-suite run remains the authoritative
  broad backend gate. The live source app remains idle with zero offers and
  unchanged spendable TEST 7 XCH/MZ balances. No wallet mutation occurred.
- A fresh isolated PyInstaller Windows build was made without cleaning or
  replacing the existing `dist/Catalyst` package. Its executable SHA-256 is
  `1F9533C8A1B897DE6FB95774379E14A235A1B19FD53FDB1DB91A4CF94135C0DE`;
  bundled GUI and certifi CA files are present. The packaged Sage mTLS worker,
  clean/duplicate/persisted/native-safety desktop launches, and packaged API
  smoke all passed. The API smoke's first two attempts reached seven endpoints
  but timed out at doctor during transient local network/Sage contention; a
  previous package passed as a control and the new package then passed the
  complete eight-endpoint smoke unchanged. No release package was published.
- The source app's real TEST 7 GUI was reloaded, MZ wallet 2 reselected, and
  the same bounded zero-headroom settings re-saved. The refreshed GUI displayed
  the corrected `MZ/XCH` pair label and a 12-second-old Coinset quote. Without
  any synthetic clock change, the quote later displayed `72s old`, `expired —
  refresh required`, and a disabled preparation confirmation button. No fee
  approval or wallet transaction was submitted. The bot stayed stopped with
  zero offers and unchanged 138.472874970211 spendable XCH / 780212.284 MZ.
- The 570-test fee-specific backend suite was repeated with unintended
  external Coinset access disabled only in that test process. It passed in
  185.71 seconds, without the earlier Windows network exceptions. The live
  app configuration and fee source were not changed by this test setting.

## Candidate handoff and broad rerun (23 September 2026)

- The 103-case Chromium E2E suite passed again. The candidate branch
  `codex/coin-prep-fee-approval` was published to GitHub at `7f39471` for
  secondary-PC review; it has not been merged or released. The remote `main`
  contains a separate squash commit of earlier v1.4 work, so branch history
  is divergent and must be reconciled before a clean PR to `main`.
- The live TEST 7 MZ/XCH GUI showed a new Coinset quote of
  0.000994804981 XCH total maximum, including 0.000105776646 XCH protected
  cancellation allowance. It expired without operator confirmation. The bot
  remains stopped; no Coin Prep transaction was submitted. The operator was
  asked to refresh and confirm a current maximum in CATalyst itself.
- A hermetic broad Python rerun recorded 6,877 passed, one skipped, 422
  subtests passed, and one failure in the unrelated desktop startup-arbiter
  diagnostic server timing test after 18m59s. That test's spawned diagnostics
  server did not become ready within its 30-second bounded wait, with empty
  captured stdout/stderr. The same test passed once immediately afterward
  and in three further isolated reruns (about nine seconds each). This is
  evidence of an intermittent full-suite startup timing failure, not a clean
  broad-suite pass; root cause remains unproven. Do not count the broad gate
  as fully green or merge on this evidence.

## Uniform-mode live failure and candidate fix (23 September 2026)

- The operator confirmed a fresh exact TEST 7 MZ/XCH Coin Prep fee cap in the
  GUI: approval `e2d754a39acbef7efe10bee647128479dbced3b35fcbc46011b8f3508ab7c6dc`,
  1,269,651,253 mojos total including 135,000,780 mojos protected for
  cancellation. The worker failed with `FEE_DISPATCH_UNSUPPORTED` before
  dispatch. The durable journal still reports zero held or spent fee, zero
  reservations and unresolved operations, and the approval remains current.
- Root cause: the UI/pricer permitted the normal untiered output recipe but
  `_run_direct_batch_prep` rejected every untiered worker. The candidate now
  allows the Sage/DB direct path for untiered approved plans and classifies
  final outputs from the frozen approved targets, without returning to a
  manual fee or legacy signing route. Focused regressions were observed red
  before the production change and green afterward; 24 dispatch tests pass,
  along with the 423-test fee-specific backend selection and 14 browser
  approval tests. Ruff and `git diff --check` pass.
- A fresh isolated Windows bundle was built without touching the existing
  live package; executable SHA-256 is
  `9A9B75FBD04BD7EA79B0AACB4C4381F43704F55432DAE5A6AA867B6CF47DD2AB`.
  Packaged API and Sage RPC worker smoke checks pass. The source server on
  port 5000 still runs the old worker. The attempted exact-process restart
  was denied by process-control policy, so the new code has **not** received
  a live-wallet retry. The operator must close that app before the new source
  server can be started; no approval bypass or live spend was attempted.

## TEST 7 uniform live Coin Prep and terminal-fee recovery (23 September 2026)

- After the operator closed the old server, the fixed source server started at
  commit `61b6e38`. Sage v0.13.0 was healthy on mainnet TEST 7 fingerprint
  `736588221`; MZ remained wallet ID 2 with the expected asset ID. The
  previously confirmed approval was current and untouched (zero fee spent or
  held). No offers were open. The approved untiered plan was retried without
  requesting a second budget.
- The first CAT batch reached Sage and confirmed, producing six additional
  CAT coins. Its exact reserved fee was 13,306,061 mojos. A second defect was
  exposed: the prep operation became authoritatively terminal, but the fee
  reservation remained unresolved, causing the next batch to stop with
  `FEE_EFFECT_RECOVERY_REQUIRED`. The durable terminal journal was reconciled
  through `record_fee_reservation_outcome` validation, not by trusting the
  submit response or timing out. This settled 13,306,061 mojos as spent and
  released the hold; no effect was replayed.
- A restart-safe, idempotent terminal-fee settlement pass was added before
  approved-batch pricing and immediately after authoritative completion or
  no-effect. Regressions were red before the new repository function and green
  afterward. The focused 29 tests passed; the broader fee selection passed
  428 tests with 14 opt-in skips. Ruff and diff whitespace checks passed.
- The same approved plan resumed. The second XCH batch was submitted with a
  9,531,051-mojo hold. Sage reported it pending for about five minutes, then
  the exact output view confirmed it. The fee settled once. Coin Prep reached
  `complete`, closed the scope from 62 approved targets and two confirmed
  operations, and reported six XCH and six CAT prepared trading outputs.
  Durable replay reconciliation returned zero additional settlements. Final
  accounting: 22,837,112 mojos spent, zero held, zero unresolved.
- The final designation sweep logged two `upsert_coin` refusals, consistent
  with its protected-coin guard, and left older non-target coins unassigned;
  tier designations for the six current XCH and six CAT outputs succeeded.
  This should be reviewed separately before treating the entire app acceptance
  as exhausted. The bot was not started, and original strategy/reserve settings
  remain saved in the `pre-fee-live-acceptance` preset rather than restored.
- A fresh isolated Windows bundle (no replacement of the existing live
  package) passed packaged API and Sage RPC worker smoke. Executable SHA-256:
  `F9F73CB5BFB9BDA751407104AF6199288554C8FD44EF09B176CA31E6D7C1BA3D`.
  No main merge or release has occurred.

## Post-prep GUI and strategy-restoration check (23 September 2026)

- The full 103-case Chromium E2E suite passed again after the terminal-fee
  settlement change. The live source GUI remained idle after Coin Prep, with
  zero unresolved operations and no bot start.
- Loaded the saved `pre-fee-live-acceptance` 97-field preset in the live GUI
  and reselected the verified TEST 7 MZ/XCH pair. The saved strategy contains
  45 offers per side, tiered sizing and a 12% preparation headroom. Current
  available MZ is about 780,212, whereas the GUI estimates about 783,289 MZ
  for 45 sell offers and about 1,443,319 MZ for all prepared sell coins. The
  GUI correctly refused Save & Continue with insufficient-token warnings.
  The preset remains saved but was **not** applied; the temporary bounded live
  test settings remain active. No further wallet or offer effect occurred.
- Restoring the exact prior strategy would require more MZ or a deliberate
  resize. Neither was silently imposed. Full app acceptance and the broad
  backend rerun remain open; no main merge or release is justified yet.

## Full-suite confirmed-view fixture repair (23 September 2026)

- The first hermetic full-suite rerun reached 6,878 passed, 104 skipped and
  three failures in `test_coin_prep_confirmed_views.py`. Its synthetic
  `database` module did not implement the newly required terminal fee
  settlement method. The three failures reproduced in isolation (34 passed,
  three failed). A no-fee, no-op settlement response was added to that
  fixture, matching its other synthetic journal operations; the file then
  passed all 37 tests. No production behavior was changed for this repair.
- The subsequent full hermetic run (`COINSET_ENABLED=false`,
  `python -m pytest tests -q -o log_cli=false --tb=short`) completed with
  **6,881 passed, 104 skipped, 422 subtests passed, exit code 0** in
  1,079 seconds. Ruff on `src/catalyst` and `tests` and `git diff --check`
  also passed. This is a backend regression gate, not evidence that the
  live bot/offer lifecycle or all native GUI actions have been exercised.

## Fresh isolated Windows candidate package (23 September 2026)

- From clean tracked source at `37b72b4`, the repository `build.py` entry
  point built into new, isolated `build-fee-acceptance-20260923` and
  `dist-fee-acceptance-20260923` directories; existing live and earlier
  packages were not replaced. The executable is v1.4.0 and has SHA-256
  `2800E255B9C1A42AA75CDECEABC8DE675E6921698C5003DE7DD515B1312BAAF0`.
  The build verified bundled HTML and certifi CA data. PyInstaller emitted
  one `importlib_resources.trees` hidden-import warning without a build
  failure.
- The packaged API smoke passed all eight endpoints, the packaged Sage RPC
  worker smoke passed with synthetic fingerprint, and clean/duplicate/
  persisted/native-safety desktop first-launch smokes passed. These run in
  isolated test data and do not establish live offer behavior.

## Live source bot restart and RED market gate (23 September 2026)

- The previous source server was gracefully stopped with `cancel_offers:false`
  after confirming zero active offers. The current `23b1c85` source server was
  started on port 5000. Sage v0.13.0 was reconnected to TEST 7 mainnet
  fingerprint `736588221`, wallet ID 2, and exact MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
  Read-only balances were 138.472852133099 XCH and 780212.284 MZ. Coin Prep
  remained complete with two confirmed operations, 22,837,112 mojos spent,
  zero held and zero unresolved.
- With the temporary bounded 3-buy/3-sell, 0.1-XCH untiered configuration,
  `/api/bot/start` accepted the request, the trading loop cycled, startup
  Sage synchronization found zero open offers, and runtime safety stayed
  allowed. No buy or sell offer was created. A verified stop returned the bot
  to `running:false`, and a second start returned it to `running:true` with
  no stale offers or new fee holds.
- This is an intentional market-safety block, not a passed offer-lifecycle
  gate. Fresh `/api/market/confidence` evidence was RED/INVALID with
  `out_of_range_depth_excluded`, `insufficient_ask_depth` and
  `single_provider_dependency`. Eligible independent ask depth was only
  0.55 XCH versus 4.012 XCH required. Dexie was valid but Splash's offer set
  was empty/degraded, so there was no trusted bid, ask or midpoint. The bot
  logged `startup_baseline_zero` and `market_confidence_no_trusted_price` and
  correctly held new exposure/requotes at zero. Bootstrap was inactive.
- The live offer creation, visibility, requote, Cancel All under load and
  remake gates therefore remain **unverified**, not passed. No campaign was
  created merely to force exposure, and neither the saved 97-field preset nor
  the installed/live package was overwritten. Main and release remain untouched.

## Live Bootstrap review and frontend inspection (23 September 2026)

- Rechecked the running source app: exact TEST 7 fingerprint 736588221,
  mainnet Sage wallet ID 2 and the MZ asset above; runtime safety ALLOWED,
  market confidence RED and zero active offers. In the real browser, the
  Settings Bootstrap wizard accepted a **review-only** preview with a
  0.000075 XCH/MZ anchor, 0.0000375–0.00015 fixed corridor, one-day expiry,
  1 XCH market budget, 10,000 MZ market budget and 0.001 XCH fee budget. It
  displayed the full 64-character asset ID, a 10% first stage and three offers
  per side. Start Campaign remained disabled without exact-asset confirmation.
  The unsaved mode selection was returned to Follow; `/api/bootstrap/status`
  remained inactive. No new fee consent, campaign or wallet effect occurred.
- The Dashboard's active-settings placeholders initially appeared after a
  browser load, then hydrated from `/api/dashboard` to the correct 3/3,
  45-second, two-sided settings; that is not a reproduced persistent bug.
  However, while `/api/market/confidence` had **no trusted midpoint or
  tradable range**, the Dashboard displayed a numeric 0.00007500 under
  “Trusted Mid Price”. The number comes from an indicative/remembered market
  price, so the current label can overstate its authority. The Offers tab's
  zero-offer empty state also said “Start the bot” while the bot was running
  and market confidence was RED. Both are frontend copy/provenance findings
  requiring a bounded, tested correction; neither is evidence that offer
  creation worked. The P&L tab displayed three Sage-confirmed buy fills and
  zero round trips. `/api/dashboard` gets these through `get_stats(...,
  since=_get_run_history_cutoff())`, where the cutoff is the last explicit
  fresh-run event, not the bot process start; the three fills are therefore
  compatible with the app's persisted run scope rather than a new fill from
  this zero-offer restart.
- Root-cause tracing for the price label found that `/api/market/summary`
  supplies an indicative 0.000075 midpoint from the visible book while
  `/api/market/confidence` has `trusted_midpoint:null` and RED confidence.
  `v4UpdateHeroStrip` and the summary/SSE updaters can render that numeric
  midpoint, but `updateHeroPriceProvenance` leaves the label “Trusted Mid
  Price” whenever there is no active Bootstrap campaign. It also reads
  `confidence.trusted_mid`, while the API field is `trusted_midpoint`. The
  frontend needs a distinct non-tradable/indicative label when confidence
  has no trusted midpoint; this is an identified correction, not yet a fix.

## Empty-wallet Cancel All and fee-ledger restart check (23 September 2026)

- With the exact TEST 7 Sage fingerprint, wallet ID 2 and MZ asset rechecked,
  and zero buy/sell offers confirmed, the bot was stopped. The real
  `/api/offers/cancel_all` empty-wallet path completed with `cancelled:0`,
  `phase:complete`, `error:null` and “No offers found to cancel.” This proves
  the harmless zero-offer path only; it does **not** prove bulk cancellation
  of live offers or cancellation-fee reservations.
- The bot was restarted and reported `running:true`, zero offers, runtime
  safety ALLOWED and no new error logs. `/api/coin-prep/status` still reported
  22,837,112 mojos spent, zero held and zero unresolved fee operations. No
  additional spend or campaign authority was created. The RED market and
  active-offer cancellation/requote/remake gates remain outstanding.

## Secondary-PC readiness gate matrix (23 September 2026)

This matrix is a scope check, not a completion claim. “Passed” refers only to
the exact evidence named; an adjacent gate is not inferred from it.

| Gate | Current evidence | Disposition |
| --- | --- | --- |
| Fee estimator, approval, dispatch and recovery regressions | Hermetic full backend run: 6,881 passed, 104 skipped, 422 subtests passed; browser E2E: 103 passed after terminal settlement | Passed automated regression scope, not live offer scope |
| Fresh Windows artifact | Exact tracked export `d6cec6d` built as v1.4.0; SHA-256 `00BAEE263AB7BE39F37E0B529E08BD0104B5E0AA7AAB89C905BBABD38D051CED`; packaged API, mock Sage RPC and interrupted-publication recovery passed | Latest package native-window launch blocked by tool policy, not passed; earlier native evidence belongs to `37b72b4`. Not installed as the live app |
| Live TEST 7 identity and fee-approved Coin Prep | Sage mainnet fingerprint 736588221, wallet ID 2, exact MZ asset; two confirmed prep operations, 22,837,112 mojos spent, zero held/unresolved after restart | Passed for the bounded untiered test plan |
| Bot start/stop and empty-book recovery | Start, stop, restart and zero-offer Cancel All returned healthy; direct Cancel All while running returned HTTP 409 / `requires_stop:true`; runtime safety remained ALLOWED and fee accounting unchanged | Passed empty-book and running-bot refusal paths only |
| Live MZ/XCH Follow offer lifecycle | RED confidence, 0.55 XCH eligible ask depth vs 4.012 required, one usable provider, no trusted midpoint and zero offers | Blocked by legitimate market safety; creation, publication, fill, requote, active Cancel All and remake **not tested** |
| Bounded Bootstrap alternative | Real GUI preview showed exact asset/corridor/3-per-side bounded plan; no campaign started or wallet effect | Awaiting exact campaign confirmation before live exposure; subsequent Coin Prep would need its own displayed fee approval |
| Original saved strategy and reserves | `pre-fee-live-acceptance` preset preserved; saved 45/45 tiered plan needs more MZ than current spendable balance | Not restored; a different strategy must not be silently substituted |
| Frontend price/empty-offer copy | Three new browser regressions reproduced the defects before the fix; all 106 Chromium E2E tests passed afterwards; live read-only reload verified indicative price and running-RED Offers explanation | Fixed in source frontend; refreshed Windows artifact still required |

No row supports merging main, issuing a release, or telling the secondary PC
that live trading acceptance is complete. The active source bot may continue
monitoring without offers until the market becomes eligible or a deliberately
authorized Bootstrap campaign is used.

The live running-bot cancellation refusal was exercised separately after the
matrix was first written: exact TEST 7 fingerprint 736588221, wallet ID 2,
MZ asset and zero offers were rechecked; POST `/api/offers/cancel_all` returned
HTTP 409 with `requires_stop:true` and the race explanation. The bot stayed
running, the previous zero-offer Cancel All record did not restart, and fee
accounting stayed 22,837,112 mojos spent, zero held/unresolved. This is not
an active-offer cancellation test.

## Live browser cross-check (23 September 2026, ~13:06 BST)

- The open localhost CATalyst tab showed the source build
  `v1.3.21+199.g23b1c85`, running on Sage fingerprint 736588221 with the
  correct MZ/XCH pair. Dashboard market confidence was RED, withdrawal ALL,
  with no tradable range; it showed 0 active offers and 0.55 XCH ask depth
  against 4.012 XCH required per side. Cancel All was disabled while running.
- The Dashboard still labelled the displayed `0.00007500` as “Trusted Mid
  Price” despite RED confidence and no trusted midpoint. Offers still said
  “Start the bot” in the empty state despite the running indicator. These
  independently reproduce the frontend defects in the gate matrix; neither
  was fixed by the inspection.
- P&L showed the historical 3 confirmed buy fills and zero round trips;
  Settings retained the `pre-fee-live-acceptance` 97-field preset and displayed
  runtime safety ALLOWED. The Settings page had no unsaved edit from this
  read-only inspection.
- Market Intel showed Dexie READY, Splash DEGRADED, Spacescan ENABLED, and
  Sage READY. Its “Thin Side BUY” indicator conflicts with the Dashboard's
  eligible ask-depth shortage; inspect whether it intentionally uses raw
  orderbook depth before classifying this as a further defect. It also said
  “Listening enabled; start the bot to receive peer offers” while the bot was
  running; verify the listener's separate status before changing this copy.
- The terminal Playwright CLI browser launch produced no page state and was
  stopped. The existing in-app localhost tab was used for the above observed
  state. No campaign, trade, cancellation or wallet mutation was made.

## Live log and durable-fee follow-up (23 September 2026, ~13:09 BST)

- The visible Logs tab showed the 12:53 bot start, successful Sage sync,
  0/0 wallet offers, clean recovery, prepared coin readiness, and no new
  ERROR entries. The startup `startup_baseline_zero` warning matched the
  current RED/no-trusted-price market; `cancel_all_blocked_live` was the
  deliberately exercised HTTP 409 guard, not an unexpected failure.
- A fresh `/api/status` read reported `running:true`, 23 loops, zero bot
  errors, zero buy/sell offers, wallet ID 2, the exact MZ asset, and runtime
  safety ALLOWED. `/api/coin-prep/status` reported the already-approved
  session complete and stale=false, two confirmed operations, 22,837,112
  mojos spent, zero held, zero unresolved, and dispatch authorization false.
  This is a read-only post-restart consistency check, not a new fee quote or
  Coin Prep run.

## Acceptance goal resumed and frontend corrections (23 September 2026, ~14:00 BST)

- The current task had no active goal, so a new acceptance-readiness goal was
  created. The existing hourly automation was retargeted to this task rather
  than duplicated. The user's existing authorization covers routine bug fixes
  and tests; a further design-approval question was not needed for these
  already-reproduced frontend defects.
- Corrected price provenance to use the API's canonical `trusted_midpoint`.
  A positive finite midpoint is labelled trusted only with GREEN/AMBER
  confidence and no explicit invalid-data state. Otherwise an active valid
  Bootstrap anchor is labelled as such, or the price is labelled indicative
  and display-only. Status, summary and SSE price writes reapply provenance
  so an indicative poll cannot overwrite a trusted/anchor number while
  retaining the wrong label.
- Corrected the Offers empty state to distinguish stopped, running under
  runtime-safety refusal, running RED Follow, and waiting for an eligible
  offer cycle. It renders actual confidence reasons as text and clears the
  obsolete blocker on recovery. No wallet, fee, strategy or trading safety
  logic was changed.
- Test-first evidence: the three added browser regressions failed before
  the production changes. The focused set then passed 4 tests, including
  the existing Bootstrap label regression. Full Chromium E2E subsequently
  passed **106 tests in 88.88 seconds**. A final punctuation-only correction
  is covered by the same focused regression group.
- A read-only reload of the running localhost app verified the fully loaded
  Dashboard showing `0.00007500` as **Indicative Mid Price**, RED confidence,
  zero active offers and zero bot errors. Offers showed the running-RED
  explanation with the observed insufficient-ask-depth/provider reasons,
  rather than asking to start an already-running bot. Browser console
  returned no warning/error entries. Python server version remained
  `1.3.21+199.g23b1c85`; this was a frontend reload, not a backend restart.
- No wallet mutation, new fee approval, Bootstrap campaign or live trade
  was performed in this correction pass. The earlier backend/full-package
  evidence remains scoped to its recorded revision. A fresh package with
  this frontend, the outstanding live ladder/cancel/remake/recovery gates,
  and investigation of the separately noted advisory/listener copy remain
  open. Do not claim overall acceptance readiness or merge main/release.

## Fresh exact-export package verification (23 September 2026, ~14:06 BST)

- Previous goal turn was progress: frontend corrections and tests were
  committed and pushed as `d6cec6d1a96ee7484fe0cd6bf756227dfc45ed36`.
  This continuation exported that exact revision with `git archive` into
  `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/candidate-d6cec6d`
  and used the repository's `python build.py --no-clean` entry point in
  that initially empty export. No existing build, installed package or
  runtime profile was replaced.
- Build exit 0, executable v1.4.0, SHA-256
  `00BAEE263AB7BE39F37E0B529E08BD0104B5E0AA7AAB89C905BBABD38D051CED`.
  The executable is at `candidate-d6cec6d/dist/Catalyst/Catalyst.exe`
  below the above plan workspace. Source and bundled `bot_gui.html` both
  have SHA-256
  `86D9D5EB55248A77B5E7B3C6E84FED824F7ECB6DA034E9739EE01958D1BD8D09`.
  HTML and certifi checks passed. The known PyInstaller warning about
  `importlib_resources.trees` was emitted; it did not fail the build.
  The optional upstream Splash executable is absent from the tracked
  export/package, so these results do not prove bundled Splash operation.
- `python scripts/packaged_api_smoke.py --exe dist/Catalyst/Catalyst.exe
  --timeout 90` passed all eight endpoint contracts with a mock Sage and
  isolated runtime data; the packaged health response reported v1.4.0.
- `python scripts/packaged_sage_rpc_smoke.py --exe
  dist/Catalyst/Catalyst.exe --timeout 90` passed, using synthetic
  fingerprint 123456789 and loopback mock TLS RPC, not the live wallet.
- `python scripts/packaged_upgrade_publication_recovery_smoke.py --exe
  dist/Catalyst/Catalyst.exe --timeout 90` passed. It verified stale-owner
  lease replacement, retryable undispatched claims, and suppression of an
  ambiguous prior publication without retaining stale claim authority.
  This is synthetic interrupted-publication recovery, not live fee or
  live active-offer cancellation evidence.
- The Windows computer-use surface could enumerate windows, but the
  attempted shell launch of this package with a new isolated profile on
  port 5097 was rejected by tool policy before execution. No alternate
  launch route was attempted. Native clean/duplicate/persisted/safety
  window verification for this exact artifact remains **unverified**.
  Existing `scripts/packaged_desktop_first_launch_smoke.py` is available
  for a user-run isolated native check. No new fee budget, campaign,
  wallet transaction, main merge or release was created.
