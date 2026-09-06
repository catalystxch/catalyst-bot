# Direct-batch Coin Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Sage's routine pool-and-split chain with deterministic, validated final-output batches while retaining exact-input admission and authoritative confirmation.

**Architecture:** A pure planner computes one bounded transaction from a fresh selectable-coin snapshot and an immutable target list. The Sage adapter first constructs and validates an unsigned effect; the worker then reuses the existing durable PREPARED/dispatch/unknown-effect protocol to submit and authoritatively reconcile one batch before replanning.

**Tech Stack:** Python 3.12, Flask status bridge, SQLite durability layer, Sage JSON RPC, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-04-direct-batch-coin-prep-design.md`

## Global Constraints

- Sage only; Chia and non-tiered workflows retain their existing implementation.
- Exact integer mojos and `Decimal` conversions only.
- Maximum 50 asset inputs, one separate CAT fee input, and 128 outputs including change.
- Preserve selected reserves, headroom, configured fee, dedicated fee-coin inventory and risk settings.
- Never select offer-locked, pending, operation-reserved or otherwise nonselectable coins.
- A submitted or ambiguous effect blocks every later batch until authoritative reconciliation.
- Completion requires confirmed selectable output identities and persisted designations.
- No bot start, offer cancellation, data reset, release or website change is part of this plan.

---

### Task 1: Deterministic pure planner

**Files:**
- Create: `src/catalyst/coin_prep_batch_plan.py`
- Create: `tests/test_coin_prep_batch_plan.py`

**Interfaces:**
- Consumes: `plan_batch(snapshot: CoinSnapshot, targets: tuple[TargetOutput, ...], constraints: BatchConstraints) -> BatchPlan | BatchRefusal`
- Produces: frozen `SelectableCoin`, `CoinSnapshot`, `TargetOutput`, `BatchConstraints`, `PlannedOutput`, `BatchPlan`, and `BatchRefusal` dataclasses. `BatchPlan` contains exact `asset_source_ids`, `fee_source_id`, outputs, change, reused target ordinals, and fee.

- [x] **Step 1: Write failing conservation and selection tests**

```python
def test_plan_is_deterministic_and_conserves_every_asset():
    request = compact_two_asset_request()
    first = plan_batch(**request)
    second = plan_batch(**request)
    assert first == second
    assert sum(first.input_mojos("xch")) == sum(first.output_mojos("xch")) + first.fee_mojos
    assert sum(first.input_mojos("cat")) == sum(first.output_mojos("cat"))

def test_ready_targets_reuse_distinct_coin_ids_without_a_transaction():
    result = plan_batch(**already_ready_request())
    assert result.transaction_required is False
    assert len(set(result.reused_coin_ids)) == len(result.reused_coin_ids)
```

- [x] **Step 2: Run `python -m pytest tests/test_coin_prep_batch_plan.py -q` and observe missing-module failure.**

- [x] **Step 3: Implement frozen validated input/output dataclasses and `plan_batch`.**

```python
def plan_batch(snapshot, targets, constraints):
    validated = _validate_request(snapshot, targets, constraints)
    reused, missing = _assign_exact_reuse(validated)
    if not missing:
        return BatchPlan.no_transaction(reused)
    selected = _select_largest_sources(validated, missing)
    return _pack_conserved_outputs(validated, reused, missing, selected)
```

Reject duplicate IDs, nonpositive amounts, repeated target ordinals, a protected/nonselectable input, reserve erosion, fee-coin reuse, more than 50 asset inputs, or more than 128 outputs. Stable ordering is `(asset, purpose, tier_rank, amount_mojos, ordinal)` for targets and `(-amount_mojos, coin_id)` for sources.

- [x] **Step 4: Add red-green tests for partial reuse, equal output amounts, one-sided prep, CAT external-fee change, reserve floor, input cap and output cap.**
- [x] **Step 5: Run `python -m pytest tests/test_coin_prep_batch_plan.py -q`; require zero failures.**
- [ ] **Step 6: Commit planner and tests as `feat: add deterministic coin prep batch planner`.**

### Task 2: Unsigned Sage effect validation

**Files:**
- Modify: `src/catalyst/wallet_sage.py`
- Modify: `src/catalyst/wallet.py`
- Create: `tests/test_wallet_sage_unsigned_effect.py`

**Interfaces:**
- Consumes: `build_transaction_rpc(selected_coin_ids, actions, identity_recheck=None) -> dict` and `validate_unsigned_effect(result, contract) -> dict`
- Produces: `submit_built_transaction_rpc(validated_result, identity_recheck=None) -> dict`; facade methods with the same names.

- [x] **Step 1: Write a failing test that building calls `create_transaction` with `auto_submit=False` and never calls signing or submission.**
- [x] **Step 2: Write failing validators for an extra removal, missing source, wrong asset, wrong destination, missing change, changed fee, coalesced equal outputs and duplicate output IDs.**

```python
effect = validate_unsigned_effect(unsigned_response(), exact_contract())
assert effect == {
    "success": True,
    "source_coin_ids": exact_contract()["source_coin_ids"],
    "created_coin_ids": expected_distinct_ids(),
}
```

- [x] **Step 3: Run `python -m pytest tests/test_wallet_sage_unsigned_effect.py -q` and observe failures before adding production entry points.**
- [x] **Step 4: Split the existing `create_transaction_rpc` build and submit stages. Parse the unsigned Sage response through Sage's structured removals/additions fields; if those fields are absent, return `UNSIGNED_EFFECT_NOT_INSPECTABLE` without signing. Exclude only explicitly identified internal ephemeral spends from the external-removal comparison.**
- [x] **Step 5: Make `submit_built_transaction_rpc` accept only the validator-produced sealed result, recheck identity before signing and again before submission, and preserve the current unknown-outcome classification.**
- [x] **Step 6: Add both methods to wallet facade allowlists and run `python -m pytest tests/test_wallet_sage_unsigned_effect.py tests/test_wallet_facade.py -q`.**
- [ ] **Step 7: Commit as `feat: validate Sage coin prep effects before signing`.**

### Task 3: Durable batch contract and recovery

**Files:**
- Modify: `src/catalyst/database.py`
- Modify: `src/catalyst/replacement_capacity.py`
- Modify: `tests/test_coin_prep_operation_journal.py`

**Interfaces:**
- Consumes: `prepare_coin_prep_operation(..., target_contract=contract_v2)`.
- Produces: version-2 target contracts with planned output IDs bound after unsigned validation; legacy version-1 rows remain readable.

- [ ] **Step 1: Add failing migration/round-trip tests for `contract_version=2`, `constructed_output_ids`, external fee output and immutable plan/config hash.**
- [ ] **Step 2: Add failing recovery tests at PREPARED, DISPATCHING and SUBMITTED_UNKNOWN boundaries; only exact source disappearance plus exact distinct output appearance may complete.**
- [ ] **Step 3: Implement an additive SQLite migration and canonical version-2 serialization. Reject rebinding output IDs or a different plan hash.**
- [ ] **Step 4: Retain the version-1 recovery parser unchanged and route version 2 through exact multi-output validation.**
- [ ] **Step 5: Run `python -m pytest tests/test_coin_prep_operation_journal.py tests/test_replacement_capacity.py -q`.**
- [ ] **Step 6: Commit as `feat: persist recoverable coin prep batch contracts`.**

### Task 4: Sage worker integration

**Files:**
- Modify: `src/catalyst/coin_prep_worker.py`
- Modify: `src/catalyst/mutation_gate.py`
- Modify: `tests/test_coin_prep_worker.py`
- Modify: `tests/test_mutation_gate.py`

**Interfaces:**
- Consumes: planner, validated Sage adapter and version-2 journal from Tasks 1–3.
- Produces: `CoinPrepWorker._run_direct_batch_prep() -> bool | None`, where `True` is verified completion, `False` is a typed refusal/error, and `None` means the compatibility path is allowed before any effect.

- [ ] **Step 1: Add a failing observed-run fixture with 126 XCH targets (including 50 fee coins) and 76 CAT targets; assert at most two submissions and confirmation rounds, no pool creation and no tier split.**
- [ ] **Step 2: Add failing tests for identity change before signing, cancel before next batch, lost submit response, restart recovery, missing external fee coin and a confirmed partial run that replans only deficits.**
- [ ] **Step 3: Add the exact operation `coin_prep.create_final_batch` to the worker and mutation-gate allowlists. Bind asset sources and the external fee source as separate cohorts.**
- [ ] **Step 4: Implement the loop: fresh identity/snapshot, plan, exact claim, unsigned build, validate, persist constructed IDs, identity recheck, dispatch, submit, authoritative wait, designation persist, refresh and replan.**
- [ ] **Step 5: Return `None` only for an unsigned `UNSIGNED_EFFECT_NOT_INSPECTABLE` response or a planner prerequisite refusal before dispatch. Propagate submitted uncertainty as `CoinPrepAuthorityUnresolved`; never enter compatibility mode from that state.**
- [ ] **Step 6: Call direct mode before routine consolidation only when `is_sage and tier_enabled`. Preserve the current path for every other mode.**
- [ ] **Step 7: Run `python -m pytest tests/test_coin_prep_worker.py tests/test_mutation_gate.py tests/test_plan_04_06_coin_prep_endpoints.py -q`.**
- [ ] **Step 8: Commit as `feat: prepare Sage tier coins in final-output batches`.**

### Task 5: Truthful progress and cancellation/recovery UI

**Files:**
- Modify: `src/catalyst/coin_prep_worker.py`
- Modify: `src/catalyst/blueprints/bot.py`
- Modify: `src/catalyst/app_bridge.py`
- Modify: `bot_gui.html`
- Modify: `tests/test_plan_04_06_coin_prep_endpoints.py`
- Modify: `tests/e2e/test_smoke.py`

**Interfaces:**
- Produces additive status fields `execution_mode`, `reused`, `missing`, `batch_current`, `batch_confirmed`, `planned_fee_mojos`, `paid_fee_mojos`, `confirmation_elapsed_seconds`, and `compatibility_reason`.

- [ ] **Step 1: Write failing API/browser tests showing `building`, `submitting`, `awaiting_confirmation`, `recovery_required`, `compatibility` and `complete`, with success withheld until designation persistence.**
- [ ] **Step 2: Add fields to `CoinPrepStatus.to_dict()` and preserve every existing response key.**
- [ ] **Step 3: Render values with `textContent`; escape any reason string before markup and show elapsed confirmation time separately from total runtime.**
- [ ] **Step 4: Verify cancellation stops only future batches and leaves the in-flight batch visibly reconciling.**
- [ ] **Step 5: Run `python -m pytest tests/test_plan_04_06_coin_prep_endpoints.py tests/e2e/test_smoke.py --e2e -q`.**
- [ ] **Step 6: Commit as `feat: report direct coin prep progress truthfully`.**

### Task 6: Regression, package and live acceptance gates

**Files:**
- Modify: `docs/superpowers/specs/2026-09-04-direct-batch-coin-prep-design.md` only to record measured evidence.

**Interfaces:**
- Consumes the completed Tasks 1–5.
- Produces a reviewed feature branch; no release artifact is published by this task.

- [ ] **Step 1: Run targeted wallet, Coin Prep lifecycle, crash recovery, mutation-gate, bridge and browser tests.**
- [ ] **Step 2: Run `python -m pytest -q`, `python -m ruff check src tests`, `python -m bandit -r src/catalyst -q`, and `python -m vulture src/catalyst --min-confidence 90`. Record exact results.**
- [ ] **Step 3: Build into an unused verification directory so the running installed build is not overwritten. Inspect the packaged GUI hash and run the mock direct-mode fixture from packaged imports.**
- [ ] **Step 4: Review the diff for source-cohort conservation, reserve/fee invariants, unknown-effect handling, secrets and unrelated files.**
- [ ] **Step 5: After explicit live-test direction, use a changed requirement that genuinely needs new outputs, verify wallet/network/asset/config immediately before submission, and measure wallet mutations, confirmation rounds and total duration.**
- [ ] **Step 6: Record actual evidence, open a pull request from the feature branch and request review. Do not merge or release until live results and review pass.**

## Self-review

- Spec coverage: planner, caps, reserves, fee source/change, unsigned validation, repeated equal outputs, durable recovery, compatibility rules, cancellation, progress, regression/package/live gates are each assigned above.
- Placeholder scan: every task has named files, interfaces, test commands and explicit acceptance behaviour.
- Type consistency: Tasks 2–4 share the sealed unsigned result and version-2 contract; Task 5 consumes only additive status fields from Task 4.
