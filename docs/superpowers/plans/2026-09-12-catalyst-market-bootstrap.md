# CATalyst Market Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any exact Chia CAT launch or rebuild a bounded non-custodial Dexie market while isolating wallet funds, resisting self-referential price manipulation, coordinating independent makers, and preserving CATalyst's authoritative Sage lifecycle.

**Architecture:** Add a pure Bootstrap campaign policy beside the existing Market Follow confidence engine. Persist exact campaign authorization and evidence before effects; derive a capped `BootstrapDecision` that the existing Smart Settings, Coin Prep, offer lifecycle, and bot loop must consume. Canonical manifests and privacy-bounded proof reports use Sage's interactive WalletConnect `chia_signMessageByAddress` command without granting WalletConnect any trading authority; standard offers remain default and partial offers remain capability-disabled until every required Sage and distribution function is proven.

**Tech Stack:** Python 3, `Decimal`, Flask, SQLite WAL, Sage mTLS RPC, vanilla HTML/CSS/JavaScript, pytest, PyInstaller, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-10-post-tibetswap-offer-book-design.md`

## Global Constraints

- Work only on `codex/post-tibetswap-v1-4` in `C:\catalyst\.superpowers\post-tibetswap-v1-4`.
- Preserve Sage as the sole wallet and v1.4 exact-fill authority; Dexie/Splash never authorize wallet state.
- Never infer a Bootstrap anchor. It is accepted only as exact XCH-per-CAT `Decimal` input or deterministically derived from exact supply and implied XCH valuation.
- A campaign may access only its persisted fixed XCH, CAT, fee, and opt-in subsidy budgets. The subsidy defaults to zero; wallet balance changes never enlarge authorization.
- Initial capacity is 10%; later capacity is exactly 25%, 50%, and 100% under the approved evidence thresholds.
- The default hard price corridor is `[anchor * 0.50, anchor * 2.00]`; automatic movement is capped at 5% per rolling hour and 20% per rolling 24 hours.
- Three standard atomic offers are created per funded side. One-sided Bootstrap is allowed and explicitly labelled.
- Campaign expiry is seven days. The loss stop is 5% of accepted campaign value and requires authoritative cancellation plus manual restart.
- Stop new creation/requotes at 80% fee-budget use and reserve 20% for cancellation.
- Use `Decimal` for all prices/amounts, integer mojos for coins, `slog` for logging, `database.py` for persistence, and `wallet.py` for wallet effects.
- Experimental partial offers are visible but disabled unless create, cancel, state, lineage, fill, and public-discovery capabilities are all proven. There is no force-enable path.
- WalletConnect is used only for explicit manifest and participation-report message signatures. Every request and response is bound to an immediate Sage RPC identity recheck, expected `chia:<network>:<fingerprint>` account, expected signing address, canonical message digest, expiry, and one-time request ID. It never creates, signs, submits, or cancels a spend.
- A public Reown project ID is configuration, not a secret. Never reuse Sage's wallet-side project ID. If CATalyst's project ID is absent, WalletConnect is unavailable, or the user rejects/times out, core Bootstrap remains usable but no verified signature or directory submission is produced.
- Every production edit starts with a focused failing regression, observes the intended failure, receives the smallest safe implementation, and ends with targeted verification plus a commit.
- Do not merge, tag, release, or update the public website before the existing two-PC 24-hour acceptance gate passes.

---

### Task 1: Add immutable Bootstrap campaign policy

**Files:**
- Create: `src/catalyst/bootstrap_campaign.py`
- Create: `tests/test_bootstrap_campaign_policy.py`

**Interfaces:**
- Consumes: timezone-aware UTC `datetime`, exact `Decimal` prices and amounts, integer confirmed-fill counters.
- Produces: `BootstrapCampaign`, `BootstrapEvidence`, `BootstrapDecision`, `CampaignMode`, `CampaignStage`, `CampaignSide`, `CampaignStopReason`, `derive_anchor_from_valuation()`, and `evaluate_bootstrap_campaign()`.

- [ ] **Step 1: Write the failing validation and default-corridor tests**

```python
def test_campaign_isolated_budgets_and_default_corridor():
    campaign = make_campaign(anchor_price=Decimal("0.01"))
    assert campaign.minimum_price == Decimal("0.005")
    assert campaign.maximum_price == Decimal("0.02")
    assert campaign.initial_deployment_fraction == Decimal("0.10")
    assert campaign.subsidy_budget_xch == Decimal("0")

def test_invalid_campaign_cannot_reach_outside_budget():
    with pytest.raises(ValueError, match="xch budget"):
        make_campaign(xch_budget=Decimal("-1"))
```

- [ ] **Step 2: Run the focused tests and observe the missing-module failure**

Run: `python -m pytest tests/test_bootstrap_campaign_policy.py -q`

Expected: collection fails because `bootstrap_campaign` does not exist.

- [ ] **Step 3: Implement exact immutable types and validation**

```python
class CampaignStage(str, Enum):
    BOOTSTRAP = "bootstrap"
    DISCOVERY_25 = "discovery_25"
    DISCOVERY_50 = "discovery_50"
    ESTABLISHED = "established"
    UNSAFE = "unsafe"
    STOPPED = "stopped"

@dataclass(frozen=True, slots=True)
class BootstrapDecision:
    authorized: bool
    stage: CampaignStage
    deployment_fraction: Decimal
    anchor_price: Decimal
    minimum_price: Decimal
    maximum_price: Decimal
    allowed_sides: frozenset[CampaignSide]
    cooldown_sides: frozenset[CampaignSide]
    stop_reason: CampaignStopReason | None
    reason_codes: tuple[str, ...]
```

Reject a non-64-hex asset ID, non-mainnet/testnet network string, missing wallet binding, nonpositive anchor/corridor, corridor excluding the anchor, negative budget, absent funded side, subsidy above its explicit budget, naive timestamps, expiry beyond seven days, and any `float` monetary input.

- [ ] **Step 4: Add and pass exact anchor-valuation tests**

```python
def test_anchor_from_supply_and_xch_valuation_is_exact():
    assert derive_anchor_from_valuation(
        circulating_supply=Decimal("1000000"),
        implied_valuation_xch=Decimal("250"),
    ) == Decimal("0.00025")
```

Run: `python -m pytest tests/test_bootstrap_campaign_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the pure policy foundation**

```powershell
git add src/catalyst/bootstrap_campaign.py tests/test_bootstrap_campaign_policy.py
git commit -m "feat: define isolated bootstrap campaigns"
```

### Task 2: Implement staged capacity, movement, cooldown, and stops

**Files:**
- Modify: `src/catalyst/bootstrap_campaign.py`
- Modify: `tests/test_bootstrap_campaign_policy.py`

**Interfaces:**
- Consumes: `BootstrapEvidence(confirmed_fills, settlement_clusters, independent_depth_sides, stable_since, hourly_anchor_change, daily_anchor_change, adverse_fill_times, fee_spent_xch, realized_loss_xch, marked_inventory_loss_xch)`.
- Produces: deterministic decisions with fractions `0.10`, `0.25`, `0.50`, `1.00`, or `0`.

- [ ] **Step 1: Write the failing stage-table tests**

```python
@pytest.mark.parametrize(
    ("fills", "clusters", "stable_minutes", "depth", "fraction"),
    [(0, 0, 0, False, "0.10"), (2, 2, 0, True, "0.25"),
     (6, 3, 30, True, "0.50"), (12, 5, 120, True, "1.00")],
)
def test_capacity_requires_approved_fill_cluster_and_depth_thresholds(
    fills, clusters, stable_minutes, depth, fraction
):
    decision = evaluate_bootstrap_campaign(
        make_campaign(),
        make_evidence(fills, clusters, stable_minutes, depth),
        now=NOW,
    )
    assert decision.deployment_fraction == Decimal(fraction)
```

Add boundary failures proving a fill threshold without distinct clusters or current independent depth cannot advance.

- [ ] **Step 2: Run the stage tests and observe incorrect 10% decisions**

Run: `python -m pytest tests/test_bootstrap_campaign_policy.py -k "capacity or stage" -q`

Expected: 25%, 50%, and 100% cases fail before stage logic exists.

- [ ] **Step 3: Implement stage transitions and identity-cluster disclaimers**

Stage decisions require current attributable non-maker depth for every funded side. Treat settlement clusters as conservative on-chain heuristics; any `suspected_linked_activity=True` excludes the related fills and emits `linked_activity_excluded`.

- [ ] **Step 4: Write and pass movement, cooldown, expiry, loss, and fee tests**

Add exact boundary tests asserting that an adverse fill cools only its affected
side until `fill_time + timedelta(minutes=5)`; proposed anchor changes are
clamped independently to 5% per rolling hour and 20% per rolling 24 hours;
expiry returns zero deployment with cancellation-only authority; loss equal to
5% of accepted campaign value returns `LOSS_LIMIT` plus manual-restart required;
and fee spend equal to 80% returns no-create/no-requote while leaving exactly 20%
for cancellation.

Run: `python -m pytest tests/test_bootstrap_campaign_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the complete pure decision engine**

```powershell
git add src/catalyst/bootstrap_campaign.py tests/test_bootstrap_campaign_policy.py
git commit -m "feat: stage and stop bootstrap exposure"
```

### Task 3: Persist campaign authorization and recovery evidence

**Files:**
- Modify: `src/catalyst/database.py`
- Create: `tests/test_bootstrap_campaign_persistence.py`

**Interfaces:**
- Consumes: canonical dictionaries returned by `BootstrapCampaign.to_record()` and event dictionaries with exact string amounts.
- Produces: `create_bootstrap_campaign(record) -> str`, `get_bootstrap_campaign(campaign_id) -> dict | None`, `get_active_bootstrap_campaign(asset_id, fingerprint, network) -> dict | None`, `append_bootstrap_campaign_event(record) -> str`, `list_bootstrap_campaign_events(campaign_id) -> list[dict]`, `stop_bootstrap_campaign(campaign_id, reason, stopped_at) -> bool`, and `record_bootstrap_participation(record) -> str`.

- [ ] **Step 1: Write failing idempotent migration and round-trip tests**

Add round-trip assertions for every canonical decimal string, run schema
initialization twice against the same isolated database, prove a second active
campaign for the same network/fingerprint/asset compare-and-set is rejected, and
reopen the database to prove stage, cooldown, fee, and loss state survive restart.

- [ ] **Step 2: Run persistence tests and observe missing schema/accessors**

Run: `python -m pytest tests/test_bootstrap_campaign_persistence.py -q`

Expected: FAIL on absent database functions.

- [ ] **Step 3: Add additive tables and database-only accessors**

Add `bootstrap_campaigns`, `bootstrap_campaign_events`, and `bootstrap_participation` using `CREATE TABLE IF NOT EXISTS`. Store every amount/price as canonical decimal text, timestamps as UTC text, and enforce one active campaign per `(network, wallet_fingerprint, asset_id)` with an application-level compare-and-set under the existing database lock. Do not add raw SQL outside `database.py`.

- [ ] **Step 4: Verify stop and recovery are idempotent**

Run: `python -m pytest tests/test_bootstrap_campaign_persistence.py tests/test_market_evidence_persistence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit persistence**

```powershell
git add src/catalyst/database.py tests/test_bootstrap_campaign_persistence.py
git commit -m "feat: persist bootstrap campaign authority"
```

### Task 4: Add canonical interactively Sage-signed manifests

**Files:**
- Create: `src/catalyst/bootstrap_manifest.py`
- Create: `src/catalyst/walletconnect_signing.py`
- Create: `web/walletconnect_signing.ts`
- Create: `scripts/build_walletconnect_signing.mjs`
- Create: `package.json`
- Create: `package-lock.json`
- Create: `assets/walletconnect-signing.js`
- Modify: `src/catalyst/config.py`
- Modify: `src/catalyst/api_server.py`
- Modify: `Catalyst.spec`
- Modify: `bot_gui.html`
- Create: `tests/test_bootstrap_manifest.py`
- Create: `tests/test_walletconnect_signing.py`
- Modify: `tests/test_build_release_config.py`

**Interfaces:**
- Consumes: public campaign fields, an immediately rechecked Sage identity/address, a WalletConnect session restricted to `chia_signMessageByAddress`, and a one-time signing request.
- Produces: `canonical_manifest_bytes(manifest) -> bytes`, `manifest_campaign_id(manifest) -> str`, `begin_manifest_signature(manifest, identity) -> SigningRequest`, `complete_manifest_signature(request_id, response, identity) -> dict`, `verify_campaign_manifest(signed_manifest) -> ManifestVerification`, and `safe_import_manifest(signed_manifest, expected_network) -> ImportedManifest`.

- [ ] **Step 1: Write failing canonicalization, tamper, and privacy tests**

Add assertions that differently ordered dictionaries produce identical canonical
bytes and campaign IDs; changing one anchor digit invalidates the BLS signature;
fingerprint, balances, credentials, unrelated addresses, and local paths are
rejected fields; and import exposes no remote trading, fee, subsidy, reserve, or
loss budget.

- [ ] **Step 2: Run tests and observe the missing-module failure**

Run: `python -m pytest tests/test_bootstrap_manifest.py -q`

Expected: collection fails because `bootstrap_manifest` does not exist.

- [ ] **Step 3: Implement canonical JSON and the bundled WalletConnect client**

Use sorted-key compact UTF-8 JSON and SHA-256 campaign IDs. Bundle a pinned `@walletconnect/sign-client` build locally; do not load executable JavaScript from a CDN. The dApp namespace requests only `chia_signMessageByAddress` on the selected `chia:mainnet` or `chia:testnet` chain. Display the pairing URI/QR, connected Sage account, exact message digest, approval state, timeout, rejection, and disconnect controls. A missing public `WALLETCONNECT_PROJECT_ID` returns stable `walletconnect_project_id_missing` with no network request.

- [ ] **Step 4: Bind and verify the interactive Sage response**

Immediately recheck Sage RPC identity before opening the request and before accepting its response. Require the WalletConnect account fingerprint/network and requested signing address to match that identity. Verify the returned Chia BLS public key/signature against Sage's exact `("Chia Signed Message", decoded_message).tree_hash()` convention using pinned `chia_rs`; reject wrong account, address, request ID, digest, expiry, duplicate response, timeout, disconnect, user rejection, and tampering. Never treat the existing standalone-RPC `sign_message_by_address` 404, a checksum, or a CATalyst-generated key as wallet proof.

- [ ] **Step 5: Verify an imported manifest has no financial authority**

`safe_import_manifest()` returns network, asset ID, anchor, corridor, expiry, stage rules, signer public key, and `VERIFIED`/`INVALID`/`UNVERIFIED_ASSET` status only. It requires the joining user to create fresh local budgets and acceptance before persistence.

Run: `python -m pytest tests/test_bootstrap_manifest.py tests/test_walletconnect_signing.py tests/test_build_release_config.py -q`

Expected: PASS.

- [ ] **Step 6: Commit signed manifests**

```powershell
git add src/catalyst/bootstrap_manifest.py src/catalyst/walletconnect_signing.py web/walletconnect_signing.ts scripts/build_walletconnect_signing.mjs package.json package-lock.json assets/walletconnect-signing.js src/catalyst/config.py src/catalyst/api_server.py Catalyst.spec bot_gui.html tests/test_bootstrap_manifest.py tests/test_walletconnect_signing.py tests/test_build_release_config.py
git commit -m "feat: sign and verify bootstrap manifests"
```

### Task 5: Separate data validity from provider redundancy

**Files:**
- Modify: `src/catalyst/market_confidence.py`
- Modify: `src/catalyst/market_runtime.py`
- Modify: `src/catalyst/blueprints/market.py`
- Modify: `src/catalyst/blueprints/smart_defaults.py`
- Modify: `src/catalyst/bot_loop.py`
- Modify: `tests/test_market_confidence.py`
- Modify: `tests/test_market_runtime.py`
- Modify: `tests/test_plan_04_10_smart_defaults_endpoint.py`

**Interfaces:**
- Consumes: existing exact Dexie/Splash normalized observations plus optional active `BootstrapDecision`.
- Produces: `MarketConfidenceResult.data_valid`, `provider_redundancy`, `follow_capacity_fraction`, `market_stage`, and reason codes that distinguish invalid data from a single healthy provider.

- [ ] **Step 1: Write the failing single-provider regressions**

Add assertions that a fresh attributable exact Dexie book remains valid with zero
Splash peers; its follow capacity is restricted rather than zero; stale or
crossed data remains unauthorized; and a Red follow market returns an explanatory
Bootstrap suggestion without settings persistence, Coin Prep, or wallet calls.

- [ ] **Step 2: Prove current behavior fails on `single_provider_dependency`**

Run: `python -m pytest tests/test_market_confidence.py tests/test_plan_04_10_smart_defaults_endpoint.py -k "single_provider or bootstrap_suggested" -q`

Expected: fresh exact Dexie-only scenarios remain Amber/409 before the change.

- [ ] **Step 3: Implement independent validity and redundancy fields**

Keep Green/Amber/Red source health, but do not derive `minimum_provider_count` from `SPLASH_ENABLED`. One valid exact Dexie book sets `data_valid=True` and restricted follow capacity; a second independent exact provider increases redundancy. Missing, stale, crossed, malformed, own-only, or unattributable books remain unauthorized.

- [ ] **Step 4: Return an explicit Bootstrap suggestion without mutation**

When the follow book is absent, stale, one-sided, insufficiently deep, or wider than 1,000 basis points, Smart Settings returns `bootstrap_suggested=true`, exact reason codes, and no settings save, Coin Prep, or offer action. Only a separate accepted campaign permits the Bootstrap path.

Run: `python -m pytest tests/test_market_confidence.py tests/test_market_runtime.py tests/test_plan_04_10_smart_defaults_endpoint.py -q`

Expected: PASS.

- [ ] **Step 5: Commit confidence separation**

```powershell
git add src/catalyst/market_confidence.py src/catalyst/market_runtime.py src/catalyst/blueprints/market.py src/catalyst/blueprints/smart_defaults.py src/catalyst/bot_loop.py tests/test_market_confidence.py tests/test_market_runtime.py tests/test_plan_04_10_smart_defaults_endpoint.py
git commit -m "feat: separate market validity from redundancy"
```

### Task 6: Derive Bootstrap Smart Settings and three-level ladders

**Files:**
- Modify: `src/catalyst/offer_book_policy.py`
- Modify: `src/catalyst/blueprints/smart_defaults.py`
- Modify: `src/catalyst/offer_manager.py`
- Modify: `src/catalyst/blueprints/coin_prep.py`
- Create: `tests/test_bootstrap_smart_settings.py`
- Create: `tests/test_bootstrap_offer_policy.py`

**Interfaces:**
- Consumes: persisted `BootstrapCampaign`, current `BootstrapDecision`, verified balances, and existing fee/profit configuration.
- Produces: `derive_bootstrap_plan(campaign, decision, balances) -> dict` with exactly three price/size levels per funded side and exact Coin Prep requirements.

- [ ] **Step 1: Write failing budget, corridor, one-sided, and subsidy tests**

Add exact-sum assertions that initial offered amounts never exceed 10% of either
funded budget; all three monotonic levels stay inside `[0.5 * anchor, 2 * anchor]`;
a buy-only plan produces no CAT Coin Prep output; subsidy affects a below-floor
quote only when the exact shortfall fits its remaining separate budget; and no
creation plan consumes the final 20% cancellation fee reserve.

- [ ] **Step 2: Run tests and observe missing Bootstrap planning behavior**

Run: `python -m pytest tests/test_bootstrap_smart_settings.py tests/test_bootstrap_offer_policy.py -q`

Expected: FAIL because follow-only Smart Settings rejects the campaign anchor.

- [ ] **Step 3: Implement exact ladder and inventory-skew policy**

Generate three monotonic levels per funded side around the current capped anchor. Sum of offered XCH/CAT must not exceed the stage fraction of its fixed budget. Apply existing fee and minimum-profit floors unless the exact projected shortfall is within the remaining separate subsidy budget. Skew remaining quotes toward rebalancing and pause a depleted side; never cross the current trusted range or hard campaign corridor.

- [ ] **Step 4: Integrate purpose-separated Coin Prep requirements**

Coin Prep receives only the exact staged XCH/CAT offer sizes and dedicated fee coins. It excludes campaign-protected, cancellation-reserve, unrelated wallet, unresolved-effect, and existing-offer coins under the existing selection rules.

Run: `python -m pytest tests/test_bootstrap_smart_settings.py tests/test_bootstrap_offer_policy.py tests/test_coin_prep_batch_plan.py tests/test_coin_prep_confirmed_views.py -q`

Expected: PASS.

- [ ] **Step 5: Commit planning and prep**

```powershell
git add src/catalyst/offer_book_policy.py src/catalyst/blueprints/smart_defaults.py src/catalyst/offer_manager.py src/catalyst/blueprints/coin_prep.py tests/test_bootstrap_smart_settings.py tests/test_bootstrap_offer_policy.py
git commit -m "feat: plan bounded bootstrap ladders"
```

### Task 7: Enforce Bootstrap authorization in the live lifecycle

**Files:**
- Modify: `src/catalyst/mutation_gate.py`
- Modify: `src/catalyst/bot_loop.py`
- Modify: `src/catalyst/offer_manager.py`
- Modify: `src/catalyst/fill_tracker.py`
- Modify: `src/catalyst/offer_reconciliation.py`
- Create: `tests/test_bootstrap_mutation_gate.py`
- Create: `tests/test_bootstrap_live_lifecycle.py`

**Interfaces:**
- Consumes: active persisted campaign ID, exact `BootstrapDecision`, Sage-confirmed effects, and durable offer lifecycle records.
- Produces: campaign-bound offer intents, exact stage counters, cooldown events, loss/fee stop events, and authoritative cancellation requests.

- [ ] **Step 1: Write failing no-bypass lifecycle tests**

Add assertions that Red follow confidence has no bypass without an active exact
campaign; every Bootstrap intent carries campaign ID and budget revision; expired,
stopped, or superseded revisions cannot create/requote; the loss stop schedules
authoritative cancellation and sets manual restart; and restart resumes unresolved
cancellation without creating replacement offers.

- [ ] **Step 2: Run and observe the current follow-only rejection**

Run: `python -m pytest tests/test_bootstrap_mutation_gate.py tests/test_bootstrap_live_lifecycle.py -q`

Expected: Bootstrap creation fails because the existing gate accepts only Green follow confidence.

- [ ] **Step 3: Add a narrow campaign-authority branch**

The mutation gate accepts either a valid Market Follow authorization or an exact active Bootstrap campaign decision bound to network, fingerprint, wallet ID, CAT asset ID, campaign ID, and revision. It does not weaken identity, ownership, reservation, publication, fill, cancellation, or terminal-proof gates.

- [ ] **Step 4: Count only Sage-confirmed independent settlement evidence**

Persist exact confirmed fill/spend identities, compute conservative non-maker clusters, exclude known own/linked activity, apply the five-minute side cooldown, and update stage only through a database compare-and-set. Dexie/Splash disappearance never increments capacity.

Run: `python -m pytest tests/test_bootstrap_mutation_gate.py tests/test_bootstrap_live_lifecycle.py tests/test_fill_confidence.py tests/test_offer_discovery_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit lifecycle enforcement**

```powershell
git add src/catalyst/mutation_gate.py src/catalyst/bot_loop.py src/catalyst/offer_manager.py src/catalyst/fill_tracker.py src/catalyst/offer_reconciliation.py tests/test_bootstrap_mutation_gate.py tests/test_bootstrap_live_lifecycle.py
git commit -m "feat: enforce bootstrap authority through lifecycle"
```

### Task 8: Expose campaign APIs and the Bootstrap wizard

**Files:**
- Create: `src/catalyst/blueprints/bootstrap.py`
- Modify: `src/catalyst/api_server.py`
- Modify: `src/catalyst/app_bridge.py`
- Modify: `bot_gui.html`
- Create: `tests/test_bootstrap_api.py`
- Create: `tests/test_bootstrap_ui_contract.py`

**Interfaces:**
- Produces: `GET /api/bootstrap/status`, `POST /api/bootstrap/preview`, `POST /api/bootstrap/start`, `POST /api/bootstrap/stop`, `POST /api/bootstrap/renew`, `POST /api/bootstrap/manifest/export`, `POST /api/bootstrap/manifest/import`, and `GET /api/bootstrap/partial-capability`.

- [ ] **Step 1: Write failing route and no-mutation-preview tests**

Add route assertions that preview returns the exact plan with zero database and
wallet mutations; start rejects changed identity or missing exact-asset warning
acceptance; import cannot start until fresh local budgets are supplied and
accepted; and the Experimental Partial control is visible, disabled, and backed
by stable missing-capability reason codes.

- [ ] **Step 2: Run tests and observe 404/missing-contract failures**

Run: `python -m pytest tests/test_bootstrap_api.py tests/test_bootstrap_ui_contract.py -q`

Expected: FAIL because the blueprint and UI controls do not exist.

- [ ] **Step 3: Implement routes with AppBridge-style error dictionaries**

All mutation routes perform an immediate identity recheck and return an AppBridge-style failure containing stable `code` and `error` strings on rejection. Preview is pure. Start persists the accepted campaign before Coin Prep. Stop invokes existing authoritative Cancel All scoped to campaign offers. Renew requires a fresh anchor/corridor/budget review. Manifest/proof signing creates a non-financial WalletConnect request and requires explicit approval in Sage.

- [ ] **Step 4: Add the UI flow across every relevant tab**

Settings shows Market Follow versus Bootstrap, exact asset verification, price-or-valuation input, fixed budgets, corridor, subsidy opt-in, loss/fee stops, manifest import/export, and the disabled Experimental Partial option. Dashboard shows mode, stage, deployed fraction, countdown, budgets, cooldown, and stop state. Offers, P&L, Market Intel, Logs, Data Reset, Help, About, and reload/restart surfaces use the same server snapshot and escaped text.

Run: `python -m pytest tests/test_bootstrap_api.py tests/test_bootstrap_ui_contract.py tests/test_post_tibet_ui_contract.py tests/test_frontend_diagnostics_layout.py -q`

Expected: PASS.

- [ ] **Step 5: Commit API and UI**

```powershell
git add src/catalyst/blueprints/bootstrap.py src/catalyst/api_server.py src/catalyst/app_bridge.py bot_gui.html tests/test_bootstrap_api.py tests/test_bootstrap_ui_contract.py
git commit -m "feat: add market bootstrap wizard"
```

### Task 9: Export participation proofs and static-directory records

**Files:**
- Create: `src/catalyst/bootstrap_proof.py`
- Modify: `src/catalyst/blueprints/bootstrap.py`
- Modify: `bot_gui.html`
- Create: `tests/test_bootstrap_proof.py`
- Create: `docs/bootstrap-directory/README.md`
- Create: `docs/bootstrap-directory/schema.json`

**Interfaces:**
- Consumes: campaign public key/ID, exact campaign offer/fill identities, bounded depth/uptime/spread samples, and wallet signature.
- Produces: `build_participation_report(campaign_id, observations) -> dict`, `sign_participation_report(report, address) -> dict`, and `verify_participation_report(signed_report) -> ProofVerification`.

- [ ] **Step 1: Write failing quality-score, anti-volume, and privacy tests**

Add deterministic assertions that the quality score changes with eligible depth,
uptime, and spread but not volume; own/linked observations are excluded; private
fingerprint, balances, paths, and unrelated history never serialize; and static
directory validation rejects a bad signature, wrong network, expired record, or
noncanonical payload.

- [ ] **Step 2: Run and observe missing proof behavior**

Run: `python -m pytest tests/test_bootstrap_proof.py -q`

Expected: collection fails because `bootstrap_proof` does not exist.

- [ ] **Step 3: Implement deterministic bounded quality totals**

Report exact eligible offer/fill IDs and aggregate time-weighted independent depth, uptime seconds, and within-corridor spread basis points. Do not calculate or promise a reward amount. Sign canonical bytes through the same identity-bound interactive Sage WalletConnect path as manifests.

- [ ] **Step 4: Define the no-cost static directory contract**

The schema requires canonical signed manifest fields, network, exact asset ID, expiry, signer public key, signature, and explicit asset verification status. Documentation states that inclusion is not endorsement and that every joining wallet chooses its own budgets.

Run: `python -m pytest tests/test_bootstrap_proof.py tests/test_bootstrap_manifest.py -q`

Expected: PASS.

- [ ] **Step 5: Commit proof and directory contracts**

```powershell
git add src/catalyst/bootstrap_proof.py src/catalyst/blueprints/bootstrap.py bot_gui.html tests/test_bootstrap_proof.py docs/bootstrap-directory/README.md docs/bootstrap-directory/schema.json
git commit -m "feat: export bootstrap participation proofs"
```

### Task 10: Add fail-closed experimental partial capability detection

**Files:**
- Modify: `src/catalyst/providers/models.py`
- Modify: `src/catalyst/providers/sage.py`
- Modify: `src/catalyst/providers/dexie.py`
- Modify: `src/catalyst/providers/splash.py`
- Create: `src/catalyst/partial_offer_capability.py`
- Create: `tests/test_partial_offer_capability.py`

**Interfaces:**
- Adds provider capabilities `PARTIAL_CREATE`, `PARTIAL_CANCEL`, `PARTIAL_STATE`, `PARTIAL_LINEAGE`, `PARTIAL_FILL`, and `PARTIAL_DISCOVERY`.
- Produces: `evaluate_partial_offer_capability(registry) -> PartialOfferCapabilityDecision(enabled, reason_codes, providers)`.

- [ ] **Step 1: Write the failing all-capabilities-required test matrix**

Parameterize every required partial capability and assert removing each one sets
`enabled=False` with that exact missing-capability reason. Also assert the current
Sage/distribution registry is disabled without invoking adapters, and inspect the
config/API contracts to prove no force-enable setting or request parameter exists.

- [ ] **Step 2: Run tests and observe missing capability enum/policy failures**

Run: `python -m pytest tests/test_partial_offer_capability.py -q`

Expected: FAIL before the capability values and evaluator exist.

- [ ] **Step 3: Implement detection only, with no live partial creation path**

Current adapters advertise only capabilities proven by their actual response contracts. The current Sage and public-discovery combination therefore returns disabled with exact reason codes. Do not add permissive wallet stubs to the live offer manager; ordinary standard offers remain unchanged.

- [ ] **Step 4: Run provider and standard-offer regression suites**

Run: `python -m pytest tests/test_partial_offer_capability.py tests/test_provider_contracts.py tests/test_provider_adapters.py tests/test_offer_creation_wallet_gate.py -q`

Expected: PASS with standard behavior unchanged.

- [ ] **Step 5: Commit capability gating**

```powershell
git add src/catalyst/providers/models.py src/catalyst/providers/sage.py src/catalyst/providers/dexie.py src/catalyst/providers/splash.py src/catalyst/partial_offer_capability.py tests/test_partial_offer_capability.py
git commit -m "feat: gate experimental partial offers by capability"
```

### Task 11: Verify deterministic and live Bootstrap acceptance

**Files:**
- Create: `tests/test_bootstrap_end_to_end.py`
- Modify: `docs/testing/v1.4.0-release-acceptance.md`
- Modify only production defects first reproduced by a focused failing test.

**Interfaces:**
- Consumes: all preceding public policy, database, API, and lifecycle interfaces.
- Produces: deterministic acceptance evidence plus the live TEST 7 SBX, DBX, and MZ results required before the existing two-PC window.

- [ ] **Step 1: Add the complete mock-wallet lifecycle**

Cover unknown CAT confirmation, campaign preview/start, three-offer one/two-sided plans, changed-size Coin Prep with fee reserve, publication/discovery, confirmed fills, excluded self activity, 10/25/50/100 stages, anchor caps, cooldown, inventory skew, expiry, loss/fee stops, cancel-all, restart, interactive signed-manifest join, missing-project-ID/user-rejection/account-mismatch signing paths, proof export, and disabled partial capability.

- [ ] **Step 2: Run targeted and full verification**

```powershell
python -m pytest tests/test_bootstrap_end_to_end.py tests/test_bootstrap_campaign_policy.py tests/test_bootstrap_campaign_persistence.py tests/test_bootstrap_manifest.py tests/test_bootstrap_smart_settings.py tests/test_bootstrap_offer_policy.py tests/test_bootstrap_mutation_gate.py tests/test_bootstrap_live_lifecycle.py tests/test_bootstrap_api.py tests/test_bootstrap_ui_contract.py tests/test_bootstrap_proof.py tests/test_partial_offer_capability.py -q
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m bandit -r src/catalyst -x tests
git diff --check
```

Expected: all commands pass.

- [ ] **Step 3: Build and smoke-test isolated Windows artifacts**

Run `python build.py`, then use isolated `CMM_DATA_DIR` directories to verify first launch, upgrade/restart, version, API/UI routes, manifest/proof import/export, standard-offer default, and disabled partial option without touching the real wallet.

- [ ] **Step 4: Execute authorized live TEST 7 acceptance**

Before each live mutation, verify mainnet, Sage TEST 7 fingerprint `736588221`, virtual CAT wallet ID `2`, exact selected asset ID, balances, campaign budgets, corridor, fee/loss stops, and zero unresolved effects. Test SBX first, DBX second, and MZ Bootstrap last. Record Smart Settings, changed-size Coin Prep, bot start, three-level creation/publication/discovery, a confirmed fill when independently available, stop, native Cancel All, restart recovery, provider degradation, and every UI tab. Never manufacture a fill or count the same user's second wallet as proven independent demand.

- [ ] **Step 5: Update acceptance evidence and commit**

```powershell
git add tests/test_bootstrap_end_to_end.py docs/testing/v1.4.0-release-acceptance.md
git commit -m "test: verify market bootstrap lifecycle"
```

### Task 12: Complete review, two-PC windows, merge, and release

**Files:**
- Modify: `docs/testing/v1.4.0-release-acceptance.md`
- Modify release metadata and website files only through their verified owning workflows.

**Interfaces:**
- Consumes: green PR #214, reproducible Windows candidate, primary-PC evidence, and secondary-PC evidence.
- Produces: merged `main`, `v1.4.0`, unsigned-beta installer plus SHA-256 metadata, updated website, and verified public download.

- [ ] **Step 1: Review the complete branch diff and require all PR checks green**

Confirm the prior compatible #213/#208/#207 integration remains intact, no unrelated files or secrets are tracked, and the three local `.tmp-*` evidence directories remain untracked.

- [ ] **Step 2: Run the complete two-PC functional matrix**

Install the same candidate on both PCs and repeat Market Follow plus Bootstrap Smart Settings, variable-size Coin Prep, start/stop, create/fill/requote, bulk Cancel All, reload/restart recovery, signed manifest join, proof export, provider degradation, and all UI tabs under each PC's independently verified wallet identity.

- [ ] **Step 3: Complete 24 clean hours on both PCs**

Require no unresolved effects, incorrect accounting, identity drift, budget overrun, stale/false market data, self-evidence capacity increase, unbounded errors, or source disagreement hidden from the UI. Any code change invalidates the affected build and restarts its relevant window.

- [ ] **Step 4: Merge and supersede source PRs only after acceptance**

Merge PR #214 into `main`, then close or supersede PRs #213, #208, and #207 with links to the integrated commits.

- [ ] **Step 5: Tag, publish, update the website, and re-download**

Tag `v1.4.0`; run the approved no-cost fail-closed unsigned-beta workflow; publish installer and exact SHA-256 metadata; update website copy for Market Follow, Bootstrap, TibetSwap retirement, and truthful SmartScreen/Defender guidance; download from the public website on clean Windows and verify hash, install, startup, version, standard-offer default, and no unexpected localhost/JSON routing.

## Verification Commands

Run from `C:\catalyst\.superpowers\post-tibetswap-v1-4`:

```powershell
python -m pytest <focused-test-files> -q
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m bandit -r src/catalyst -x tests
python build.py
git diff --check
git status --short
```

## Stop Conditions

Stop live activity, preserve diagnostics, and require a fresh explicit decision if wallet/network/asset identity changes; campaign authorization cannot be proven; the hard corridor, campaign budget, loss stop, or fee withdrawal reserve would be exceeded; Sage signing or cancellation repeatedly fails; an offer may still be live while replacement is proposed; settlement activity appears linked or manipulated; errors become unbounded; or an external credential/permission blocks required GitHub or release work.
