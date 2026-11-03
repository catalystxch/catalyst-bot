"""The fenced terminal recovery screen must be the only native entry."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_restricted_root_serves_terminal_recovery_screen(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", True)
    monkeypatch.setattr(api_server, "_refresh_abort_recovery_active", False)
    client = api_server.app.test_client()
    headers = {api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}

    response = client.get("/", headers=headers)

    assert response.status_code == 200
    assert b"Verify Terminal Offers" in response.data
    assert b"/api/bootstrap/preview_terminal" in response.data
    assert b"/api/bootstrap/commit_terminal" in response.data
    assert b"Start Bot Now" not in response.data
    assert client.post("/api/bot/start", json={}, headers=headers).status_code == 423


def test_restricted_scope_is_token_guarded_and_bound_to_current_candidate(monkeypatch):
    import api_server

    campaign_id = "a" * 64
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", True)
    monkeypatch.setattr(api_server, "_refresh_abort_recovery_active", False)
    monkeypatch.setattr(
        api_server,
        "preflight_registry_terminal_restricted_startup",
        lambda **_kwargs: {
            "eligible": True,
            "campaign_id": campaign_id,
            "revision": 0,
            "latch_generation": 150,
            "blocking_operation_ids": ["reconcile:one"],
            "wallet_snapshot": {"trade_ids": [], "pending_transaction_ids": []},
        },
    )
    client = api_server.app.test_client()
    path = "/api/bootstrap/terminal_recovery_scope"
    assert client.get(path).status_code == 401
    headers = {api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["campaign_id"] == campaign_id
    assert response.get_json()["latch_generation"] == 150
    assert "wallet_snapshot" not in response.get_json()


def test_terminal_recovery_screen_is_bundled_and_reviews_all_roots():
    page = (ROOT / "terminal_offer_recovery.html").read_text(encoding="utf-8")
    spec = (ROOT / "catalyst.spec").read_text(encoding="utf-8")

    assert "terminal_offer_recovery.html" in spec
    assert "reviewed.offers" in page
    assert "textContent" in page
    assert "partial_commit" in page
    assert "fresh preview" in page.lower()
    assert "wallet transaction" in page.lower()
    assert "trading stays stopped" in page.lower()
    assert "proof.offers.length < scope.blocking_count" in page


def test_normal_stopped_campaign_exposes_reviewed_terminal_control():
    page = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert 'id="bootstrapReconcileTerminalBtn"' in page
    assert "async function bootstrapReconcileTerminalOffers()" in page
    assert "'/api/bootstrap/preview_terminal?'" in page
    assert "'/api/bootstrap/commit_terminal'" in page
    assert "proofReview: true" in page
    assert "partial_commit" in page
    assert "#bootstrapReconcileTerminalBtn" in page
