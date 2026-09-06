# Direct-batch Coin Prep

Date: 4 September 2026

Status: written specification approved; user requested startup/Cancel All testing first

Scope: faster Sage Coin Prep, without weakening wallet-effect safety

## Outcome

Create missing final-sized trading and fee coins directly in bounded transactions. Reuse suitable existing coins. Remove the routine consolidation -> tier-pool creation -> individual tier splits -> cleanup chain from the eligible Sage path.

Five minutes is the performance target under ordinary confirmation conditions, not a guaranteed deadline. The measurable software improvement is fewer dependent transactions and confirmation rounds, without replaying uncertain transactions or reducing verification.

## Evidence and choice

Local run `54fae2b1` started at 15:56:54 UTC and finished at 16:26:34 UTC on 4 September: approximately 29 minutes 40 seconds. It prepared 126 XCH coins and 76 MZ coins, plus reserves. The final log records successful designations and matching tier sizes.

Consolidation took approximately 8m45, tier-pool creation 2m12, sequential tier splitting 17m23, and cleanup/final verification another 1m20. The workflow involved roughly 20 transactions. `_wallet_mutation` waits for authoritative confirmation before returning from each split/combine. Consequently, `_submit_split` is no longer genuinely submit-only despite its comments; the later collective poll reports already-confirmed splits.

Source inspection locates this confirmation barrier in the stability-kernel integration at commit `8560be5b`. The barrier protects recovery and must remain. The separately staged Splash inbox fix addresses a persistent safety fence, not this performance bottleneck.

Alternatives considered:

- Shorter polling: does not remove sequential blockchain waits; insufficient.
- Concurrent tier transactions: could shorten the critical path, but changes effect admission and recovery across overlapping source/fee cohorts; deferred.
- Direct final-output batches: chosen. Retains serial admission and authoritative confirmation while eliminating most intermediate transactions.

Detailed local evidence: `C:/catalyst/evidence/coin-prep-desktop-bridge-20260904.md`. No raw wallet logs, credentials or user wallet identifiers are to be committed with the implementation.

## Scope and invariants

- Initially applies to the existing Sage tiered-prep workflow. Chia and other prep modes keep their existing behavior.
- Keep the selected wallet/network/asset, Smart Settings, trading limits, reserve amounts, headroom rules and risk settings unchanged. Never recompute the user's strategy merely to fit a batch.
- Use existing tier-count and amount calculations. New outputs use exact integer amounts; reuse uses the existing eligibility rules without widening tolerances. Use integers for base units and `Decimal` for conversions.
- Preserve already-suitable unencumbered trading/fee coins by identity. Do not consume offer-locked, pending, reserved-by-operation or otherwise nonselectable coins.
- Preserve the configured reserve floor for each asset. A selectable reserve/change coin may be reshaped only with an explicit return contract that maintains that floor after all prep fees. A reserve is not permission to spend below the user's reserve setting.
- Completion requires confirmed, owned and selectable outputs, satisfied tier counts, sufficient reserves, and successfully persisted designations. RPC success or mempool acceptance alone is not completion.
- No automatic bot start, trade, offer cancellation, history deletion, safety reset, fee-setting change or production release is part of this redesign.

## Components

### Pure batch planner

Add `src/catalyst/coin_prep_batch_plan.py`, independent of wallet calls and database writes. Inputs are a validated coin snapshot, current tier requirements, existing eligible assignments, reserve floors, fee budget and batch limits. Output is either a deterministic next-batch proposal or a structured refusal explaining why it cannot safely proceed.

A proposal identifies exact source coins, any external XCH fee coin, every intended output amount and purpose, change/reserve allocation, and the explicit fee. Stable coin-ID tie-breaking makes identical inputs yield identical plans.

Choose largest eligible unmatched sources first, then pack missing targets in deterministic tier order. Deduct reused slots once only. Never count the same coin toward two tiers. Include required change in the batch contract. Replan the remaining deficit only after the previous batch is authoritatively confirmed; never assume pending change is spendable.

When both sides need work and a separate eligible XCH fee input exists, prepare CAT first, then include its confirmed XCH fee change in final XCH planning. Otherwise, fund the CAT fee from an explicitly planned XCH prerequisite batch. A fee prerequisite must not consume a coin already protected for reuse or breach the reserve floor; if that cannot be satisfied, refuse with the specific funding reason.

Initial application limits are at most 50 asset inputs, plus one explicitly selected external XCH fee input for CAT, and at most 128 final wallet outputs including change across both assets. Respect a lower configured Sage consolidation input limit. These are conservative application limits, not claims about protocol limits; they remain below the existing 512-output contract ceiling. Build/validation failures can require smaller batches.

If the next needed output cannot be funded within the input cap, allow only the existing bounded consolidation prerequisite for that deficit, with its fee disclosed in advance. Do not consolidate an entire already-prepared side. If available balances cannot fund outputs, reserves and the fee budget together, refuse without shrinking reserves or target sizes.

### Sage transaction adapter

Use the wallet facade and the existing Sage `create_transaction` action mechanism with explicit selected inputs. It already supports custom output amounts and unsigned construction. Do not use send endpoints that ignore input hints.

Separate unsigned construction/validation from signing/submission for the new batch path. Validate the returned external removals against the claimed asset and fee cohorts, and validate destinations, amounts, asset identity and fee before signing. Account for any internal ephemeral spends separately; they do not authorize additional wallet inputs.

Repeated equal-sized outputs must become distinct coin identities. Validate the actual constructed output multiset, not just the number of requested send actions: coalescing or duplicate coin IDs is a refusal, not success. Do not change tier amounts to make outputs unique. If the installed Sage cannot construct the required distinct outputs safely, use the compatibility path before signing rather than weakening verification.

Unsigned construction is not a financial submission. A strictly unsigned local build rejection may be partitioned into smaller batches; a response suggesting any submission must instead enter uncertain-effect recovery. Do not probe build limits with signed transactions.

### Worker and durable recovery

Integrate the planner into `coin_prep_worker.py` ahead of routine consolidation and tier-pool creation, so eligible direct runs skip both stages. Reuse the existing wallet identity binding, mutation permit, effect claims and durable Coin Prep operation records. Extend the exact-operation allowlists for the new batch call with focused tests, rather than exempting it from admission.

Each batch has a canonical contract including sources, final output amounts/purposes and fee cohort. Persist its association with the run and immutable plan/config identity through `database.py`. Bind exact constructed output IDs before submission. Any additional fee-change/output metadata must be versioned so recovery of legacy operation records remains supported.

Keep this ordering:

1. Validate fresh identity/configuration and authoritative spendability; claim exact inputs.
2. Build unsigned, validate its complete effect, and durably record the exact contract.
3. Recheck identity/ownership immediately before signing and dispatch; record the dispatch boundary durably.
4. Treat transport failure or an ambiguous response as an unknown effect. Submit no subsequent batch while it is unresolved.
5. Confirm exact asset outputs and external fee effects from authoritative views, then persist designations and release only the resolved claims.
6. Refresh the snapshot and plan the remaining deficit.

Cancellation stops future batches, not reconciliation of an already-submitted batch. After a crash, recover the existing operation and reuse its confirmed outputs. Never clear the durable latch manually, infer no effect from elapsed time, or replay a transaction merely because Sage's response lacks a transaction ID.

Compatibility fallback is allowed before signing or after the existing authoritative no-effect procedure proves the prior attempt harmless. It is not allowed on timeout, unknown submission, identity mismatch or unresolved ownership. A partially completed direct run must preserve its confirmed outputs and use a fresh deficit plan, not restart full consolidation.

## Fees and progress

Preserve the selected base fee and the existing cost-aware preparation policy; do not silently introduce higher fees. Existing CAT consolidation can use a higher cost-scaled fee than the manual base, so the preview must show actual planned fees, not label every transaction with the base setting.

Direct batches need an explicitly tested fee/cost calculation covering their inputs and outputs. Bound the run by the displayed total fee budget. If validated construction needs a higher budget than approved, stop for review before signing. Partitioning must not silently exceed that budget. Retain all required final dedicated fee coins; CAT prep fees use separate, unassigned XCH inputs or a planned fee prerequisite, never fee coins protected for reuse.

Expose additive progress fields through the existing worker/status/UI route: execution mode, reused/missing coins, current and confirmed batches, planned/paid fees, current stage and elapsed confirmation time. Distinguish building, submitting, awaiting confirmation, recovery required and complete. Any remaining batch count is an estimate until its fresh snapshot is validated. Include prerequisite consolidation and compatibility-mode reasons visibly.

Do not report 100% or success before final verification and database persistence. Do not show a zero-second wait as the total transaction confirmation duration. Preserve existing response keys, escape server-sourced display text and use `slog` for diagnostics.

## Verification and acceptance

Use test-driven development with mocked wallet boundaries and isolated databases. Establish failures before implementation for:

- Exact tier outputs, unchanged reserves/headroom, deterministic selection, reuse and fee conservation; full, partial, one-sided and already-prepared plans.
- Input/output caps, fragmented funds, equal-sized outputs, duplicate IDs, wrong assets, missing change, additional unclaimed removals and insufficient fees.
- Wallet/config changes between planning and signing; unavailable or stale authoritative views; a submission accepted but response lost; crash at each durable boundary; cancellation and restart with no duplicate dispatch.
- CAT fee-coin ownership and fee change reconciliation; no borrowing of an already-used fee input and no erosion of final fee inventory.
- Unsupported unsigned building and proven-no-effect fallback; no fallback for ambiguous submissions; backwards-compatible recovery of old records.
- Desktop and HTTP progress paths, truthful confirmation timing, durable completion and specific failure reasons.

Performance fixtures must count actual planned wallet mutations/confirmation rounds, not only measure mocked wall-clock time. An eligible compact fixture with the observed 126 XCH and 76 CAT targets, sufficient funds and an available separate CAT fee input must need no more than two final-output batches, with no tier-pool or per-tier split transactions. An already-prepared fixture must need zero transactions. A fragmented fixture must use bounded deficit batches and report prerequisites honestly; do not claim a universal two-transaction result.

Run relevant wallet-adapter, prep lifecycle/crash/recovery, mutation-gate, desktop bridge and UI regressions; lint; then a fresh packaged build in a separate output directory. Package verification must exercise the direct mode without live wallet access and preserve startup/recovery behavior.

The completed live wallet must remain untouched while implementing. After offline verification, a user-executed packaged run with changed coin requirements must validate reserve/fee inventory and measure end-to-end time. A no-op run against already-prepared coins is not proof of reshaping performance. Five-minute success, live readiness or release readiness may be claimed only with corresponding evidence; blockchain confirmation time remains external.

## Delivery boundary

This change stays on a feature branch and is reviewed through a pull request before merging. The staged desktop/Splash fixes remain separately attributable. Do not modify the website or publish a release as part of design approval. The user approved this specification on 4 September, but requested Cancel All testing first and then reported the current bot-start failure. Resolve that testing prerequisite before starting the direct-batch implementation plan.
