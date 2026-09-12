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
