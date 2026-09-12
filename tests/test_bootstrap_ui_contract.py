from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI = (ROOT / "bot_gui.html").read_text(encoding="utf-8")


def test_bootstrap_wizard_exposes_reviewed_campaign_controls():
    for element_id in (
        "bootstrapModeSelect",
        "bootstrapAnchorPrice",
        "bootstrapXchBudget",
        "bootstrapCatBudget",
        "bootstrapFeeBudget",
        "bootstrapSubsidyBudget",
        "bootstrapExpiryDays",
        "bootstrapExactAssetConfirm",
        "bootstrapPreviewBtn",
        "bootstrapStartBtn",
        "bootstrapStopBtn",
        "bootstrapManifestExportBtn",
        "bootstrapManifestImportInput",
        "bootstrapParticipationExportBtn",
        "bootstrapPartialOffers",
        "bootstrapPartialOffersReason",
        "bootstrapStatusPanel",
        "bootstrapDashboardStatus",
    ):
        assert f'id="{element_id}"' in GUI


def test_bootstrap_ui_calls_every_campaign_route_and_walletconnect_signing():
    for route in (
        "/api/bootstrap/status",
        "/api/bootstrap/preview",
        "/api/bootstrap/start",
        "/api/bootstrap/stop",
        "/api/bootstrap/manifest/export",
        "/api/bootstrap/manifest/import",
        "/api/bootstrap/participation/export",
        "/api/bootstrap/participation/sign/begin",
        "/api/bootstrap/participation/sign/complete",
        "/api/bootstrap/partial-capability",
    ):
        assert route in GUI
    assert "signBootstrapManifest" in GUI
    assert "exportBootstrapParticipationProof" in GUI


def test_partial_offers_are_visibly_disabled_with_stable_reason():
    assert 'id="bootstrapPartialOffers"' in GUI
    assert 'id="bootstrapPartialOffersReason"' in GUI
    assert "disabled_until_capability_proven" in GUI
    assert "PARTIAL_OFFERS_CAPABILITY_NOT_PROVEN" in GUI
    assert "payload?.reason_codes" in GUI


def test_bootstrap_status_is_visible_across_the_main_workflow():
    for label in (
        "Dashboard",
        "Offers",
        "P&L",
        "Market Intel",
        "Settings",
        "Logs",
        "Help",
        "About",
    ):
        assert label in GUI
    assert 'id="bootstrapGlobalStatus"' in GUI


def test_coin_prep_binds_the_exact_active_bootstrap_revision():
    assert (
        "prepPayload.bootstrap_campaign_id = _bootstrapActiveCampaign.campaign_id"
        in GUI
    )
    assert (
        "prepPayload.bootstrap_campaign_revision = _bootstrapActiveCampaign.revision"
        in GUI
    )


def test_active_bootstrap_campaign_restores_its_exact_pair_after_reload():
    """A stopped app must not strand a durable campaign behind the fresh-pair gate."""

    assert "function syncBootstrapCampaignPairIntoSelectors(payload)" in GUI

    expose_start = GUI.index("function _shouldExposeRestoredPairToUI()")
    expose_end = GUI.index("function getDashboardSelectedPair", expose_start)
    expose_block = GUI[expose_start:expose_end]
    assert "typeof _bootstrapActiveCampaign !== 'undefined'" in expose_block
    assert "&& _bootstrapActiveCampaign.asset_id" in expose_block

    render_start = GUI.index("function _bootstrapRenderStatus(payload)")
    render_end = GUI.index("async function bootstrapRefreshStatus", render_start)
    render_block = GUI[render_start:render_end]
    assert "syncBootstrapCampaignPairIntoSelectors(payload)" in render_block

    cats_start = GUI.index("async function loadCATs()")
    cats_end = GUI.index("async function selectCAT()", cats_start)
    cats_block = GUI[cats_start:cats_end]
    assert "await bootstrapRefreshStatus()" in cats_block


def test_active_bootstrap_campaign_hydrates_saved_settings_after_reload():
    assert "function hydrateBootstrapCampaignControls(campaign)" in GUI

    hydrate_start = GUI.index("function hydrateBootstrapCampaignControls(campaign)")
    hydrate_end = GUI.index(
        "function syncBootstrapCampaignPairIntoSelectors", hydrate_start
    )
    hydrate_block = GUI[hydrate_start:hydrate_end]
    for campaign_field in (
        "campaign.anchor_price",
        "campaign.minimum_price",
        "campaign.maximum_price",
        "campaign.xch_budget",
        "campaign.cat_budget",
        "campaign.fee_budget_xch",
        "campaign.subsidy_budget_xch",
    ):
        assert campaign_field in hydrate_block
    assert "mode.value = 'bootstrap'" in hydrate_block
    assert "fields.style.display = 'block'" in hydrate_block
    assert "preview.disabled = true" in hydrate_block
    assert "start.disabled = true" in hydrate_block
    assert "setValue('configMinMid', campaign.minimum_price)" in hydrate_block
    assert "setValue('configMaxMid', campaign.maximum_price)" in hydrate_block

    render_start = GUI.index("function _bootstrapRenderStatus(payload)")
    render_end = GUI.index("async function bootstrapRefreshStatus", render_start)
    render_block = GUI[render_start:render_end]
    assert "hydrateBootstrapCampaignControls(_bootstrapActiveCampaign)" in render_block

    settings_start = GUI.index("async function v4SwitchView(viewName")
    settings_end = GUI.index(
        "// Keyboard shortcuts for sidebar navigation", settings_start
    )
    settings_block = GUI[settings_start:settings_end]
    config_load = settings_block.index(
        "const response = await apiFetch(API_URL + '/config')"
    )
    campaign_hydrate = settings_block.index(
        "hydrateBootstrapCampaignControls(_bootstrapActiveCampaign)", config_load
    )
    legacy_guard_load = settings_block.index(
        "document.getElementById('configMaxMid').value = formatPriceGuardInput",
        config_load,
    )
    assert campaign_hydrate > legacy_guard_load


def test_coin_prep_preview_shows_campaign_caps_instead_of_legacy_wallet_plan():
    preview_start = GUI.index("function renderBootstrapCoinPrepPreview")
    preview_end = GUI.index("function validateSettingsForm()", preview_start)
    preview_block = GUI[preview_start:preview_end]

    assert "renderBootstrapCoinPrepPreview" in preview_block
    assert "_bootstrapActiveCampaign" in preview_block
    assert "campaign.xch_budget" in preview_block
    assert "campaign.cat_budget" in preview_block
    assert "campaign.fee_budget_xch" in preview_block
    assert "Campaign-bound" in preview_block
    assert "legacy Smart Settings coin plan is bypassed" in preview_block


def test_coin_prep_verify_has_bounded_client_wait_and_safe_fallback():
    start = GUI.index("async function checkIfCoinPrepNeeded(config)")
    end = GUI.index("function showCoinPrepConfirm(config", start)
    block = GUI[start:end]

    assert "Promise.race" in block
    assert "Coin Prep verification timed out" in block
    assert "verifyController.abort()" in block
    assert "Could not verify existing coins" in block


def test_settings_warning_is_not_hidden_behind_preopened_coin_prep():
    start = GUI.index("async function saveConfig()")
    end = GUI.index("function closeCtgErrorModal()", start)
    block = GUI[start:end]
    warning = block.index("if (validationWarnings.length > 0)")
    confirm = block.index("const proceed = await showStyledConfirm", warning)
    dismiss = block.index("dismissCoinPrepConfirmLoading()", warning)
    reopen = block.index("showCoinPrepConfirmLoading(config)", confirm)

    assert dismiss < confirm < reopen


def test_bootstrap_coin_prep_preflight_sends_exact_campaign_authority():
    start = GUI.index("async function checkIfCoinPrepNeeded(config)")
    end = GUI.index("function showCoinPrepConfirm(config", start)
    block = GUI[start:end]

    assert "params.set('bootstrap_campaign_id'" in block
    assert "params.set('bootstrap_campaign_revision'" in block
    assert "showCoinPrepConfirm(config, reason, reasonMessage, result)" in block


def test_bootstrap_coin_prep_confirmation_renders_exact_verified_plan():
    assert "function renderBootstrapCoinPrepConfirmation" in GUI
    start = GUI.index("function renderBootstrapCoinPrepConfirmation")
    end = GUI.index("function showCoinPrepConfirm(config", start)
    block = GUI[start:end]

    assert "verification.bootstrap_campaign_id" in block
    assert "verification.xch_needed_mojos" in block
    assert "verification.cat_needed_mojos" in block
    assert "verification.tiers" in block
    assert "Prepare Exact Campaign Coins" in block
    assert ".textContent" in block

    confirm_start = end
    confirm_end = GUI.index("function closeCoinPrepConfirm()", confirm_start)
    confirm_block = GUI[confirm_start:confirm_end]
    assert "renderBootstrapCoinPrepConfirmation" in confirm_block
