# Coin Prep pre-dispatch fee recovery

## Live observation

The Harvestr TEST 7 v1.4.1 one-day MZ/XCH Bootstrap campaign reached 30% Coin Prep and failed closed with `FEE_ESTIMATE_UNAVAILABLE`. The worker had persisted a `PREPARED` coin-prep operation and an unresolved wallet-effect claim, then retained the claim as `DIRECT_BATCH_FEE_APPROVAL_FAILED`. The runtime safety latch blocked further wallet effects.

The read-only second-PC audit found no constructed outputs, approved fee reservation or outcome, wallet-effect dispatch or resolution, Sage pending transaction, offer, or paid fee. All 43 CAT inputs and the XCH fee input remained selectable. The app process and lease remained healthy. The old build cannot release this exact pre-dispatch state through its startup recovery, so it must not be restarted on the assumption that restart alone repairs the latch.

The 16:33:23 UTC quote was the UI consent preview. The worker generated a separate execution quote around 16:39–16:40 UTC, acquired the claim at 16:40:34 UTC, persisted `PREPARED` at 16:40:40 UTC, and failed fee validation at 16:41:02 UTC. The old log does not distinguish expiration from unsigned-cost drift at the final check.

## Change

- A quote with less than ten seconds remaining is rejected before a wallet-effect claim is made.
- On a fee validation failure before dispatch, the worker attempts a fresh read-only exact-cohort proof. No proof leaves the safety fence intact.
- Startup recovery can terminally release an exact `PREPARED` no-dispatch claim, including one earlier marked `SUBMITTED_UNKNOWN` solely because observation was unavailable. The authoritative view must be current, bound to the stored wallet identity, contain every source and fee coin as selectable, and have no pending transaction. The database atomically rechecks no constructed outputs, fee hold/outcome, or dispatch before recording `RELEASED_NO_EFFECT`, a failed no-effect operation, and latch resolution.
- The rejected quote is now logged with observed/expiry time and quoted versus validated cost and fee, without wallet secrets.
- The exact legacy PR #218 fee-ledger upgrade temporarily removes only the canonical wallet-effect resolution guard while swapping fee tables, then restores that guard in the same transaction. This preserves pending fees and the pre-dispatch recovery checks during upgrade.

## Verification and limits

Focused regressions cover stale or nearly expired quotes before claim; valid and invalid exact-cohort proof; restart recovery; a retry collision after safe release; immediate recovery; and continued fencing without proof or after dispatch. A same-contract retry still cannot reuse the historical immutable operation ID: it fails closed and releases the colliding claim, without replaying a wallet effect. This change does not authorize any wallet transaction or override the 0.01 XCH campaign fee cap. A replacement build must pass package checks and be installed on the second PC before live recovery is attempted. Fresh wallet, process, offer, pending-transaction, campaign, fee-ledger, and safety checks remain required at that time.

The exact affected Windows suite passed 190 tests, including the legacy fee-ledger migration and restored-guard assertion. An earlier broad serial run passed 7,575 tests but exposed the migration failure plus three source-introspection tests that passed when isolated; the migration was fixed before this affected rerun. Broad exact-head CI and package verification remain gates before live recovery.
