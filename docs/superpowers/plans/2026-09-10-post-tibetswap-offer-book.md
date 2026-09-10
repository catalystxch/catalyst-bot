# CATalyst v1.4.0 Post-TibetSwap Offer-Book Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace CATalyst's retired TibetSwap assumptions with a safe, provider-capability offer-book engine and ship a verified v1.4.0 Windows release.

**Architecture:** Normalize Dexie, Splash, Sage, Spacescan, and Coinset observations into immutable evidence records. A confidence engine derives trusted market state, manipulation risk, publication state, and fill authority; the trading loop consumes those derived decisions and progressively withdraws offers when evidence degrades. Existing state migrates fail-closed and TibetSwap remains historical metadata only.

**Tech Stack:** Python 3, Flask, SQLite WAL, PyWebView, vanilla HTML/CSS/JavaScript, pytest, PyInstaller, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-10-post-tibetswap-offer-book-design.md`

## Global Constraints

- Work only on `codex/post-tibetswap-v1-4` in `C:\catalyst\.superpowers\post-tibetswap-v1-4`.
- Keep the live v1.3.21 bot stopped and its Sage offer book empty while changing architecture.
- Preserve mainnet, Sage TEST 7 fingerprint `736588221`, wallet ID `2`, ticker `MZ_XCH`, and asset ID `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105` for later live acceptance.
- Write a focused failing regression test and observe the expected failure before each production change.
- Use `Decimal` for prices and amounts, `slog` for logs, `database.py` for persistence, and `wallet.py` for wallet calls.
- Do not release or merge to `main` until both PCs complete the 24-hour acceptance gate.

---

### Task 1: Integrate and verify PR #213 startup/top-up recovery

**Files:**
- Modify: `desktop_app.py`
- Modify: `src/catalyst/bot_loop.py`
- Modify: `src/catalyst/coin_manager.py`
- Modify: `src/catalyst/database.py`
- Modify: `src/catalyst/legacy_startup_recovery.py`
- Modify: `src/catalyst/replacement_capacity.py`
- Modify: `src/catalyst/reservation_manager.py`
- Test: PR #213 test files

1. Inspect commit `1cabc77710a1d11903eda0ee00630cd44a8cec74` and classify every hunk against current invariants.
2. Run its focused tests against the current base or temporarily apply tests only to confirm the represented regressions.
3. Cherry-pick the commit without committing, remove unrelated or contradictory hunks, and resolve conflicts in favor of the approved spec.
4. Run the startup recovery, mutation-gate, top-up, reservation, replacement-capacity, publication-outbox, and fill-authority tests.
5. Commit as `fix: recover startup and live top-up state safely`.

### Task 2: Integrate and verify PR #208 native bulk cancellation recovery

**Files:**
- Modify: `desktop_app.py`
- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/blueprints/bot.py`
- Modify: `src/catalyst/legacy_startup_recovery.py`
- Test: `tests/test_legacy_startup_recovery.py`
- Test: `tests/test_plan_04_01_status_endpoints.py`

1. Inspect commit `1395ad23f4c98adfc2389707b9af7dedc0871cd3` against Task 1's resulting recovery model.
2. Add or retain a regression proving a completed native bulk cancellation clears stale lock counts and is correctly recovered after restart.
3. Apply only compatible changes and unify cancellation progress in the general and dedicated status surfaces.
4. Run focused startup, cancellation, mutation-gate, wallet-sync, and status endpoint tests.
5. Commit as `fix: recover native bulk cancellation consistently`.

### Task 3: Repair and integrate PR #207 Splash backpressure behavior

**Files:**
- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/blueprints/splash.py`
- Modify: `src/catalyst/splash_node.py`
- Test: `tests/test_plan_04_22_splash_settings.py`
- Test: `tests/test_splash_runtime_paths.py`

1. Add a failing concurrent regression showing duplicate Splash status requests can both miss the persisted cache.
2. Implement process-local in-flight coalescing with bounded wait, safe timeout, and no lock held during network I/O.
3. Apply the valid warning/backpressure changes from `d000cacee36955d7976226b7c53671c3712767ec`.
4. Verify healthy backpressure is quiet, genuine delivery failure remains visible, and concurrent callers share one probe.
5. Commit as `fix: coalesce Splash probes and classify backpressure`.

### Task 4: Add provider-capability contracts and normalized evidence

**Files:**
- Create: `src/catalyst/providers/__init__.py`
- Create: `src/catalyst/providers/models.py`
- Create: `src/catalyst/providers/protocols.py`
- Create: `src/catalyst/providers/registry.py`
- Create: `tests/test_provider_contracts.py`

1. Write failing tests for immutable `MarketQuote`, `BookObservation`, `PublicationObservation`, `ChainObservation`, provider health, provenance, monotonic timestamps, and capability lookup.
2. Implement typed dataclasses/protocols without binding the trading loop to provider names.
3. Reject invalid asset IDs, negative values, inverted books, future timestamps, and missing provenance.
4. Test serialization and deterministic provider registry ordering.
5. Commit as `feat: add provider capability contracts`.

### Task 5: Build Dexie, Splash, Sage, Spacescan, and Coinset adapters

**Files:**
- Create: `src/catalyst/providers/dexie.py`
- Create: `src/catalyst/providers/splash.py`
- Create: `src/catalyst/providers/sage.py`
- Create: `src/catalyst/providers/spacescan.py`
- Create: `src/catalyst/providers/coinset.py`
- Modify: existing provider clients only where normalization needs a narrow hook
- Create: `tests/test_provider_adapters.py`

1. Write fixtures and failing tests for normal, empty, stale, malformed, timeout, rate-limit, conflicting, and duplicate-source responses.
2. Normalize all observations without silently substituting zero or stale data.
3. Ensure asset ID is authoritative and metadata disagreements are explicit health evidence.
4. Mark Dexie and Splash observations of the same offer/coin ID as one independent fact.
5. Verify adaptive polling inputs and privacy-safe error messages.
6. Commit as `feat: normalize offer-book and chain providers`.

### Task 6: Persist evidence, trusted snapshots, and migration state

**Files:**
- Modify: `src/catalyst/database.py`
- Create: `src/catalyst/market_evidence.py`
- Create: `tests/test_market_evidence_persistence.py`
- Create: `tests/test_post_tibet_migration.py`

1. Write failing migration and round-trip tests for evidence, last trusted midpoint, `degraded_since`, source health, decision reason, and migration report.
2. Add idempotent schema migration and database-only accessors.
3. Retain detailed evidence for 30 days, then compact to summaries without deleting legacy TibetSwap history.
4. Fail closed if legacy ladder ownership cannot be proven; retain compliant owned offers and flag unsafe offers for cancellation.
5. Verify backup/restore and two consecutive migration runs.
6. Commit as `feat: persist market evidence and v1.4 migration state`.

### Task 7: Implement trusted market confidence and manipulation resistance

**Files:**
- Create: `src/catalyst/market_confidence.py`
- Modify: `src/catalyst/market_data_collector.py`
- Modify: `src/catalyst/price_engine.py`
- Modify: `src/catalyst/market_toxicity.py`
- Create: `tests/test_market_confidence.py`

1. Write failing table-driven tests for green/amber/red decisions, own-offer exclusion, deduplication, depth scaled to configured offer size, stale data, one-sided books, source conflict, and chain override.
2. Require material moves to persist for two or three refreshes unless a settled trade confirms sooner.
3. Add churn/manipulation scoring tied to risk preset, with hard caps and visible derived thresholds.
4. Make Dexie live book primary and settled trades validating evidence; never use historical TibetSwap data for a live decision.
5. Freeze the last trusted midpoint only for display/evidence during red confidence.
6. Commit as `feat: derive trusted offer-book market confidence`.

### Task 8: Implement degraded-mode withdrawal and recovery state machine

**Files:**
- Create: `src/catalyst/degraded_market.py`
- Modify: `src/catalyst/risk_manager.py`
- Modify: `src/catalyst/bot_loop.py`
- Create: `tests/test_degraded_market_state_machine.py`

1. Write failing clock-controlled tests for immediate create/requote freeze, immediate inner cancellation, middle cancellation at 3 minutes, outer/extreme/opportunity cancellation at 10 minutes, and pause.
2. Persist timers across restart and make every transition idempotent.
3. Require three healthy refreshes over at least 60 seconds before recovery.
4. Emit a desktop notification only on confidence transitions, not every poll.
5. Verify a manipulator cannot reset grace or recovery timers by flapping data.
6. Commit as `feat: withdraw safely during offer-book degradation`.

### Task 9: Enforce publication discovery and replacement lifecycle

**Files:**
- Modify: `src/catalyst/offer_lifecycle.py`
- Modify: `src/catalyst/offer_registry.py`
- Modify: `src/catalyst/dexie_manager.py`
- Modify: `src/catalyst/splash_manager.py`
- Modify: `src/catalyst/bot_loop.py`
- Test: `tests/test_publication_outbox.py`
- Create: `tests/test_offer_discovery_policy.py`

1. Write failing tests for independent Dexie/Splash submission, exact-offer discovery, duplicate evidence, partial provider failure, and the 90-second discovery deadline.
2. Require at least one provider to rediscover the exact offer; otherwise cancel via Sage.
3. Replace only after authoritative terminal proof and exponential backoff.
4. Prevent duplicate live offers through crashes, retries, and delayed discovery.
5. Verify cancel-all progress is consistent in all status APIs.
6. Commit as `feat: prove publication before offer replacement`.

### Task 10: Add fill-confidence authority and accounting gates

**Files:**
- Modify: `src/catalyst/fill_classifier.py`
- Modify: `src/catalyst/fill_tracker.py`
- Modify: `src/catalyst/offer_reconciliation.py`
- Modify: `src/catalyst/database.py`
- Create: `tests/test_fill_confidence.py`

1. Write failing cases for Observed, Probable, and Confirmed fills, including Sage delay, external cancellation, self-spend, chain conflict, reorg, and exact Coinset+Spacescan block-height agreement.
2. Allow accounting and replacement only for Confirmed fills.
3. Make Sage/confirmed chain authoritative; treat Dexie/Splash as hints.
4. On source conflict, prefer chain evidence but degrade confidence to amber and preserve evidence.
5. Commit as `feat: gate accounting on confirmed fill evidence`.

### Task 11: Recalibrate Smart Settings, risk presets, and opportunity orders

**Files:**
- Modify: `src/catalyst/blueprints/smart_defaults.py`
- Modify: `src/catalyst/risk_manager.py`
- Modify: `src/catalyst/offer_manager.py`
- Modify: `src/catalyst/config.py`
- Test: `tests/test_plan_04_10_smart_defaults_endpoint.py`
- Create: `tests/test_offer_book_smart_settings.py`

1. Write failing tests proving all three presets derive offer-book-only spreads, manipulation thresholds, minimum depth, churn limits, and profitability floor.
2. Include network fee, expected cancellation/requote cost, and configured minimum profit in every order decision.
3. Replace TibetSwap sniper behavior with conservative, bounded book-opportunity orders.
4. Rate-limit price wars and compete only inside the trusted profitable envelope.
5. Keep thresholds visible but not editable in v1.4.0.
6. Commit as `feat: recalibrate Smart Settings for offer books`.

### Task 12: Remove live TibetSwap dependencies and preserve compatibility

**Files:**
- Modify: `src/catalyst/price_engine.py`
- Modify: `src/catalyst/market_intel.py`
- Modify: `src/catalyst/api_server.py`
- Modify: relevant blueprints and config compatibility parsing
- Create: `tests/test_no_live_tibetswap_dependencies.py`

1. Write a failing source/runtime test proving no trading, Smart Settings, risk, price, slippage, or health path calls TibetSwap.
2. Remove runtime TibetSwap fetches and AMM-derived decisions.
3. Keep legacy fields read-only and explicitly `retired`/`unavailable` for one release.
4. Generate a one-time migration report explaining preserved history and retired live features.
5. Commit as `refactor: retire TibetSwap live market dependencies`.

### Task 13: Expose coherent APIs and rebuild every UI tab

**Files:**
- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/app_bridge.py`
- Modify: `bot_gui.html`
- Test: dashboard, offers, P&L, market, settings, logs, reset, help, and about endpoint tests
- Create: `tests/test_post_tibet_ui_contract.py`

1. Write failing API/HTML contract tests for market confidence, exact sources, timestamps, reason, degraded countdown, discovery state, fill confidence, and migration report.
2. Replace live TibetSwap cards and wording with offer-book liquidity and provider health.
3. Update Dashboard, Offers active/history, P&L, Market Intel, Settings live/setup, Logs, Data Reset safety gating, Help, About, startup/reload recovery, and notifications.
4. Preserve chronological Logs backfill and live advancement through tab switching.
5. Escape all server-sourced HTML and keep destructive controls gated.
6. Run browser verification at desktop dimensions and inspect console/network errors.
7. Commit as `feat: present post-TibetSwap confidence across the app`.

### Task 14: Verify coin prep and full lifecycle integration

**Files:**
- Modify only defects demonstrated by focused tests in coin prep, cancellation, recovery, or orchestration modules
- Create: `tests/test_post_tibet_full_lifecycle.py`

1. Add an isolated end-to-end mock-wallet test covering Smart Settings, fee coins, Coin Prep, start, publish, discover, fill, replace, stop, native bulk cancel, restart, and continue/start-over prompt.
2. Inject Dexie/Splash outages, stale books, source conflicts, provider recovery, Sage delay, and process restart at each durable boundary.
3. Verify no wallet mutation occurs under red confidence except required safety cancellations.
4. Run targeted integration tests, then `python -m pytest` from repository root.
5. Build with `python build.py` and smoke-test the unpacked artifact against isolated data.
6. Commit as `test: verify the post-TibetSwap trading lifecycle`.

### Task 15: Review, package, two-PC acceptance, merge, and release

**Files:**
- Modify: `_version.py` only through the release workflow/tag contract
- Modify: release notes and website download copy in their owning repositories/workflows
- Create: acceptance evidence under the repository's existing evidence convention

1. Run `ruff`, Bandit, relevant static checks, full serial pytest, build, and installer smoke test from a clean checkout.
2. Open a feature PR, review the complete diff including the incorporated #213/#208/#207 work, and require all CI checks green.
3. Install the candidate on this PC and the secondary PC from the candidate release asset; verify mainnet and exact TEST 7 identity before any live action.
4. On both PCs execute Smart Settings, variable-reserve Coin Prep with fees, start/stop, create/fill/requote, native cancel-all, restart recovery, and existing-ladder continue/start-over behavior.
5. Run controlled Dexie/Splash/Spacescan/Coinset outage and conflict scenarios and collect 24 hours of clean evidence on each PC.
6. Fix every confirmed CATalyst defect with a new failing regression and repeat affected acceptance gates.
7. Merge only after review and acceptance, tag `v1.4.0`, build/publish the Windows installer, update the live website, download it from the public website on a clean Windows environment, and verify installation/startup/version/hash.
8. Close or supersede PRs #213, #208, and #207 with links to the integrated commits.
9. Commit/release only when no unresolved confirmed defect remains.

## Verification Commands

Run from `C:\catalyst\.superpowers\post-tibetswap-v1-4`:

```powershell
python -m pytest <focused-test-files> -q
python -m pytest
python -m ruff check .
python -m bandit -r src/catalyst -x tests
python build.py
git diff --check
git status --short
```

## Stop Conditions

Stop live activity, preserve diagnostics, and request user action only if the verified wallet/network/asset changes, ownership cannot be proven, Sage signing fails repeatedly, balances conflict with chain evidence, offer counts exceed limits, errors become unbounded, or an external permission/credential blocks required GitHub or release operations.
