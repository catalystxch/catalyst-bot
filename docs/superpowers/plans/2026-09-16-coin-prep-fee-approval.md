# Dynamic Coin Prep fee approval implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Execute inline in this task; no new delegation is requested.

**Goal:** Implement the full approved dynamically priced, user-approved, durable Coin Prep fee budget and verify it before any release.

**Architecture:** A small estimation/approval service owns strict quotes and canonical preview contracts. Database functions own approval/reservation/evidence transitions; all prep paths reserve validated final fees at the existing wallet-effect dispatch boundary. HTTP and native bridge share preview/approval enforcement, with a normal-GUI confirmation dialog.

**Tech Stack:** Python, Decimal/integer mojos, Flask, SQLite WAL, Sage unsigned transactions/chia_rs, vanilla JavaScript, pytest and Playwright.

**Spec:** docs/superpowers/specs/2026-09-16-coin-prep-fee-approval-design.md (explicitly approved).

## Global constraints

- Default inclusion target: 300 seconds; never guarantee inclusion or total prep duration.
- Maximum quote age: 60 seconds from original observation; cache hits do not renew it.
- Integer mojos and Decimal only for money/cost; no implicit bool/float coercion into atomic amounts.
- All DB access through database.py; wallet access through wallet.py; server HTML safely escaped.
- Preserve identity, wallet strategy/reserves and all existing mutation/effect safety gates.
- Live identity: mainnet, Sage TEST 7 fingerprint 736588221, wallet ID 2, MZ b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105.
- Genuine explicit fee-budget consent required; unknown effects stay counted; protected cancellation allowance cannot fund prep.
- No main merge or release until full verification supports readiness. Keep all unfinished gates open.

## Task 1: Strict fresh transaction-cost-specific fee quotes

Files: create src/catalyst/fee_estimation.py and tests/test_fee_estimation.py; modify tx_fees.py and its fee regressions only as needed for observation provenance/strict parsing.

Interface: `quote_fee(cost: int, target_seconds: int = 300) -> dict`; `normalize_fee_response(response: dict, *, cost: int, target_seconds: int, source: str, observed_at: int, now: int) -> dict`. Quote result contains available/reason/source/cost/target_seconds/fee_mojos/fee_xch/observed_at/expires_at. Unavailable result never contains a usable fee.

- [x] Write failing tests with literal expected fee amounts. Start with missing/empty estimate producing unavailable, numeric zero producing an available zero, and Decimal fractional mojos rounded upward.

```python
assert normalize_fee_response({'success': True, 'estimates': []}, cost=20_000_000, target_seconds=300, source='coinset', observed_at=100, now=100)['available'] is False
assert normalize_fee_response({'success': True, 'estimates': [0]}, cost=20_000_000, target_seconds=300, source='coinset', observed_at=100, now=100)['fee_mojos'] == 0
```

- [x] Run `python -m pytest tests/test_fee_estimation.py -q`; observe missing-behavior assertion failures before implementation.
- [x] Implement strict response normalization: exact success flag, single result, supplied target/cost match, finite nonnegative decimal value, SQLite integer fee limit, original observation time and 60-second expiry. Invalid requests fail closed without network calls.
- [x] Add and observe failing tests for negative/NaN/Infinity/bool/container/missing values, target/cost mismatch, stale/future observations and integer type boundaries. Implement only the missing checks.
- [x] Expose original observation metadata on provider snapshots/cache hits; reuse configured node/Coinset retrieval while rejecting unavailable/raw malformed data. Provider tests mock transport/clock; quote-boundary tests additionally exercise malformed cached snapshots.
- [x] Run fee tests, batch/direct prep regression tests and Ruff checks, record red/green evidence, commit focused changes (`61fdab4`).

## Task 2: Durable canonical approvals, exact holds and effect evidence

Files: modify src/catalyst/database.py; review/reuse PR #218; extend tests/test_fee_approval_ledger.py and existing schema/authority tests. Add canonical scope/plan helpers to the approval service.

Interfaces: retain create_fee_approval/get_fee_approval/reserve_approved_fee keyword signatures from PR #218; add `record_fee_reservation_outcome(operation_id: str, evidence_id: str) -> dict`, which reads authoritative journal evidence instead of accepting a caller-provided settled boolean. Approval preview identifiers are server-generated.

- [x] Bring reviewed ledger code/tests into the feature branch with exact provenance; do not merge the PR or claim dispatch enforcement.
- [x] Write failing real isolated-SQLite tests: two competing reservations cannot spend the same remainder; older-version fees remain counted; protected cancellation allowance is unavailable to prep; schema corruption blocks use.

```python
approval = database.create_fee_approval(scope_sha256='a'*64, plan_sha256='b'*64, total_fee_mojos=10_000_000_000, cancellation_reserve_mojos=2_000_000_000)
with pytest.raises(ValueError, match='FEE_BUDGET_EXCEEDED'):
    database.reserve_approved_fee(approval_id=approval['approval_id'], scope_sha256='a'*64, plan_sha256='b'*64, operation_id='1'*64, fee_mojos=8_016_000_000, cancellation=False)
```

- [x] Run ledger/schema tests to observe failures, then add canonical validated/migrated schema, indexes and append-only approval semantics. Monetary constraints must reject fractional and boolean fees.
- [x] Test journal-linked reserved/submitted/unknown/confirmed/no-effect transitions against literal held/spent totals. Timeout/process exit cannot release; confirmed fees remain spent; duplicate evidence cannot change totals; replay retrieval cannot authorize redispatch.
- [x] Run ledger, schema, authoritative recovery and reset-preservation tests; commit with checkpoint (296 combined regressions, 36 focused ledger/recovery, Ruff and independent review passed).

## Task 3: Read-only canonical multistage preview and approval APIs

Files: create src/catalyst/coin_prep_fee_approval.py; modify blueprints/coin_prep.py, app_bridge.py and worker planning interfaces; create tests/test_coin_prep_fee_approval.py.

Interfaces: `preview_coin_prep_fees(request_options: dict) -> dict`, `approve_coin_prep_fees(preview_id: str, maximum_fee_mojos: int, cancellation_reserve_mojos: int) -> dict`, `validate_prep_fee_approval(approval_id: str, economic_plan: dict) -> dict`. Add `/api/coin-prep/fee-preview` and `/api/coin-prep/fee-approval` and equivalent bridge methods. No caller scope/hash is trusted.

Verified core substeps (do not imply the runtime collector/routes below are complete):

- [x] Canonical economic contracts bind wallet/network/asset/session or campaign, exact outputs, multiplier, reserves, target and cancellation policy; transient quotes/selected coins are excluded.
- [x] Trusted staged-cost aggregation distinguishes projected counts from exact unsigned costs, preserves source observation age, separates retained fee-coin principal and blocks unavailable/insufficient estimates.
- [x] Immutable preview/consent persistence provides atomic concurrent confirmation, fresh-preview checks, protected and total budget checks, reset/restart preservation and duplicate/conflicting-consent handling.
- [x] Read-only current-economic consent validation rejects generic ledger approvals, changed contracts and superseded versions; quote expiry does not refund holds. Readback explicitly grants no dispatch authority.
- [x] Pure atomic target conversion and exact batch descriptions/actions are shared with the worker. Real unsigned inspection binds executable inputs/additions/fee/CAT2 identity/destinations to the validated summary before exposing exact cost. This helper is not yet a runtime preview endpoint or dispatch guard.
- [x] Read-only wallet snapshot boundary verifies current Sage identity, actual CAT precision/metadata, complete selectable inventory totals and stable bounded pagination, current non-mutating receive address, configuration changes and protected DB coins. Sage v0.13 schemas are represented by complete fixtures. This inventory is not executable-effect proof.
- [x] Shared frozen tier/uniform economics derive exact atomic output denominations, actual generated sell-ladder amounts, reversed buy positions, headroom, one-sided operation, reserves and fee-coin principal. The read-only runtime economic collector uses current verified inventory/configuration and existing Bootstrap authority, accepts client choices only, rechecks identity/configuration/campaign, and grants no dispatch permission.
- [x] Internal next-batch collection retains whole-plan principal and physical/declared reserves, excludes reconciliation-protected funds, classifies exact reusable outputs and obtains a bounded fee/cost-consistent executable unsigned effect. Final economic/inventory rereads, whole-plan fee capacity and original quote expiry are checked before returning available evidence. This is not the full multistage projection, public API, approval or dispatch enforcement.
- [x] Internal future-stage standard-P2/CAT2 projection executes bounded CLVM profiles with disclosed amount/hint/mesh/linked-ring assumptions, refuses unknown puzzles and grants no effect or dispatch authority. Independent linked-CAT counterexample regression and return-distribution comparisons pass. The bounded staged runtime collector now consumes this component; arbitrary wallet extensions remain unsupported.
- [x] Bounded staged runtime preview now connects the exact current unsigned batch, projected future native output/ephemeral profiles, bounded future XCH consolidation coverage and protected individual cancellation cover from frozen replacement targets. All quotes retain original age; final wallet/economic rereads precede persistence. This does not adopt frozen plans in execution or support every compatibility/prerequisite family.
- [x] HTTP/native preview surfaces accept choices only, share ownership protection, expose lossless nested mojo amounts and create no consent, fee reservation, operation journal or dispatch authority. Provider failures and changed contexts remain actionable and fail closed. GUI/worker adoption remains open.
- [x] Runtime confirmation derives current scope/economics and funding from persisted server choices and freshly verified wallet inventory. New consent requires principal and retained fee funding; prior commitments are subtracted atomically. Freshness is sampled after acquiring the database write lock. Duplicate consent returns durable accounting without renewed selectable-input requirements or dispatch permission.
- [x] HTTP/native approval surfaces accept only a server preview ID and exact operator budget/reserve amounts, share mutation protection, reject client economic authority and return lossless decimal-string mojo accounting. Confirmation creates no worker, fee hold or wallet effect. Public preview, GUI confirmation and dispatch adoption remain open.
- [x] Internal stage aggregation can preserve the exact batch's fee/cost-consistent network quote instead of requoting it. It revalidates matching cost/target/source, exact fee and original expiry against a single current observation, sanitizes readback and rejects malformed or expired guidance without silently replacing the matched fee. Full staged collection remains open.
- [x] Initial standalone session ownership is server-generated, immutable and durable across refresh/restart/resets; concurrent collectors reuse one scope. Runtime confirmation rejects unknown or foreign ownership before wallet reads. Campaigns retain their existing scope. The separate fee-schema watermark permits genuine pre-fee upgrades while detecting lost marked fee tables and retaining prior fees.
- [x] Session completion and later-generation transitions require exact current frozen-target inventory plus authoritative terminal fee-journal proof. The immutable completion transition is idempotent, stale/unresolved scopes fail closed, concurrent resolvers mint exactly one next generation, and worker success cannot precede completion.
- [x] Supported direct CAT/XCH and bounded native prerequisite stages derive funding/counts and actual unsigned costs from the verified snapshot. Execution adopts frozen outputs/order, not CLI overrides or later prices. Real worker/CLVM/ledger scenarios cover 61/153 native roots in buy-only and two-sided plans; preview refuses plans exceeding the shared eight-batch limit before initial spending. HTTP/native preview accepts no caller-supplied scope, plan, stage costs or funding. Unsupported compatibility modes remain explicitly fail-closed rather than becoming unpriced fallbacks.

- [x] Write failing API/bridge tests that a preview leaves balances, resets, journals and worker launch untouched, and approval requires a current matching server-owned preview.

```python
result = client.post('/api/coin-prep/fee-preview', json={'coin_multiplier': 1}).get_json()
assert result['target_seconds'] == 300
assert fake_wallet.signatures == []
assert fake_wallet.submissions == []
```

- [x] Observe failures; factor the existing prep economic plan so preview and execution consume identical validated tier/reserve/bootstrap choices. Use exact unsigned cost where current inputs exist, explicitly projected cost/count for future outputs.
- [x] Add tests for fee-coin principal versus actual spend, insufficient funding, stale quotes, changed identity/plan, projected stages and provider outage. Build canonical digests with integer atomic amounts and immutable economic scope.
- [x] Persist preview/approval state so reloads return pending operations and remaining budget rather than duplicate starts. Ensure HTTP mutation protection and desktop guard are shared.
- [x] Run API/bridge/planner/schema regressions; commit verified service/routes. The consolidated approval/preview/dispatch/lifecycle surface passed 481 tests on 22 September 2026.

## Task 4: Enforce approval and fresh exact fees on every prep dispatch

Files: modify coin_prep_worker.py, coin_manager.py, wallet.py, wallet_sage.py and prep trigger/delegation integration; extend dispatch, direct batch, compatibility combine, recovery and bootstrap tests.

Interfaces: focused fee service produces validated final unsigned effect plus exact fee and reservation reference; existing wallet-effect authority stays the final dispatch fence. Unsupported fee-bearing paths return structured pause instead of bypassing approval.

- [x] Internal atomic prep-hold groundwork joins deliberate preview consent/latest version, exact PREPARED journal and bound constructed additions, active undispatched effect claim, quoted final fee and lock-acquired original quote freshness. It enforces the protected preparation allowance, wallet/network/CAT consistency, normalized source and external-fee cohorts, and rejects reservation replay. This primitive returns no dispatch authority and is NOT yet called by worker paths.
- [x] Read-only frozen execution groundwork persists typed server configuration, receive address and exact sizing arguments privately with runtime previews. Confirmation compares this binding against current settings even when output amounts are unchanged. Approved readback reconstructs canonical prepared targets without later price reads or double headroom, refreshes selectable inventory, and checks configuration/identity/address/current session or campaign/latest consent. It grants no dispatch permission and does not prove intermediate completion; actual worker adoption and Bootstrap financial authority remain open.
- [x] Internal consent-bound exact pricing-to-hold service consumes frozen targets, derives fresh executable cost/network guidance and checks current remaining preparation allowance without borrowing cancellation cover. Its final boundary re-inspects the bundle, matches deterministic operation/journal/constructed additions, validates all current inventory while allowing only proven own-claim protection, and calls the exact atomic hold. A newly reserved selected root is denied inside the write transaction. These helpers never sign/submit and are not yet invoked by worker dispatch paths.
- [x] Adopt frozen approved economics/configuration in the supported Sage tier dispatch, connect actual unsigned cost/fixed-point pricing and the atomic hold to its direct and bounded-prerequisite transactions, and bind restart recovery/accounting. Unsupported compatibility modes pause without entering legacy manual-fee mutations.

- [x] Write failing direct and compatibility-path tests: missing approval and exceeded budget produce no signing/submission; configured manual fee cannot bypass; supported bounded XCH prerequisites use actual cost-specific network pricing while unsupported legacy combines fail closed.

```python
worker.run()
assert status.reason == 'FEE_APPROVAL_REQUIRED'
assert fake_wallet.signatures == []
assert fake_wallet.submissions == []
```

- [x] Run each supported dispatch-family test red before implementing its guard. Build/validate unsigned effects and re-evaluate fee/cost with bounded fixed-point retries, then atomically reserve exact final fee before signing.
- [x] Test price increase within allowance proceeds, beyond allowance pauses, provider failure pauses, fee-induced output/cost changes converge or stop, approval scope changes stop, and ordinary expected intermediate outputs preserve economic approval.
- [x] Test crashes before signing and after submission, authoritative settlement/no-effect, duplicate recovery, automatic bootstrap prep and cancellation usage. Protected Sage Cancel All now prices and seals the exact unsigned transaction, atomically holds only its approved cancellation allowance, settles once after authoritative cohort proof, releases on authoritative no-effect, and recovers unsettled outcomes after restart. Single-offer and genuine zero-fee cancellations are covered without inventing a fee input.
- [x] Run all affected authority/prep/recovery/fee tests and checkpoint exact supported-path coverage; commit only verified controls. The final cancellation/API/native/browser gate passed 216 tests on 22 September 2026; the broader authority run passed 1,706 tests, with two cold Windows diagnostics startups timing out before passing individually once Defender's new SQLite snapshots were warm.

## Task 5: Normal GUI confirmation, pause/reload recovery and E2E

Files: modify bot_gui.html; create tests/e2e/test_coin_prep_fee_approval.py; extend frontend/bridge response tests.

- [x] Write failing browser tests through real GUI buttons with mocked transport/wallet effects. Coin Prep opens read-only estimate, not immediate signing; Cancel has no mutations; explicit confirm sends displayed budget only once.

```python
page.get_by_role('button', name='Coin Prep', exact=True).click()
expect(page.get_by_role('dialog')).to_contain_text('Estimated fees')
page.get_by_role('button', name='Cancel', exact=True).click()
assert fake_wallet.submissions == []
```

- [x] Observe failure and implement escaped/textContent rendering, source/age/projected labels, editable cap, protected cancellation amount, funding errors and five-minute estimate disclaimer.
- [x] Add red/green tests for stale refresh, changing costs, outage, budget increase prompt, duplicate clicks, desktop bridge equivalence, status updates and reload/resume of pending approvals. Approval refresh cannot launch prep or clear durable evidence.
- [x] Run E2E plus relevant frontend/API tests; commit verified UI.

## Task 6: Regression, fresh package and live acceptance

Files: build.py/package manifests only if required; evidence/2026-09-16-coin-prep-fee-approval-checkpoint.md for gates and receipts.

- [x] Run full relevant pytest suites, full suite where practical, Ruff and tracked-secret checks; inspect failures rather than narrowing scope. Final frozen-app suite: 6,981 passed, 157 skipped, 422 subtests in 1,037.25s (23 September, session 4916); broad Chromium 156 passed. Eight later test-harness cases are verified separately in the 14-test helper run. Ruff, staged-secret and diff checks passed. Exact native/live gates remain below.
- [x] Build fresh Windows package with the repository build entry point and verify exact built commit/resources. Exercise HTTP and native GUI in isolated test data first. Candidate build/API/package receipts are in `evidence/2026-09-23-review-fix-acceptance.md`; the operator-reported clean/duplicate/relaunch/safety native launch pass is recorded in `evidence/2026-09-24-native-operator-result.md`. This does not establish live fee or trading acceptance.
- [x] Verify live identity and current configuration, show a fresh preview through the GUI and obtain genuine operator fee-budget confirmation before spending. Execute prep and read back signed fee/effect, peer acceptance and chain confirmation evidence; verify pause/restart recovery and no double accounting. Completed on 24 September 2026; exact receipts are in `evidence/2026-09-24-live-test7-acceptance.md`.
- [x] Audit every spec requirement against source/tests/UI/build/live receipts, recording blocked gates as incomplete. The requirement matrix is in `evidence/2026-09-24-live-test7-acceptance.md`; the separate live create/requote/cancel/remake trading gate remains incomplete. The registered broader goal is blocked, not complete, and no release/main merge is authorized.

## Current checkpoint

**25 September 2026, 21:59 UTC:** primary commit61ad703 incorporates the shared
repairs and later latest-campaign-approval status fix. Raw final backend log
confirms **7042 passed,165 skipped,422 subtests**; current471-file manifest
`C9DCF5F653FE314C0DE10C0653E41F9D036D253D130AA94AF73178AA80FF8A7A`.
Final EXE `5B3D259964A8537D214E150F853B19B99ED6297D96A00B247F1E97BBFA07F6D4`
matches all131 project modules+entrypoint/HTML. All198 files in the primary's
local ZIP match the bundle. Primary records164 Chromium/build/package/native
smokes; those console-only receipts were not independently rerun.

Protected live cleanup used priorEXE55C749, not5B3D. Observer read-only durable
proof confirms new3+3 terminal cohorts, fees90369+311977=402346mojos, original
cap/overrun preserved. LatestV3 consent1746988850/spent1736965715/held0/remaining
10023135/stalefalse/unresolved0 agrees with new5B3D real-profile restart API;
botstopped,0openoffers/locks/blockers. Primary records displayed budget and
separate cancellation confirmation. No new observer wallet action or consent.
These close protected cleanup/settlement/restart gates with exact attribution.

Live automatic requote/remaining market-publication acceptance is still open.
Current confidence refuses creation/requote but was derived13:36:39UTC and is
expired, so do not call this fresh evidence of unavoidable market insufficiency.
Review Catalyst work (3) retains live ownership and was asked to obtain fresh
attributable confidence before further classification/actions. See latest
observer checkpoint for raw log hashes, cohort IDs and receipt boundaries.
No duplicate full suite/build, strategy activation, main merge, release or goal
completion. Earlier pending/provenance/native/live statuses below are historical
where this update explicitly supplies newer evidence.

**25 September 2026, 20:56 UTC:** collected the repaired-source full backend:
**7041 passed, 165 skipped, 422 subtests passed in 1421.36s**, finished 18:30:07
UTC. Log SHA-256 `BF0E21FA5534E7285820C3B51FC272B5A8E0F2E561581E47A31DE13418CC1645`.
Session56922 is expired and PID35184 absent; the passing persisted summary is
verified, not a newly recovered exit code. No observer verification job remains
active. Current source and isolated candidate still match the 471-file manifest
`3097114C6243E617BFD1D18654146423C7608A70CF4513D4D5188DA1F0D9314E`; isolated
EXE736FAA remains unchanged. No duplicate full suite/build or production edit.

Shared EXE now hashes to
`55C749B5BC98B53F4EFBF1DE3A1C2DD15DEC804C6F1B4B0B4D238DFFD2591EEC`.
Independent read-only inspection matches all131 embedded project modules,
entrypoint and HTML to tested source. This does not transfer isolated736FAA
package probes or older768CDE4B native receipts to55C749. Review Catalyst work
(3) is active, retains UI/native/live ownership, and was asked for exact new
build/native/live evidence. The bounded legacy-accounting regression gate is
closed; intended-artifact/native and post-fix live recovery/requote gates remain
open. Original overrun/cap and user data preserved. No readiness/main/release or
goal-completion claim. The following 18:12/18:08 job statuses are historical.

**18:12 UTC package follow-up:** isolated build63634 completed exit0. Candidate
EXE SHA-256 `736FAA2E01C27C175DAB7FC395AA394750689976356701F15CA6F21409AC0906`
passed API/mock-Sage/upgrade-publication probes and all131 embedded project
module comparisons plus entrypoint. Candidate/worktree471-file manifests both
match the frozen value below. Only full backend56922/PID35184 remains active;
native/live acceptance remains open. Existing shared package untouched.

**25 September 2026, 18:08 UTC update:** the legacy unresolved-fee gap now has
a bounded test-first repair and **59 focused passing tests** (26 new cases),
including HTTP/native restart refusal, authoritative no-effect/retry/terminal
transitions and protected/legacy deduplication. Further REDs for mixed SQLite
snapshots and confirmation-before-ledger-settlement double counting were fixed.
Full backend **56922/PID35184** is pending on frozen 471-file manifest
`3097114C6243E617BFD1D18654146423C7608A70CF4513D4D5188DA1F0D9314E`;
isolated Windows build **63634** is pending from
`.superpowers/candidate-legacy-20260925-1806`. Collect both before duplicates or
source changes. The former EXE943B0D is preserved but does not contain these
repairs. This task temporarily owns the bounded offline accounting repair;
Review Catalyst work (3) retains UI/native/live ownership. See the latest
observer checkpoint for exact logs/hashes and intermediate failures. No wallet
spend, cap change, native/live relabelling, merge, release or completion.

The following 16:56 checkpoint is historical and superseded only where the
18:08 update explicitly supplies newer evidence:

**25 September 2026, 16:56 UTC:** release/secondary-PC readiness is still open.
The historical campaign cancellation overrun and current repair verification
are recorded in `evidence/2026-09-25-campaign-fee-overrun-observer.md`.
Fresh campaign/bypass/recovery verification passes 16 tests, including both
composed-stop and canonical-context refusal cases. Focused browser verification
passes 32 tests; complete Chromium E2E passes 164 tests. Current EXE
`943B0D54FC9DF01D8005C35A0946D7D41EB060D3511ABD63FC2A7913F7167D6D`
independently passes API/mock-Sage/upgrade-recovery probes. The full backend run
was collected: 7011 passes, 165 skips, 422 subtests, two failures and two setup
errors, all in stopped-fee-renewal import initialization. A minimal cross-file
reproduction preceded the test-only correction; same-order 7 tests and the
16-test campaign/recovery group now pass. Replacement full run completed:
session 88147, **7015 passed, 165 skipped, 422 subtests**, exit 0; log
`observer-full-backend-20260925-1554.log` in the SDD directory. The frozen
470-file manifest remained unchanged. No observer test job remains active.
A subsequent real-database legacy-unresolved cancellation regression is RED:
2 failures (submitted/unknown fees reported as zero held), with 2 otherwise
identical protected-reservation controls passing. Separate journal safety
blockers remain; this is not a proven new dispatch bypass. The new cases are
not included in the prior green full-run count. Earlier evidence includes
196 ledger/cancellation/hold/journal tests, 27 Chromium fee-flow tests, and
isolated API/mock Sage/upgrade-recovery probes against EXE SHA-256
`6C3B69255833CDC5D9B86318FC4E71C928EA9956F920A39D249D1F0855D675B3`.
The owner's earlier 7011 full backend /159 Chromium/native receipt names
`768CDE4B...`; do not conflate it with current 943B0D verification. Exact final
source/build/native provenance still needs to be tied to the handoff artifact.
Read-only comparison now matches all 131 embedded project PYZ modules plus the
desktop entrypoint to current source; this is not native/live acceptance.
Current source is base `f07af36` plus shared repair WIP, not that commit alone.

- [x] Original automatic-policy-stop regressions now pass and are integrated
  into `tests/test_bootstrap_stopped_fee_renewal.py`. This closes that isolated
  failure, not every composed stop/recovery or live acceptance gate.
- [x] Explicit stop following automatic policy stop now passes the prior RED
  regression. Added repeated-stop changed reserve/identity/address refusals
  also pass; new cleanup review does not grant ordinary prep authority.
- [x] Cancellation-only fee review now passes the prior RED browser case.
  Additional real-button tests cover approval refusal, Keep Offers, and a second
  cancellation confirmation through mocked async completion, retaining the
  approved ID and never launching prep/history reset. No live wallet is used.
- [x] Collect and diagnose the failed full suite; reproduce and fix its
  test-isolation import errors without changing financial assertions/guards.
- [x] Collect the replacement frozen-source full suite: 7015 passes, no
  failures/errors, without weakening guards.
- [x] Fix and verify the newly reproduced legacy submitted/unknown campaign
  cancellation fee-accounting gap, including once-only cohort/reservation
  accounting and authoritative terminal transitions; 59 focused and 7041 full
  backend passes on the matching 471-file source/test manifest.
- [x] Finalize exact source/package provenance without omitting the new shared
  test fixture or conflating historical package/native receipts:61ad703 source,
  EXE5B3D,198matching ZIP files; primary-recorded exact native smokes, observer
  verified restart/API/code attribution. Live mutation remains attributed55C.
- [x] Complete post-fix live campaign cleanup through genuine displayed
  recovery consent, exact cap-enforced dispatch, authoritative settlement and
  restart accounting; preserve the original 0.001 XCH cap and evidenced overrun.
  New402346mojos fit explicitV3 cumulative1746988850 cap; held/unresolved0.
- [ ] Finish remaining live requote/recovery/market/publication acceptance.

No further fee-bearing live tests until the repaired accounting and dispatch
controls are verified for the intended artifact and actual new displayed fee
consent is recorded. Review Catalyst work (3) owns the production repair and
live session. Keep the unaffordable saved strategy intact. Earlier checked
items below/above describe historical fee-feature evidence, not clearance of
these newly discovered acceptance gates. No merge, release or goal completion.

Prior combined-candidate verification is recorded in
`evidence/2026-09-24-combined-candidate-verification.md`: frozen source `088d9d6`,
fresh Windows build, 156 Chromium passes, 6,999 final worktree passes with
157 skips and 422 subtests, corrected isolated package probes, and a recorded
same-executable native acceptance receipt. The 20:25 UTC heartbeat rechecked
all 198 bundled file hashes/sizes. These newer results supersede the earlier
test/build counts above without relabelling older live TEST 7 receipts as
new-build wallet tests. No test job remains active. The combined app reopened
on 25 September with intact fee accounting; see
`evidence/2026-09-25-combined-runtime-reopened.md`. The broader live offer
lifecycle remains incomplete, pending an operator-run live cycle and fresh
market authority; no safety gate may be bypassed.

- [x] User approved written specification; new goal created and existing hourly loop refreshed.
- [x] Existing isolated branch codex/coin-prep-fee-approval verified; untracked user/build artifacts preserved.
- [x] Baseline fee/planner/direct batch tests: 37 passed on 16 September 2026.
- [x] Task 1 strict estimation foundation verified and committed.
- [x] Task 2 database foundation and canonical scope/plan helper core verified; later tasks integrated and verified live fee accounting.
- [x] Task 3 core, bounded staged runtime preview, HTTP/native preview/approval, durable reload accounting and full standalone session lifecycle are implemented and jointly regression-tested. Task 5 is complete.
- [x] Task 4 supported Sage tier execution, restart-safe authoritative accounting, final Bootstrap campaign authority and protected Sage cancellation consumption are implemented. Unsupported compatibility modes pause safely. Task 6 fee-feature evidence is recorded; the broader live trading lifecycle remains incomplete as documented above.
