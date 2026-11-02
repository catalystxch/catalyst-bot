# Scoped confidence override implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow explicit user consent to continuous Follow despite thin-market confidence, without changing displayed confidence or financial safety.
**Architecture:** An in-memory, expiring run permit binds an immutable review digest to live wallet identity, saved economic configuration and existing fee approval. Persist consent for audit only; never restore it as authority. A fresh-price projection feeds existing candidate profitability checks while raw RED evidence remains unchanged.
**Tech Stack:** Python, Flask, SQLite through database.py, native HTML/JavaScript.
**Spec:** Human-approved design in this conversation: wallet/asset/duration/limits/fee-bound consent; RED remains visible; no wallet/fee/runtime bypass.

## Global constraints
- Isolated source only; no original profile or live wallet mutations, launch, trading, merge or release.
- Explicit native consent; no hidden environment toggle or automatic renewal.
- Only thin depth and provider redundancy policy may be overridden; freshness, two-sided prices, conflict/manipulation and all existing financial guards remain enforced.
- Stop, restart, expiry, identity/config/fee-approval drift revoke permission.

## Review focus
- First-ever thin book must use current observed prices, never a historical trusted range.
- A consent expiring between planning and dispatch must fail at final candidate checks.
- Config or wallet changing and then changing back must not resurrect an invalidated permit.
- Background publication and confidence-driven cancellations must agree with creation.
- No consent must preserve current behavior exactly.

### Task 1: Consent policy and fresh range
Files: new src/catalyst/confidence_override.py, tests/test_confidence_override.py; modify market_confidence.py.
- [x] Write tests for scope/digest/time/expiry/drift/revocation and thin-only fresh range, watch failure.
- [x] Implement pure policy, immutable run permit and explicit audit-only persistence.
- [x] Test RED unchanged and missing/stale/crossed/conflicting prices rejected.

### Task 2: Runtime and native consent
Files: bot_loop.py, offer_manager.py, database.py, blueprints/bot.py, blueprints/market.py, app_bridge.py, bot_gui.html.
- [x] Add failing tests for candidate, phase, target and withdrawal behavior with/without valid consent.
- [x] Add server-generated review, exact confirmation on start, bounded duration, existing fee authority binding; persist through database.py.
- [x] Wire runtime effective confidence, publication and withdrawal checks; revoke on stop/drift and failed start.
- [x] Add native review and active warning, escaped text, explicit checkbox; no automatic confirmation.

### Task 3: Verification and reviewed handoff
- [x] Run focused real policy/runtime/API/frontend tests, lint, format and diff checks.
- [x] Review whole branch, repair issues, rerun relevant regressions.
- [ ] Send source commit and evidence to production integration owner; preserve draft release and live restrictions.


## Execution ledger
- Isolated clone/feature branch codex/scoped-confidence-override from b505733487c0010534d7fd21ea73bb511f4c2625; original profile and dist untouched.
- Ruling: implement inline under the existing explicit source execution approval; no redundant permission request for plan mechanics.
- Ruling: only low-depth/redundancy warnings are overrideable, not missing/stale/crossed/conflicting prices or manipulation. This follows the approved requirement to preserve valid pricing.
- TDD: missing policy module, runtime capacity/effective view, API/bridge, wallet-dispatch callback, and delayed-scope deadline test observed failing before each fix.
- Independent review found final wallet dispatch, Resume handoff, and stale-clock-after-wallet-read gaps; all fixed with regressions and reviewer confirmed no outstanding important findings.
- Audit receipt is never a restorable permit. Temporary pending cancellation accounting blocks effects but does not permanently revoke a matching consent; scope drift or expired consent does.
- Focused final suite218 passed53.51s (before final clock reordering); final policy35 passed1.95s; repository Ruff check and changed-file format pass. Browser3 passed4.34s with all network requests intercepted.
- Full isolated suite running; no pass claimed until exit0. No build, launch, profile change, financial action, merge or publication.

- Price-persistence integration ruling: the raw engine cannot confirm a material move while depth is insufficient. Preserve confirmation by collecting distinct fresh observed midpoints within the existing preset jitter/persistence thresholds in run memory; never count repeated reads, waive hard caps, conflict, manipulation, or expose unconfirmed prices. No durable engine state or confidence label is modified.
- Earlier full-suite strict variant was explicitly cancelled/superseded before completion and is NOT a final pass. A fresh final suite follows persistence integration.


## Final integration contract and validation ledger
- Financial authority is supplied by primary integration through read-only `database.get_follow_creation_authority(identity=..., configuration_sha256=..., now_epoch=...)`. Preparation consent is never accepted as a substitute. The absent reader fails closed; this component alone is not a financial-cap implementation.
- Primary uses `confidence_override.current_configuration_digest()` for the exact financial binding. Immutable run ID, consent ID, expiry, side counts, cap and protected shutdown reserve enter the risk scope; mutable spent/held counters do not reset consent. Temporary `FOLLOW_UNRESOLVED_EFFECT` pauses effects without granting permission.
- Only durable `follow:<run_id>:normal_lifecycle` and `follow:<run_id>:book_opportunity` intents may inherit the current risk consent. Publication checks the durable record and consent again after lookup; withdrawal protects only current-run IDs. Bare, legacy, other-run, malformed and terminal intents receive no waiver. Mixed-run regressions pass; independent review found no important fail-closed gaps.
- Focused policy/runtime/API/wallet regressions: 614 passed in 91.48s before attribution tightening; browser native-modal flow: 3 passed in 11.65s. New exact-run tests were observed failing (5 failures) then passed. Policy plus market guard: 57 passed; two further real publication/withdrawal integration regressions passed (50 policy tests total).
- Earlier serial runs were cancelled/superseded or failed and are not passes. The first complete four-shard baseline finished with 8026 passed, 345 skipped, 457 subtests and one obsolete static forwarding assertion failure; three shards passed. Its logs are preserved outside source under validation-before-attribution. The assertion was updated to require the effective current-confidence view, backed by behavioral dispatch and consent regressions.
- Fresh complete four-shard validation is running after attribution changes, with separate temporary profiles per process. No final full-suite pass is claimed until its exit results are inspected.
- No live configuration, new quote, financial consent, preparation, launch, trading, merge or release has occurred in this source task.

- Final latest-source four-shard run completed all four exit0: 8034 passed, 345 skipped, 457 subtests passed, one existing warning. Shard times 587.56/473.01/507.41/617.65 seconds; exclusive 368-file manifest. Ruff check, 14 changed-file format checks and diff checks pass. No financial integration or release readiness is inferred from this component validation.
