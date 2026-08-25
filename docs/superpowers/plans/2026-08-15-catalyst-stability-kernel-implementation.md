# CATalyst Stability Kernel Implementation Plan

> **For Codex:** Execute this plan task-by-task using the test-driven-development
> workflow. Do not proceed past a red test without confirming it fails for the
> intended reason. Use the verification-before-completion workflow before any
> completion claim.

**Goal:** Integrate the strongest stability mechanisms from the private V50.11
reference into current CATalyst, using SQLite-backed fail-closed offer operations,
then verify the result locally and on the authorised Sage `TEST 7` mainnet wallet.

**Architecture:** Add small pure policy modules around a durable schema owned by
`database.py`. Record every wallet intent before its effect, normalize wallet
outcomes into typed results, block mutation behind a durable latch and single-run
lease, and reconcile ambiguous operations from authoritative Sage evidence. Extend
the same primitives to replacement capacity, coin prep, publication, and long-gap
recovery. Preserve `wallet.py` as the only adapter entry point and existing
AppBridge response contracts.

**Tech stack:** Python 3.12, SQLite WAL, Flask, PyWebView, `Decimal`, pytest,
PyInstaller. Reference behavior may be adapted from the private bundle under
`stable/src/src/catalyst` and `stable/src/tests`, but its CSV persistence is not
copied.

**Baseline:** `3300 passed, 13 skipped, 3 warnings, 42 subtests passed` on commit
`15f6aab` before implementation.

---

## Task 1: Harden Sage configuration, identity, and error output

**Files:**

- Modify: `src/catalyst/config.py`
- Modify: `src/catalyst/wallet.py`
- Modify: `src/catalyst/wallet_sage.py`
- Test: `tests/test_sage_config_hardening.py`
- Test: `tests/test_wallet_sage_signing_guard.py`
- Test: `tests/test_wallet_sage_startup_readiness.py`

1. Write failing tests proving certificate resolution prefers explicit canonical
   config, then the platform Sage `wallet.crt`/`wallet.key`, and never silently
   uses a rejected generated certificate.
2. Add a failing CP1252 test proving every RPC exception path uses `_console()` or
   `slog` and does not raise `UnicodeEncodeError`.
3. Add a failing identity snapshot test covering name, integer fingerprint,
   network, key kind, signing capability, and observation timestamp.
4. Run:

   `python -m pytest tests/test_sage_config_hardening.py tests/test_wallet_sage_signing_guard.py tests/test_wallet_sage_startup_readiness.py -q`

   Confirm the new tests fail for missing deterministic resolution/snapshot logic.
5. Add typed config access and pure certificate-path resolution. Keep process
   environment overrides used by tests, but remove independent adapter decisions
   where `cfg` is canonical.
6. Add `get_wallet_identity()` as a read-only wallet API for both Sage and Chia;
   Chia returns the closest supported identity fields with explicit unknowns.
7. Route RPC console failures through the encoding-safe logger.
8. Re-run the focused tests and commit:

   `fix: harden Sage identity and certificate resolution`

## Task 2: Add canonical cancellation outcomes

**Files:**

- Create: `src/catalyst/cancel_outcomes.py`
- Create: `tests/test_cancel_outcomes.py`
- Modify: `tests/test_wallet_sage_bulk_cancel_method.py`
- Reference: private `cancel_outcomes.py` and its cancel tests

1. Write table-driven failing tests for `CANCEL_CONFIRMED`,
   `CANCEL_SUBMITTED_UNCONFIRMED`, `CANCEL_FAILED`, and `CANCEL_UNKNOWN`.
2. Cover timeout, disconnect, malformed JSON, 404/missing offer, mempool conflict,
   already-including, explicit rejection, transaction ID, spend identity, bounded
   raw evidence, and evidence digests.
3. Require submitted outcomes to carry a transaction ID or exact spend identity.
   Assert `success` is true only for confirmed cancellation; expose separate
   `submitted` and `reconciliation_required` fields.
4. Run `python -m pytest tests/test_cancel_outcomes.py -q` and confirm red.
5. Implement the pure normalizer without wallet/database imports.
6. Re-run focused cancellation unit tests and commit:

   `feat: add typed fail-closed cancellation outcomes`

## Task 3: Add the durable stability schema and repository API

**Files:**

- Modify: `src/catalyst/database.py`
- Create: `tests/test_stability_schema.py`
- Modify: `tests/test_plan_02_30_database_unit.py`

1. Write failing migration tests from empty, current, and representative legacy
   databases. Assert idempotency and `PRAGMA integrity_check` success.
2. Define `offer_intents`, `offer_operation_journal`, `runtime_safety_latch`,
   `runtime_mutation_lease`, worker delegation, and `publication_outbox` through
   `database.py` migrations.
3. Add uniqueness/index tests for trade ID, offer hash, journal event ID,
   operation/attempt/phase, publication idempotency key, and singleton rows.
4. Add repository tests for intent preparation/finalization, append-only events,
   unresolved blockers, latch transitions, compare-and-set lease acquisition,
   heartbeat, release, and delegation expiry.
5. Run `python -m pytest tests/test_stability_schema.py tests/test_plan_02_30_database_unit.py -q` and confirm red.
6. Implement only database functions; no new module may issue raw SQL.
7. Store atomic amounts and hashes exactly, validate JSON before commit, use short
   `BEGIN IMMEDIATE` transactions for compare-and-set operations, and never keep a
   transaction open across RPC.
8. Re-run focused tests and commit:

   `feat: add durable offer operation schema`

## Task 4: Add pure registry policy and transition authorization

**Files:**

- Create: `src/catalyst/offer_registry.py`
- Create: `tests/test_offer_registry.py`
- Modify: `src/catalyst/offer_lifecycle.py`
- Modify: `tests/test_offer_lifecycle.py`
- Reference: private `offer_registry_policy.py` tests, not its CSV persistence

1. Write failing state-table tests for prepared, submitted-unconfirmed, created,
   visible, cancel-requested, terminal, unknown, conflicted, and quarantined
   states.
2. Add failing authorization tests for wallet/network mismatch, ambiguous match,
   protected/non-owned offer, duplicate slot, missing selected coins, invalid
   parent/child lineage, and terminal mutation without proof.
3. Run `python -m pytest tests/test_offer_registry.py tests/test_offer_lifecycle.py -q` and confirm red.
4. Implement immutable dataclasses/enums and pure transition functions. Keep
   persistence in `database.py` and amounts as atomic integers/exact strings.
5. Adapt current lifecycle signals to the stricter policy without deleting
   backward-compatible coarse status mapping.
6. Re-run tests and commit:

   `feat: enforce durable offer registry policy`

## Task 5: Add durable mutation latch and single-writer lease

**Files:**

- Create: `src/catalyst/mutation_gate.py`
- Create: `tests/test_mutation_gate.py`
- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/coin_prep_worker.py`

1. Write failing tests for process-local and durable latch behavior across module
   reload/restart.
2. Write competing-process tests proving only one run owns mutation, an expired
   lease is not stolen while the prior PID is alive, and takeover requires
   in-flight reconciliation.
3. Write worker delegation tests scoped to parent run, operation, purpose,
   fingerprint/network, and expiry.
4. Run `python -m pytest tests/test_mutation_gate.py -q` and confirm red.
5. Implement `trip`, `status`, `require_allowed`, `release_resolved`, lease
   acquisition/heartbeat/release, and worker delegation helpers over `database.py`.
6. Initialize the gate before Flask serves mutating routes. A second process stays
   read-only and reports the owning lease without exiting diagnostics.
7. Re-run tests and commit:

   `feat: add durable mutation gate and run lease`

## Task 6: Enforce fresh wallet identity at mutation boundaries

**Files:**

- Modify: `src/catalyst/mutation_gate.py`
- Modify: `src/catalyst/wallet.py`
- Modify: `src/catalyst/wallet_sage.py`
- Modify: `src/catalyst/wallet_chia.py`
- Create: `tests/test_wallet_identity_gate.py`

1. Write failing tests for fingerprint, network, key kind, signing capability,
   stale observation, unreachable wallet, and identity changing between initial
   preflight and the adapter call.
2. Test that read-only calls remain available while mutation is blocked.
3. Run `python -m pytest tests/test_wallet_identity_gate.py -q` and confirm red.
4. Implement a fresh, noncached identity check immediately around every offer
   create/cancel and transaction/split/combine submission exported by `wallet.py`.
   Keep a second orchestration preflight for useful early errors.
5. Ensure AppBridge/API paths return `{success: False, error, reason}` rather than
   raising into JavaScript.
6. Re-run tests and commit:

   `feat: bind wallet mutations to fresh identity`

## Task 7: Journal offer creation before Sage effects

**Files:**

- Modify: `src/catalyst/offer_manager.py`
- Modify: `src/catalyst/database.py`
- Modify: `src/catalyst/wallet.py`
- Create: `tests/test_offer_create_journal.py`
- Modify: `tests/test_offer_manager_coin_ids.py`
- Modify: `tests/test_parallel_offers.py`

1. Write failing crash-injection tests at: before intent commit, after intent
   commit, before Sage call, after Sage response, before trade-ID commit, and after
   trade-ID commit.
2. Assert retry never creates twice; unresolved prepared/submitted creation trips
   the latch and retains selected-coin reservations.
3. Add racing thread tests for the same slot and same selected coin.
4. Run the new tests and confirm red.
5. Refactor `create_offer_with_retry()` to build an immutable intent, prepare it
   transactionally, call `wallet.create_offer()` outside the transaction, then
   record confirmed/failed/unknown outcome.
6. Keep existing offer-size uniqueness and post-create locked-input verification;
   make their evidence part of finalization.
7. Re-run offer creation/parallel tests and commit:

   `feat: journal offer creation before wallet effects`

## Task 8: Integrate typed cancellation and durable reconciliation blockers

**Files:**

- Modify: `src/catalyst/wallet_sage.py`
- Modify: `src/catalyst/wallet_chia.py`
- Modify: `src/catalyst/offer_manager.py`
- Modify: `src/catalyst/database.py`
- Create: `tests/test_offer_cancel_journal.py`
- Modify: `tests/test_wallet_sage_cancel_batch.py`
- Modify: `tests/test_plan_03_12_cancel_all_flow_integration.py`
- Modify: `tests/test_bot_health_pending_cancels.py`

1. Write failing tests proving 404, absence, timeout, and an unconfirmed submission
   do not mark the database cancelled or release coins.
2. Write batch tests where outcomes differ per trade ID and one ambiguous member
   blocks only the correct cohort plus global mutation until reconciled.
3. Add retry-exhaustion tests proving CATalyst never marks cancellation merely to
   stop retrying.
4. Run focused cancel tests and confirm red.
5. Normalize adapter results through `cancel_outcomes.py`, persist request before
   submission, and append result evidence after submission.
6. Replace `CANCEL_PENDING_METHODS` string-policy branches with typed outcome
   helpers while retaining compatibility fields for existing callers/tests.
7. Re-run all cancel/pending-cancel tests and commit:

   `feat: make cancellation outcomes durable and fail closed`

## Task 9: Add authoritative terminal reconciliation

**Files:**

- Create: `src/catalyst/offer_reconciliation.py`
- Create: `tests/test_offer_reconciliation.py`
- Modify: `src/catalyst/fill_tracker.py`
- Modify: `src/catalyst/bot_health.py`
- Modify: `src/catalyst/database.py`
- Reference: private `authoritative_fill_reconciliation.py` and
  `cancel_reconciliation.py`

1. Adapt the reference evidence fixtures into failing tests for exact fill,
   exact cancellation return flow, active offer, local expiry, missing pages,
   fee-bearing/grouped cancellation, same-wallet self-take, conflicts, and unknown.
2. Add pagination/filter tests proving Sage's ignored `include_completed` and
   `end` values are normalized locally with completeness metadata.
3. Run `python -m pytest tests/test_offer_reconciliation.py -q` and confirm red.
4. Implement read-only evidence loaders plus a pure classifier. Require source
   timestamps and exact asset/amount/input/height matches.
5. Commit a terminal transition and fill record only through one narrow database
   transaction after registry authorization.
6. Make unknown/conflict trip the latch without wallet mutation.
7. Re-run fill, pending-cancel, and status-mapping tests and commit:

   `feat: reconcile terminal offers from authoritative proof`

## Task 10: Recover safely at startup and expose diagnostics

**Files:**

- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/bot_loop.py`
- Modify: `src/catalyst/app_bridge.py`
- Modify: `src/catalyst/database.py`
- Create: `tests/test_stability_startup_recovery.py`
- Create: `tests/test_stability_status_api.py`
- Modify: `tests/test_startup_offer_recovery_public_post.py`

1. Write failing tests proving startup remains read-only until DB integrity,
   lease, identity, freshness, unresolved operations, reservation reconciliation,
   and publication claims are checked.
2. Cover prepared creation, submitted cancel, stale lease, stale Sage snapshot,
   contradictory history, and clean restart.
3. Write API/AppBridge contract tests for stable reason codes, blocker counts,
   redacted identity, source age, and recommended action.
4. Run focused tests and confirm red.
5. Add a startup coordinator that performs ordered read-only recovery before
   enabling the mutation gate.
6. Add `/api/safety/status` and an AppBridge method returning structured dicts.
7. Re-run startup/API tests and commit:

   `feat: recover stability state before enabling mutations`

## Task 11: Add staged refresh and verified lineage

**Files:**

- Create: `src/catalyst/refresh_safety.py`
- Create: `tests/test_refresh_safety.py`
- Modify: `src/catalyst/offer_manager.py`
- Modify: `src/catalyst/bot_loop.py`
- Modify: `src/catalyst/database.py`
- Reference: private `refresh_safety.py` and registry lineage tests

1. Write failing pure tests for no-op, staged batches, overlap capacity, explicit
   operator mass cancellation, and deterministic batch ordering.
2. Write integration tests proving a parent cannot retire until the exact child
   is confirmed and required visibility is durable.
3. Cover crashes between child intent, child creation, publication, parent cancel,
   and lineage commit.
4. Run focused tests and confirm red.
5. Implement refresh plans and exact bidirectional parent/child lineage. Preserve
   current requote pricing, storm protection, and position safety.
6. Re-run offer manager/bot-loop tests and commit:

   `feat: stage offer refresh with verified lineage`

## Task 12: Separate replacement capacity and harden coin prep

**Files:**

- Create: `src/catalyst/replacement_capacity.py`
- Create: `tests/test_replacement_capacity.py`
- Modify: `src/catalyst/coin_manager.py`
- Modify: `src/catalyst/coin_prep_worker.py`
- Modify: `src/catalyst/database.py`
- Modify: `tests/test_coin_prep_post_drift_failure.py`
- Modify: `tests/test_coin_prep_confirmed_views.py`
- Reference: private `replacement_capacity.py`, `coin_prep_requirements.py`, and
  tier semantics tests

1. Write failing tests for lifecycle, replacement, fill-response, operator
   recovery, top-up, and fee purposes.
2. Prove one purpose cannot silently consume another purpose's floor and that
   ambiguous coins count toward no spendable capacity.
3. Add idempotent split/combine intent tests, post-drift verification, restart
   recovery, worker delegation expiry, and exact wallet identity checks.
4. Run focused tests and confirm red.
5. Implement pure readiness decisions and persist purpose through coin
   designation/reservation functions in `database.py`.
6. Journal coin-prep mutations and require authoritative post-operation coin
   views before success.
7. Re-run coin manager/prep suites and commit:

   `feat: separate replacement capacity and coin purposes`

## Task 13: Add durable publication outbox

**Files:**

- Create: `src/catalyst/publication_outbox.py`
- Create: `tests/test_publication_outbox.py`
- Modify: `src/catalyst/dexie_manager.py`
- Modify: `src/catalyst/splash_manager.py`
- Modify: `src/catalyst/database.py`
- Modify: `src/catalyst/bot_loop.py`
- Reference: private Splash publication idempotency tests

1. Write failing tests for transactional enqueue, duplicate enqueue, claim,
   success, retry with backoff, crash after remote success, stale claim recovery,
   and terminal suppression.
2. Assert network + offer fingerprint + epoch is the idempotency key and remote
   visibility never changes wallet terminal state.
3. Run focused tests and confirm red.
4. Implement the outbox repository/worker and adapt Dexie/Splash flush paths.
5. Re-run Splash/Dexie/startup-publication tests and commit:

   `feat: publish offers through durable outbox`

## Task 14: Add long-gap/session recovery and quarantine constraints

**Files:**

- Create: `src/catalyst/runtime_recovery.py`
- Create: `tests/test_long_gap_recovery.py`
- Modify: `src/catalyst/bot_loop.py`
- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/database.py`
- Reference: private long-gap, session recovery, and fresh-start tests

1. Write failing fake-clock tests for sleep, VM pause, wall-clock rollback/jump,
   stale last-known-good wallet state, and delayed publication/cancel responses.
2. Write quarantine tests proving evidence is archived but mutation remains
   blocked unless complete authoritative absence and owned/unlocked inputs are
   proven.
3. Run focused tests and confirm red.
4. Add monotonic-gap detection and route recovery through the same startup
   read-only coordinator.
5. Add explicit operator quarantine with immutable evidence manifest/digest.
6. Re-run tests and commit:

   `feat: recover safely after long gaps and quarantines`

## Task 15: Add operator-facing safety diagnostics

**Files:**

- Modify: `src/catalyst/bot_gui.html`
- Modify: `src/catalyst/app_bridge.py`
- Modify: `src/catalyst/api_server.py`
- Create: `tests/test_safety_diagnostics_ui.py`
- Modify: `tests/test_bot_gui_offer_filters.py`

1. Write failing API serialization and HTML safety tests.
2. Add a compact status panel showing allowed/blocked, reason code, freshness,
   unresolved counts, lease owner state, registry/lineage/publication counts, and
   safe next action.
3. Render server values through `escapeHtml()` and data attributes/event
   delegation; add no inline interpolated handlers.
4. Keep detailed evidence redacted and operator actions explicit.
5. Run focused UI/API tests and commit:

   `feat: expose stability diagnostics to operators`

## Task 16: Complete automated regression and build verification

**Files:**

- Modify as required by failures only; do not weaken tests or invariants
- Add: `docs/testing/stability-kernel-verification.md`

1. Run all new stability tests together with no order dependency.
2. Run existing cancellation, lifecycle, wallet, offer-manager, coin-prep,
   startup, Splash, and database suites.
3. Run repository quality/security commands available in
   `requirements-dev.txt`/CI (ruff, bandit, vulture or their configured subsets).
4. Run `python -m pytest tests -q` and record the fresh exact count.
5. Run `python build.py` from the worktree and verify the built executable starts
   with an isolated non-live `CMM_DATA_DIR` and reaches the status endpoint.
6. Write the verification document with commands, timestamps, results, and known
   limitations. Commit:

   `test: verify stability kernel and local build`

## Task 17: Run authorised TEST 7 mainnet acceptance

**Files:**

- Create: `scripts/test7_stability_lab.py`
- Create: `tests/test_test7_lab_guard.py`
- Update: `docs/testing/stability-kernel-verification.md`

1. Write failing dry-run guard tests proving the lab refuses every mutation unless
   Sage freshly reports `TEST 7`, fingerprint `736588221`, mainnet, BLS, and
   signing enabled. The script defaults to dry-run and requires an explicit live
   flag plus isolated `CMM_DATA_DIR`.
2. Implement a checkpointed lab runner using public CATalyst APIs and the durable
   journal; do not call `wallet_sage` directly.
3. Run read-only inventory and reconcile Sage's unfiltered offer history.
4. Run one small wide-spread SBX/XCH create/publish/cancel lifecycle.
5. Run restart checkpoints, Sage disconnect/stale-read freeze, and long-gap
   recovery without changing the Sage profile.
6. Run staged multi-offer replacement and verify coin purpose/lineage.
7. Produce a genuine on-chain fill using an external fill if practical or an
   isolated same-wallet self-take with disjoint verified inputs.
8. Run a sustained soak with periodic invariant snapshots. On any invariant
   failure, stop mutation, preserve evidence, reproduce in automation, fix, and
   restart the acceptance sequence.
9. Final-reconcile Sage history, SQLite registry/journal, publication outbox,
   reservations, offer book, and balances. Require zero unresolved blockers.
10. Add redacted evidence and final outcomes to the verification document and
    commit:

    `test: complete TEST 7 mainnet stability acceptance`

## Final completion gate

1. Re-run `git diff --check`, all focused stability suites, full pytest, and the
   clean build command from fresh state.
2. Inspect `git status`, committed diff, migration behavior, and verification
   evidence.
3. Confirm the goal's explicit conditions are all satisfied and no required work
   remains.
4. Mark the goal complete and report the local branch/worktree/build locations.
5. Do not push, create a PR, or merge to GitHub `main` without a new explicit user
   request.
