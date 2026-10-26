# Follow Fee Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind every wallet fee in a reviewed 48-hour Follow ladder to one durable cumulative 0.05 XCH ceiling, including safe shutdown after restart.

**Architecture:** A native review records one immutable wallet, configuration, offer-limit, expiry and fee consent. Every Follow offer intent carries that run ID. Fee-bearing operations obtain a fresh exact price and an atomic, append-only hold in the same run scope before wallet dispatch; unknown effects remain held until proved. Creation pauses when the shutdown reserve cannot be protected. The RED-market override consumes this run's read-only creation authority.

**Tech Stack:** Python, Flask/PyWebView, SQLite WAL, Sage wallet adapter, pytest, Playwright.

**Spec:** User instructions in this task: continuous Follow, 24 BUY + 24 SELL on each original-profile PC, maximum safely selectable XCH/MZ while retaining protected fee principal, 0.05 XCH cumulative fee cap per PC, 48-hour observation, one identical normal production-path build.

## Global Constraints

- Decimal for prices and XCH amounts; integer mojos for wallet fees.
- All database writes through `database.py`; all wallet calls through `wallet.py`.
- Preserve runtime lease, wallet identity, safety latch and exact unsigned pricing fences.
- Native final clicks require their applicable human confirmation; no CLI/API wallet-effect bypass.
- Keep PR272 and website PR93 draft/unpublished until verified.

## Review Focus

- A submitted but unconfirmed cancellation must hold its entire quoted fee across restart.
- A single-offer cancellation must not fall back to unapproved serial dispatch.
- A settings or wallet change must invalidate creation while retaining cleanup authority for prior offers.
- A Stop or expiry must remove creation authority without stranding approved cleanup.
- A new fee session or process restart must not reset the previous run's 0.05 XCH accounting.

---

### Task 1: Durable native run binding and read-only creation authority

**Files:** `src/catalyst/database.py`, `tests/test_follow_fee_authority.py`, native review route and GUI.

**Interfaces:** `create_follow_run_authority(...)` persists one reviewed run; `get_follow_creation_authority(identity, configuration_sha256, now_epoch)` returns the exact immutable run binding or a fail-closed reason. It never dispatches a wallet effect.

- [x] Write a failing test for exact run binding, config drift and expiry.
- [x] Reproduce the missing function failure.
- [x] Add immutable schema and reader; run focused tests.
- [x] Add unresolved-hold test and fail-closed reader state.
- [ ] Bind creation to an exact native review/consent event and verify copied original-profile DB migration.
- [x] Add append-only Stop lifecycle and read-only exact-scope cleanup reader that survives Stop/expiry; unresolved fee effects still block new cleanup dispatch. Native cleanup authorization and wallet-effect pricing remain pending.

Native consent boundary to implement next: the server must persist an immutable,
short-lived review for the exact wallet fingerprint/network/asset, settings
digest, 24/24 limits, 48-hour expiry, maximum safe principal, fee approval ID,
0.05 XCH ceiling and protected shutdown reserve. The final native click may
submit only that review ID and digest. In one database transaction, compare the
still-current review and approval, record a single-use consent, and create the
run authority. `create_follow_run_authority` must reject arbitrary 64-hex
`consent_id` values; current tests use such values only for the provisional
reader and must be updated to exercise the real review transition. Approval
must never start the bot or dispatch a wallet effect.

Progress: the database now persists an immutable five-minute review and its
digest, and the run-authority transition rejects arbitrary IDs, changed terms,
expired reviews and replay. This is DB-only. The native server route must still
derive the review terms from verified wallet/configuration and display them to
the human; the final native click must submit the exact review ID/digest. The
review is not yet a user consent by itself.

Principal review groundwork: `follow_principal.py` now reads the existing
identity-verified, complete selectable Sage coin snapshot, combines it with
durable fee-reserve purpose, and calculates an exact atomic trading upper
bound after the configured wallet reserves and the larger of approved fee
ceiling or configured fee-pool principal. Its inventory and proposal digests
change when coin evidence or material reserve terms change. It cannot grant
consent or wallet effects. The native review still must bind this digest and
recheck the same live inventory at final consent; offer-sized Coin Prep and
24/24 affordability remain to be proved before Start.

The read-only Follow principal preview now requires a current, completed
standalone Coin Prep fee approval. It verifies the stored approval scope and
plan hashes, matches the wallet identity to a fresh selectable-coin snapshot,
and rechecks approval accounting and configuration after that read. The
response carries exact atomic amounts as JSON strings plus a proposal digest;
the browser API and native bridge share the same handler. It records no
consent or run authority. Persisting a single-use principal-bound review and
rechecking it at the final native click remain pending.
The preview also reports the approved Coin Prep plan's replacement-coin counts
and atomic totals by asset. These figures must be compared with 24 slots per
side and current principal; they do not prove contemporaneous price fit or
the exact live ladder's slot allocation.

The immutable Follow review and resulting authority now store the exact
principal proposal digest; changing that digest when consuming the review is
rejected. The creation-authority reader exposes the frozen digest for a future
Start recheck. The reviewed digest still needs to be supplied from a trusted
server review route and compared with fresh inventory at final consent and
before offer creation; the database field alone does not prove that check.

### Task 2: Attribute all Follow intents and fee effects to the run

**Files:** `src/catalyst/offer_manager.py`, `src/catalyst/bot_loop.py`, `src/catalyst/database.py`, focused tests.

**Interfaces:** Follow intents carry `follow:<run_id>:<classification>` while preserving normal/book-opportunity classification. Only matching active authority permits new creation. Existing legacy intents do not inherit a new run.

- [ ] Write a failing test for a new Follow intent created without authority and for a mismatched run ID.
- [ ] Enforce authority before persisted create and before final wallet submission.
- [ ] Verify both normal and book-opportunity intent purpose and restart recovery.

Progress: exact `follow:<run_id>:normal_lifecycle|book_opportunity` purpose now
rechecks the verified durable run at canonicalization, before intent preparation,
and immediately before wallet submission. A regression reproduced wallet-boundary
revocation when the final check was absent. The task remains open until every
ordinary Follow producer attaches this purpose; legacy unscoped producers must
be fenced rather than silently inheriting a new run.
The ladder builder now accepts an exact run ID and labels both ordinary and
book-improving offers without losing their classification. BotLoop's main
replenishment producer reads the current durable run before creating and passes
that ID. A missing or revoked authority pauses that producer. Requote cold
start and staged refresh still call the ladder builder without a run ID, as do
three BoostManager handoff/cascade producers. These must be bound to the exact
parent/new-run scope or fenced before enabling a Follow run. Direct legacy
`create_offer_with_retry` paths also need the same boundary audit.

Central producer fence: canonical creation must reject unscoped Follow offers
while an unexpired run exists for the verified wallet and asset. The fence must
hold after settings drift or Stop; `current_scope()` alone cannot detect those
cases because it deliberately raises when creation authority is unavailable.
Recheck at the final wallet boundary, then bind or disable each Boost, Sniper,
requote and refresh producer. An ended run must require an explicit new mode
decision instead of falling back to unscoped creation during acceptance.

### Task 3: Exact priced cancellation hold for every Follow path

**Files:** `src/catalyst/offer_manager.py`, `src/catalyst/database.py`, fee pricing/dispatch helpers, focused tests.

**Interfaces:** The canonical Follow run ID resolves one fee approval scope. Each batch, including a singleton, obtains exact unsigned cost, fresh quote, atomic hold, dispatch recheck and terminal/no-effect outcome. No generic unpriced fallback is permitted.

- [x] Write a failing test proving a Follow-labelled cancellation reaches the generic unapproved route; reproduce the bypass before adding its fail-closed boundary.
- [x] Reproduce the unapproved Follow cancellation path and add an early fail-closed guard for scoped, malformed and singleton intents. This is a temporary safety boundary; the approved priced path remains required.
- [ ] Cover routine requote, degraded withdrawal, Stop, Cancel All, expiry and shutdown call sites.
- [ ] Enforce full-book shutdown reserve at creation and cancellation planning.
- [ ] Recheck the same approval, run, wallet, intent roots, fee coin and quote under the final dispatch lock.
- [ ] Verify crash/restart and ambiguous submitted outcomes remain held without duplicate effect.

### Task 4: Native configuration, integration and release gates

**Files:** Native GUI, Flask routes/AppBridge, integration and browser tests, build workflow.

- [ ] Present exact wallet, pair, 24/24 limits, duration, principal, 0.05 cap and shutdown reserve for native approval.
- [ ] Require financial creation authority and scoped risk consent before Start; do not auto-start on either approval.
- [ ] Show spent/held/remaining fees and clear review-needed reasons in GUI.
- [ ] Run relevant full tests, Ruff, copied original-profile migration/replay, clean default Windows build, Defender and independent review.
- [ ] Use the same exact built artifact on both original profiles after action-time executable confirmation and human wallet authentication.
- [ ] Begin new identity-bound 24-hour acceptance only after both live ladders are stable and fully audited.
