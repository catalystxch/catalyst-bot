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
- [x] Runtime confirmation derives current scope/economics and funding from persisted server choices and freshly verified wallet inventory. New consent requires principal and retained fee funding; prior commitments are subtracted atomically. Freshness is sampled after acquiring the database write lock. Duplicate consent returns durable accounting without renewed selectable-input requirements or dispatch permission.
- [x] HTTP/native approval surfaces accept only a server preview ID and exact operator budget/reserve amounts, share mutation protection, reject client economic authority and return lossless decimal-string mojo accounting. Confirmation creates no worker, fee hold or wallet effect. Public preview, GUI confirmation and dispatch adoption remain open.
- [x] Internal stage aggregation can preserve the exact batch's fee/cost-consistent network quote instead of requoting it. It revalidates matching cost/target/source, exact fee and original expiry against a single current observation, sanitizes readback and rejects malformed or expired guidance without silently replacing the matched fee. Full staged collection remains open.
- [x] Initial standalone session ownership is server-generated, immutable and durable across refresh/restart/resets; concurrent collectors reuse one scope. Runtime confirmation rejects unknown or foreign ownership before wallet reads. Campaigns retain their existing scope. The separate fee-schema watermark permits genuine pre-fee upgrades while detecting lost marked fee tables and retaining prior fees.
- [ ] Session completion and later-generation transitions require authoritative journal proof and remain unimplemented; currently all later standalone generations fail closed. This ownership groundwork is not a completed session lifecycle or public preview collector.
- [ ] Runtime staged funding/counts and actual unsigned costs must still be derived from this snapshot. No HTTP/native endpoint may accept caller-supplied scope, plan, stage costs or funding. Execution must adopt the frozen outputs and their ordering, rather than independently regenerating them from CLI overrides or a later market price.

- [ ] Write failing API/bridge tests that a preview leaves balances, resets, journals and worker launch untouched, and approval requires a current matching server-owned preview.

```python
result = client.post('/api/coin-prep/fee-preview', json={'coin_multiplier': 1}).get_json()
assert result['target_seconds'] == 300
assert fake_wallet.signatures == []
assert fake_wallet.submissions == []
```

- [ ] Observe failures; factor the existing prep economic plan so preview and execution consume identical validated tier/reserve/bootstrap choices. Use exact unsigned cost where current inputs exist, explicitly projected cost/count for future outputs.
- [ ] Add tests for fee-coin principal versus actual spend, insufficient funding, stale quotes, changed identity/plan, projected stages and provider outage. Build canonical digests with integer atomic amounts and immutable economic scope.
- [ ] Persist preview/approval state so reloads return pending operations and remaining budget rather than duplicate starts. Ensure HTTP mutation protection and desktop guard are shared.
- [ ] Run API/bridge/planner/schema regressions; commit verified service/routes.

## Task 4: Enforce approval and fresh exact fees on every prep dispatch

Files: modify coin_prep_worker.py, coin_manager.py, wallet.py, wallet_sage.py and prep trigger/delegation integration; extend dispatch, direct batch, compatibility combine, recovery and bootstrap tests.

Interfaces: focused fee service produces validated final unsigned effect plus exact fee and reservation reference; existing wallet-effect authority stays the final dispatch fence. Unsupported fee-bearing paths return structured pause instead of bypassing approval.

- [ ] Write failing direct and compatibility-path tests: missing approval and exceeded budget produce no signing/submission; configured manual fee cannot bypass; XCH combines use actual cost-specific network pricing.

```python
worker.run()
assert status.reason == 'FEE_APPROVAL_REQUIRED'
assert fake_wallet.signatures == []
assert fake_wallet.submissions == []
```

- [ ] Run each dispatch-family test red before implementing its guard. Build/validate unsigned effects and re-evaluate fee/cost with bounded fixed-point retries, then atomically reserve exact final fee before signing.
- [ ] Test price increase within allowance proceeds, beyond allowance pauses, provider failure pauses, fee-induced output/cost changes converge or stop, approval scope changes stop, and ordinary expected intermediate outputs preserve economic approval.
- [ ] Test crashes before signing and after submission, authoritative settlement/no-effect, duplicate recovery, automatic bootstrap prep and cancellation usage. Never treat reservation replay as a fresh spending permit.
- [ ] Run all affected authority/prep/recovery/fee tests and checkpoint exact supported-path coverage; commit only verified controls.

## Task 5: Normal GUI confirmation, pause/reload recovery and E2E

Files: modify bot_gui.html; create tests/e2e/test_coin_prep_fee_approval.py; extend frontend/bridge response tests.

- [ ] Write failing browser tests through real GUI buttons with mocked transport/wallet effects. Coin Prep opens read-only estimate, not immediate signing; Cancel has no mutations; explicit confirm sends displayed budget only once.

```python
page.get_by_role('button', name='Coin Prep', exact=True).click()
expect(page.get_by_role('dialog')).to_contain_text('Estimated fees')
page.get_by_role('button', name='Cancel', exact=True).click()
assert fake_wallet.submissions == []
```

- [ ] Observe failure and implement escaped/textContent rendering, source/age/projected labels, editable cap, protected cancellation amount, funding errors and five-minute estimate disclaimer.
- [ ] Add red/green tests for stale refresh, changing costs, outage, budget increase prompt, duplicate clicks, desktop bridge equivalence, status updates and reload/resume of pending approvals. Approval refresh cannot launch prep or clear durable evidence.
- [ ] Run E2E plus relevant frontend/API tests; commit verified UI.

## Task 6: Regression, fresh package and live acceptance

Files: build.py/package manifests only if required; evidence/2026-09-16-coin-prep-fee-approval-checkpoint.md for gates and receipts.

- [ ] Run full relevant pytest suites, full suite where practical, Ruff and tracked-secret checks; inspect failures rather than narrowing scope.
- [ ] Build fresh Windows package with the repository build entry point and verify exact built commit/resources. Exercise HTTP and native GUI in isolated test data first.
- [ ] Verify live identity and current configuration, show a fresh preview through the GUI and obtain genuine operator fee-budget confirmation before spending. Execute prep and read back signed fee/effect, peer acceptance and chain confirmation evidence; verify pause/restart recovery and no double accounting.
- [ ] Audit every spec requirement against source/tests/UI/build/live receipts, recording blocked gates as incomplete. Leave goal active until all requirements are proven. No automatic release/main merge.

## Current checkpoint

- [x] User approved written specification; new goal created and existing hourly loop refreshed.
- [x] Existing isolated branch codex/coin-prep-fee-approval verified; untracked user/build artifacts preserved.
- [x] Baseline fee/planner/direct batch tests: 37 passed on 16 September 2026.
- [x] Task 1 strict estimation foundation verified and committed.
- [x] Task 2 database foundation and canonical scope/plan helper core verified; live integration is still outstanding.
- [ ] Task 3 core, read-only next-batch runtime collection and HTTP/native approval are partially implemented; full multistage projection and HTTP/native preview integration remain open. Tasks 4–6 remain open.
