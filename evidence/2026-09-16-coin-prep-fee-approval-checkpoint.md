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

## Outstanding acceptance gates

Session completion lifecycle, remaining compatibility/prerequisite-family canonical plan preview,
all-path dispatch enforcement, authoritative settlement/recovery integration, GUI confirmation/E2E,
full regression testing, fresh Windows build and live operator-approved fee acceptance
remain incomplete. These tests do not prove the entire feature ready.

The live package was not reloaded or changed, no wallet mutations were performed,
and no release or main merge was made during this checkpoint.
