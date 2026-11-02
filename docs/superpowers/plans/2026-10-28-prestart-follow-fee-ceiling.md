# Pre-start Follow Fee Ceiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a completed standalone Coin Prep session receive a fresh native review that raises its initial Follow cumulative fee ceiling to exactly 0.005 XCH without changing its completed targets or prior fee accounting.

**Architecture:** Reuse the existing immutable fee preview and approval-version tables in the same economic scope. A dedicated pre-start preview records the original approval, exact spent/held accounting, previously protected cancellation reserve, freshly verified wallet/targets/funding and proposed ceiling. A dedicated native confirmation rechecks those fields and inserts a new version plus consent atomically. The later Follow review obtains a fresh shutdown fee quote. Follow resolves the latest version for the completed session, while the worker's completed approval remains historical evidence.

**Tech Stack:** Python, Flask, PyWebView, SQLite WAL, vanilla JS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-prestart-follow-fee-ceiling.md`

## Global Constraints

- Both original PCs remain stopped during source work. No CLI/API wallet effect, fee approval, Start, cancel, reconciliation or latch change.
- Exact initial requested cap is 5,000,000,000 mojos (0.005 XCH) per PC; earlier 0.05 wording is superseded.
- Preserve immutable prior approval, Coin Prep completion, confirmed spent 774,766,315 mojos on Harvestr, and any held fee. Protected cancellation cannot decrease.
- Native operator confirmation and action-time Computer Use confirmation are required for live final financial clicks. No source test or mock is live authorization.
- PR272 and site PR93 stay draft/unpublished. No 24/24 readiness or observation pass claim from source tests.

## Review Focus

- A fee outcome settles between preview and confirm: confirmation refuses and records no new approval.
- A regular completed-session preview rotates the session: the pre-start review becomes stale and cannot confirm.
- A second final click or concurrent confirmation consumes the preview once and cannot mint another version.
- A changed wallet, receive address, configuration, target coin set, or plan refuses even if balances still add up.
- An existing Follow run routes through active-run revision; the pre-start path refuses.

---

### Task 1: Completed-scope preview and ledger confirmation

**Files:** Modify `src/catalyst/coin_prep_fee_approval.py`, `src/catalyst/database.py`; create `src/catalyst/prestart_follow_fee_ceiling.py`; test `tests/test_prestart_follow_fee_ceiling.py`.

**Interfaces:** `preview_prestart_follow_fee_ceiling(approval_id: str, proposed_maximum_fee_mojos: int) -> dict` and `confirm_prestart_follow_fee_ceiling(preview_id: str, review_sha256: str) -> dict`. The preview returns the exact prior/new ceilings, spent, held, protected allowance, funding, quote expiry, identity, and a single-use review digest. Confirmation returns the new approval ID and unchanged cumulative accounting with `dispatch_authorized=False`.

- [x] Write fixture-backed failing tests for a completed current standalone session, proposed 5,000,000,000-mojo ceiling, no new wallet effects, unchanged scope/plan and completion, plus accounting drift, rotation, replay, wallet, funding and existing-run refusals. Existing ledger tests cover authoritative confirmed-spend evidence; a synthetic outcome fixture was rejected by the database's journal-evidence trigger.
- [x] Run `pytest -q tests/test_prestart_follow_fee_ceiling.py` and verify failures are caused by absent pre-start interfaces.
- [x] Implement preview using `read_approved_prep_fee_snapshot`, exact target proof, original scope/plan, prior protected reserve and fresh funding. Persist a purpose-marked immutable preview and reviewed accounting; never call completed-session scope rotation.
- [x] Implement native-confirm service and one `database.py` serialized transaction that rechecks latest version, same scope/plan/session completion, no existing Follow run, exact spent/held, prior protection, preview age and one-time use before inserting a new `fee_approvals` version and `coin_prep_fee_consents` row. Ordinary fee confirmation rejects purpose-marked previews.
- [x] Re-read wallet/identity/targets before and after ledger confirmation; a changed observation refuses run authority, even if the append-only ceiling record was already written.
- [x] Run focused tests and the full existing suite, including fee ledger/session completion tests. Commit the integrated change, then build that exact commit in an isolated checkout.

### Task 2: Native review and Follow approval resolution

**Files:** Modify `src/catalyst/app_bridge.py`, `src/catalyst/blueprints/coin_prep.py`, `bot_gui.html`; test `tests/test_prestart_follow_fee_ceiling_native_bridge.py`, `tests/e2e/test_prestart_follow_fee_ceiling.py`.

**Interfaces:** Bridge methods `prepare_prestart_follow_fee_ceiling_review(body)` and `confirm_prestart_follow_fee_ceiling_review(body)` accept closed, typed inputs and return `{"success": bool, ...}`. Completed Coin Prep status distinguishes worker completion approval from latest Follow-eligible approval.

- [x] Write failing bridge and browser tests: exact 0.005 amount/spent/held/protection visible; no HTTP-only final path; refresh on stale review; duplicate click disabled; Follow refresh uses latest completed-scope approval; no Prepare/Start side effect.
- [x] Run the focused tests and verify the intended failures.
- [x] Add a dedicated native review modal reachable from the completed Coin Prep/Follow mismatch state. Render server text with `textContent` or `escapeHtml()`. The final button calls the bridge only and does not start a worker or bot.
- [x] Resolve the latest consented version for the completed session in status readback, retaining the original worker approval as immutable completion evidence. Make Follow review use the latest version and keep its existing exact-cap equality check.
- [x] Run focused bridge/E2E tests. Commit the integration, then build that exact commit in an isolated checkout.

### Task 3: Full verification and release-candidate handoff

**Files:** No production edits unless a failing test identifies a defect; add only targeted regressions needed to prove a discovered gap.

- [x] Run relevant fee, Coin Prep, Follow principal/slot/shutdown, database migration and UI suites; inspect every failure and preserve traces. Fresh reviewer found the initial ceiling could exceed 0.005; two RED tests demonstrated that gap. The service and ledger now require exactly 5,000,000,000 mojos; latest four-worker suite: 8,266 passed, 356 skipped, 460 subtests passed. Native review E2E: 2 passed.
- [ ] Run lint/security gates and fresh normal Windows build from the exact PR head. Record source commit, test counts, CI revision, ZIP/manifest and EXE hashes.
- [ ] Re-audit both original DBs/Sage/native process identities and balances before proposing any EXE replacement. A new live EXE launch needs action-time user confirmation.
- [ ] Keep PR272 draft and site PR93 unpublished. Only after native 0.005 review, 24/24 principal/slot/market proof and separate final financial confirmation may a live Start be considered; 48-hour observation begins only after both ladders run.
