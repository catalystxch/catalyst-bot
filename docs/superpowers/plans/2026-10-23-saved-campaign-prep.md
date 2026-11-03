# Saved campaign preparation implementation plan

> Execute inline with test-driven development; user explicitly requested proceeding without further design questions.

Goal: expose an explicit native review of Coin Prep for an already saved Bootstrap campaign without saving general settings or reusing a completed cancellation approval.

Architecture: add an active-campaign-only button beside campaign controls. Re-fetch durable status and existing config read-only, validate exact identity/revision and configured fee pool, then invoke existing campaign-bound coin verification and fee-review UI. Record only an in-memory campaign-specific setup review; never mark blank general settings saved. Backend wallet and fee gates remain unchanged.

Constraints: no original profile imports or live RPC in tests; no configuration POST, automatic fee approval, prep trigger or bot start; preserve campaign budgets/revision and original fee count50/size0.001. Existing user approval covers narrow implementation, not a new binary launch or financial confirmation.

- [x] Add browser regression: active saved campaign + blank general inputs + old cancellation intent can reach current campaign verification without config POST, approval, trigger or start. Watch fail on missing continuation.
- [x] Implement button, fresh scope/config validation, campaign-specific review state and safe clearing of stale cancellation UI intent; reuse existing verification/fee review.
- [x] Test refusal for stopped/running/mismatched/revised campaign, fee pool zero, unavailable status/config, and invalidation of reviewed scope. Verify unrelated general fields/localStorage untouched.
- [ ] Run browser and relevant backend regressions, full pytest, lint and build; source-owner independent review before integration. Inspect actual packaged HTML and disposable profile boundary before any human-reviewed launch.

Review focus: stale old fee intent, campaign revision/asset drift during async reads, zero fee pool, blank unrelated settings, no automatic wallet effects.

Verification so far: RED missing-button regression, then 15 targeted Chrome tests pass; combined fee approval/pair/entry browser suite passed 59 tests before the last two malformed-response cases were added. Ruff and whitespace checks pass. Independent read-only review found no blocking issue; minor recommendation is a success-shaped fee-preview/tier presentation fixture. Full isolated suite remains running; packaged build and original-profile launch are not yet verified.
