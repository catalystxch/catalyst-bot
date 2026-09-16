# Dynamic Coin Prep fees and explicit spending approval

Status: chat design and written specification explicitly approved by the user on 16 September 2026. Implementation is authorized. Persistent goal and hourly continuation loop are active.

## Purpose and scope

Replace flat standard-transaction assumptions with transaction-size-aware, current-network fee guidance and a durable, explicitly approved spending ceiling. Default inclusion target is 300 seconds. This is an estimate, never a promise of block inclusion or a five-minute total Coin Prep duration.

Preserve wallet identity, pair, capital allocation, strategy, reserves and existing authority checks. Do not change market-confidence gates, create a release, merge main, or treat the blockchain duststorm as a CATalyst defect. Live TEST 7 testing requires verified mainnet Sage fingerprint 736588221, wallet ID 2 and MZ asset b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105. New fee-budget approval must be genuine operator consent; broad testing permission cannot fabricate it.

## Existing components

- `src/catalyst/tx_fees.py` already queries local Chia full-node and Coinset fee estimates, but commonly uses a generic configured cost. Preserve its existing interface for unrelated callers while adding provenance/freshness and strict response validation for this workflow.
- `src/catalyst/wallet_sage.py` can estimate mainnet CLVM cost from an unsigned Sage transaction. All application wallet access remains through `wallet.py`.
- `src/catalyst/coin_prep_worker.py` has direct final-output transactions, compatibility combines and split/fee preparation paths. XCH compatibility combines currently have a flat fee floor. Every fee-bearing prep dispatch must use the same approval enforcement, or fail closed as unsupported.
- `src/catalyst/blueprints/coin_prep.py` owns normal and bootstrap Coin Prep triggering. `app_bridge.py` mirrors the HTTP route for the desktop window. `bot_gui.html` owns the frontend.
- PR #218 at 9508ae849cdb5f6e5b80907979965ad7b7172d4c provides database-only atomic fee holds. It is unmerged groundwork, not a live control. Reuse only after reviewing amendments and adding missing schema/recovery invariants.

## Estimate, confirmation and execution

1. Clicking Coin Prep first requests a read-only preview, with no reset, signing, submission or worker launch. Snapshot the canonical wallet/network/asset and economic plan, inspect selectable source inventory, and identify required transactions without changing it.
2. Build unsigned transactions for currently available exact inputs when supported. Validate their intended effects and calculate actual CLVM cost. For later stages whose inputs do not yet exist, show a conservative projected cost and distinguish it from exact unsigned cost. Never claim the whole multistage plan has exact prebuilt bundles.
3. Obtain fee guidance for the applicable cost and 300-second target using a configured local node or Coinset. Validate success, matching target/cost, estimate count, finite nonnegative numeric values, observed time and network evidence when supplied. Missing estimates must not become a fabricated available zero. Use integer mojos and Decimal; round required fees upward.
4. Show the target, number of required transactions or projected count/range, per-stage estimates, total estimated fee, estimate source/time, projected versus exact labels, maximum approved fee, and protected cancellation allowance. Distinguish fee-coin face value retained in the wallet from fees actually spent. No arbitrary hidden fee ceiling increase or invisible buffer.
5. A deliberate operator confirmation creates a durable approval tied to a server-derived scope and plan digest. The displayed maximum is editable and must cover the validated planned spending and cancellation allowance; never silently alter an existing campaign fee budget. Cancel closes the dialog without mutations. Insufficient fee funding blocks confirmation with a clear explanation.
6. Immediately before each dispatch, verify identity and exact economic effect again, build/validate its unsigned bundle and actual CLVM cost, refresh network guidance, and price the final bundle. Fee changes can affect cost or change outputs, so re-evaluate until the validated final cost/fee/effect contract is consistent, using bounded retries.
7. Atomically reserve that exact final fee against the approval before signing/submitting. Repricing is permitted only within the approved total and non-cancellation allowance. If the required price no longer fits, do not submit: pause with spent/held/remaining totals and a fresh estimate, and require explicit approval of an increased ceiling. Do not spend first and report overrun later.
8. Changed wallet/network/asset or changed economic plan invalidates approval and requires renewed confirmation. Expected intermediate output transitions inside the approved staged plan do not themselves create a new economic plan, but must be proven and incorporated in exact per-operation contracts.

## Freshness and unavailable providers

Preview guidance is usable for at most 60 seconds from its original observation time. Cache hits retain the original observation time; reading a cache cannot make an old quote fresh. Refresh after that window and before each new dispatch. Freshness limits constrain guidance, not accounting: accepted/submitted fee commitments never expire when the estimate does.

If all configured estimation sources are unavailable or their responses are stale/malformed, show an unavailable state and block automatic submission. The user can retry estimation. A manual fee mode already configured elsewhere does not bypass this approval gate or imply a timely confirmation estimate. An explicitly acknowledged manual fallback can be a later separate feature; it is not included in this implementation.

Use a fee floor only when justified by current relay/mempool evidence and the validated transaction cost; do not always pay six mojos per cost merely because a previous duststorm required it. Estimate source disagreement, unavailable congestion indicators and uncertain projected stages must be visible. Never infer that local RPC acceptance proves network acceptance or block confirmation.

## Durable ledger and recovery

All database access remains in `database.py`. Add approvals/reservations to canonical schema validation and migrations with exact integer constraints, indexes and append-only approval semantics. Scope is server-derived from canonical wallet/network/asset/campaign or standalone prep-session identity, not an arbitrary client string. Plan digest covers economic outputs, tier/multiplier/reserve choices, target and approved cancellation policy, not transient fee estimates.

Approval versions retain prior commitments in the same economic scope. An operation's deterministic ID binds its exact selected inputs, intended outputs, fee and effect identity. Retrieving an existing reservation is not authorization to submit the same external effect again. Recovery must join fee holds with the existing authoritative operation/effect journal.

Reserved, submitted/unknown and confirmed-spent states remain counted. Only authoritative proof of no effect before submission or definitive no-effect recovery may release a reservation. A timeout, missing peer response, process exit or missing immediate wallet balance update is not proof. Confirmed fees remain spent across restarts and later approval versions. Evidence and transition IDs must make observation/import idempotent; no double counting or automatic refunds.

Keep reservation and dispatch fencing safe across concurrent workers, crashes between hold and signing, crashes after submission and legacy operations. Do not rewrite historical fees as zero or mark unproven operations settled. Already submitted transactions may continue confirming while preparation is paused; the status UI must say this explicitly.

Cancellation transactions attributable to this workflow may use its protected allowance but not exceed total approval. Unrelated legacy cancellations must retain their existing safety model and must not be silently charged to another prep scope. Do not reduce the protected cancellation allowance to fund more preparation. If the allowance is insufficient for required safe cancellation, report and request fresh approval.

## User interface and API requirements

Use a focused estimation/approval service and small route integration points; do not further entangle fee logic in the large worker and GUI. Both HTTP and native bridge entry points enforce the same approval requirements. Worker delegation includes a validated approval reference, not client-controlled authority. Direct API calls, automatic bootstrap replacement prep and retry buttons cannot bypass the gate; missing approval returns a structured approval-required state.

The confirmation dialog displays wallet/pair, estimated and maximum spend, source/age, inclusion target and cancellation protection. Use `escapeHtml()` or textContent for server data. Disable duplicate confirmation while processing; errors remain actionable, and refresh produces a fresh preview rather than launching another worker. Show waiting-for-approval, estimating, preparing, submitted-awaiting-confirmation and paused-budget/provider states consistently. Successful completion must not leave stale red cost errors visible.

Approvals, held/spent totals and paused reasons survive reload. Returning users see the current pending operation and remaining budget, not an invitation to start an overlapping prep. History/counter reset controls never delete approvals, holds or authoritative effect evidence.

## Verification and acceptance gates

Use focused failing regressions before implementing each control. Required cases: varying exact costs and congestion; low and high network estimates; malformed/NaN/negative/boolean values; zero/missing result distinctions; stale cached guidance; five-minute target; cost/fee fixed-point convergence; insufficient funding; unchanged plan repricing within cap; exceeded cap without dispatch; wrong/stale identity/plan approval; all prep dispatch families; HTTP/bridge bypass attempts; bootstrap automatic prep requiring approval; duplicate/concurrent confirmation; conflicting operation replay; restart at every reservation/submission transition; authoritative no-effect release and confirmed accounting; cancellation allowance; preserved approvals after runtime-counter/history resets.

Exercise the GUI preview, Cancel, confirm, refresh, provider outage, increased-cost pause, reload and restart with mocked wallet effects first. Run targeted tests, relevant database/authority/prep/fee regressions, full suite where practical, browser E2E and a fresh Windows build. Then perform live acceptance using verified TEST 7 identity and genuine approved fees: preview, prep, confirmation evidence and restart recovery. Record blocked or untested gates as incomplete. Never claim timely inclusion is guaranteed.

Completion requires implemented enforcement on all supported prep paths, demonstrated no bypass, durable recovery/accounting, accurate GUI and API readback, fresh test/build evidence and live acceptance under authorized fees. Main merge and release are separate decisions.
