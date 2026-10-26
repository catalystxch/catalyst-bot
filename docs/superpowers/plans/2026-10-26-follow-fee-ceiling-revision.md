# Follow Fee Ceiling Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user revise the initial 0.005 XCH cumulative fee ceiling during an active 24 BUY / 24 SELL Follow run, without resetting lifetime spending or weakening shutdown funding.

**Architecture:** Keep the existing run ID, wallet identity, configuration, offer intents and initial fee scope immutable. Each ceiling change gets a short-lived, single-use native review and an append-only revision tied to that run; its fee approval version uses the same economic scope so prior spent and unresolved held fees remain counted. Every creation, cancellation and final wallet check reads the effective revision inside its existing transaction. A higher ceiling requires contemporaneous proof of protected fee-coin funding; an unfunded change fails closed and asks for a separate reviewed Coin Prep path.

**Tech Stack:** Python, Flask/PyWebView, SQLite WAL, Sage wallet adapter, pytest, browser UI tests.

**Spec:** User instruction on 2026-10-26: 0.005 XCH starting ceiling per PC, adjustable during the active run as fees change; prior 24/24, maximum safe principal, one normal build and 48-hour observation requirements remain. Existing authority design: `docs/superpowers/plans/2026-10-25-follow-fee-authority.md`.

## Global Constraints

- All fee values are integer mojos. The displayed XCH value uses exact decimal conversion.
- Revisions require a fresh explicit native final confirmation; no automatic increase, CLI/API consent substitute or wallet authentication automation.
- Use the same immutable `scope_sha256`, `plan_sha256`, run ID and cumulative `_fee_scope_totals` across every revision.
- A decrease cannot fall below spent plus unresolved held fees plus protected shutdown reserve while creation remains active.
- A new ceiling cannot authorize trading principal or fee coins that the current wallet cannot prove selectable and protected.
- On a failed or expired review, the prior ceiling remains effective. Ambiguous wallet effects remain held.
- PR272 and website PR93 stay draft/unpublished; original profiles are not changed by source tests.

## Review Focus

- Confirm and reserve race: a fee hold begun under the old ceiling must be rechecked against the effective revision at wallet dispatch.
- Lower ceiling with an unresolved hold must reject, preserving both the hold and old authority.
- Raise ceiling without enough currently protected fee-coin principal must reject, even if the wallet has unrelated trading XCH.
- Process restart must reconstruct exactly one latest revision and retain all earlier fee spending in the same scope.
- Stop or expiry must retain exact journaled cleanup under the most recently approved ceiling and must not grant new offer creation.

---

### Task 1: Append-only revision review and effective policy reader

**Files:** Modify `src/catalyst/database.py`; test `tests/test_follow_fee_ceiling_revision.py`.

**Interfaces:** `create_follow_fee_ceiling_review(run_id, identity, proposed_maximum_fee_mojos, observed_fee_principal_mojos, now_epoch) -> dict`; `get_follow_fee_ceiling_review(review_id) -> dict`; `get_effective_follow_fee_policy(run_id, identity, now_epoch) -> dict`.

- [ ] Write tests for immutable five-minute review, exact identity/run/scope binding, initial 0.005 XCH ceiling, and stale/replayed review rejection.
- [ ] Run those tests and confirm the missing interfaces fail.
- [ ] Add append-only review and revision tables plus schema validation and the read-only effective policy reader.
- [ ] Run focused schema/restart tests, Ruff and `git diff --check`; commit.

### Task 2: Native final consent and funding proof

**Files:** Modify `src/catalyst/follow_principal.py`, `src/catalyst/blueprints/coin_prep.py`, `src/catalyst/app_bridge.py`, `bot_gui.html`; test `tests/test_follow_fee_ceiling_revision.py` and rendered GUI tests.

**Interfaces:** `prepare_follow_fee_ceiling_review(...) -> dict` derives current wallet/fee-pool proof; `confirm_follow_fee_ceiling_review(review_id, review_sha256) -> dict` consumes the exact native review and atomically records one effective fee approval revision without starting/stopping the bot.

- [ ] Write failing tests for increase, decrease, insufficient protected funding, changed wallet/configuration, edited GUI amount, expired review and double click.
- [ ] Implement read-only proposal with current spent, held, reserve, old ceiling, proposed ceiling, fee-coin funding and exact identity visible in the native review.
- [ ] Implement native-only confirmation using the existing lifecycle lock and one SQLite `BEGIN IMMEDIATE` transaction. Reject arbitrary API requests and unrelated Coin Prep approvals.
- [ ] Run focused service, HTTP, bridge and rendered GUI tests; commit.

### Task 3: Enforce the effective ceiling at every fee boundary

**Files:** Modify `src/catalyst/database.py`, `src/catalyst/offer_manager.py`, and the existing creation/cancellation fee readers; test `tests/test_follow_fee_ceiling_revision.py`, `tests/test_follow_fee_cancellation_hold.py` and wallet-boundary tests.

**Interfaces:** Existing creation and cancellation fee reservations, pricing readers, restart recovery and final adapter callbacks consume `get_effective_follow_fee_policy` without changing their wallet-effect API.

- [ ] Write failing tests for lifetime spent+held accounting across two revisions, revised cap at final dispatch, generic stale approval rejection, and exact old-run cleanup after a later approval.
- [ ] Bind new holds to the current revision's approval ID while preserving the same scope; make recovery map both initial and revised approval IDs to the original run.
- [ ] Recheck effective ceiling, protected shutdown reserve, unresolved effects, identity and fee-coin funding immediately before wallet effect.
- [ ] Run the full Follow fee/cancellation/restart matrix, Ruff and `git diff --check`; commit.

### Task 4: Release integration and original-profile review

**Files:** Modify only integration defects found by the gates; preserve evidence under the existing acceptance directories.

- [ ] Prove the initial 0.005 ceiling can fund the exact 48-offer shutdown at current quotes or obtain a new exact user-reviewed ceiling before Start.
- [ ] Run full combined tests, security/lint checks, clean normal production build and identical artifact hash checks on both PCs.
- [ ] Verify native review and final-click behavior on original profiles, with human wallet authentication and action-time confirmations for financial effects.
- [ ] Start the authorized 24/24 runs only after all other financial/safety gates pass; collect 48 hours of identity-bound observations without claiming a pass from gaps or stale snapshots.
