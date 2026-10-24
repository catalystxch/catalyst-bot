"""Desktop bot start must preserve the explicit recovered-book request."""

import pytest
from flask import jsonify, request


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, {}),
        ({"resume_existing_offers": True}, {"resume_existing_offers": True}),
        ({"resume_existing_offers": False}, {}),
        ({"resume_existing_offers": "true"}, {}),
        (
            {"resume_existing_offers": True, "unexpected": "value"},
            {"resume_existing_offers": True},
        ),
    ],
)
def test_desktop_bot_start_forwards_only_explicit_resume_flag(
    monkeypatch, body, expected
):
    import api_server
    from app_bridge import AppBridge

    seen = []

    def fake_start():
        seen.append(request.get_json())
        return jsonify({"success": True})

    monkeypatch.setattr(api_server, "api_bot_start", fake_start)
    monkeypatch.setattr(
        api_server, "wallet_setup_bootstrap_allows", lambda _operation: True
    )

    result = AppBridge().start_bot(body)

    assert result == {"success": True}
    assert seen == [expected]
