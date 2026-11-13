from types import SimpleNamespace


def test_approved_run_previews_binds_and_starts_prep_once(monkeypatch):
    import coin_prep_fee_approval
    import confidence_override
    import database
    import follow_run_automation
    import follow_run_coordinator

    session = "a" * 64
    policy_digest = "b" * 64
    configuration_sha256 = "c" * 64
    approval_id = "d" * 64
    state = {
        "session_id": session,
        "policy_digest": policy_digest,
        "configuration_sha256": configuration_sha256,
        "state": "prep_pending",
        "fee_approval_id": None,
    }
    calls = []

    class Coordinator:
        def get_state(self):
            return dict(state)

        def bind_prep_approval(self, **kwargs):
            calls.append(("bind", kwargs))
            state["fee_approval_id"] = kwargs["approval_id"]

        def mark_preparing(self, **kwargs):
            calls.append(("preparing", kwargs))
            state["state"] = "preparing"

    monkeypatch.setattr(follow_run_coordinator, "FollowRunCoordinator", Coordinator)
    monkeypatch.setattr(
        database,
        "get_active_follow_run_policy",
        lambda: SimpleNamespace(digest=policy_digest),
    )
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: configuration_sha256,
    )
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "preview_coin_prep_fees",
        lambda options: {"available": True, "preview_id": "e" * 64},
    )
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "approve_coin_prep_fees",
        lambda **kwargs: {"approval_id": approval_id},
    )
    monkeypatch.setattr(
        follow_run_automation,
        "_route_json",
        lambda route, path, **kwargs: (
            calls.append(("trigger", kwargs["body"])) or {"success": True}
        ),
    )
    result = follow_run_automation.advance_approved_follow_run(session, permit=object())
    assert result["state"] == "preparing"
    assert [call[0] for call in calls] == ["bind", "preparing", "trigger"]
    assert calls[2][1]["fee_approval_id"] == approval_id


def test_prep_status_must_match_exact_approved_id(monkeypatch):
    import confidence_override
    import database
    import follow_run_automation
    import follow_run_coordinator

    state = {
        "session_id": "a" * 64,
        "policy_digest": "b" * 64,
        "configuration_sha256": "c" * 64,
        "state": "preparing",
        "fee_approval_id": "d" * 64,
    }
    called = []

    class Coordinator:
        def get_state(self):
            return dict(state)

        def reconcile_prep(self, **kwargs):
            called.append(kwargs)

    monkeypatch.setattr(follow_run_coordinator, "FollowRunCoordinator", Coordinator)
    monkeypatch.setattr(
        database,
        "get_active_follow_run_policy",
        lambda: SimpleNamespace(digest=state["policy_digest"]),
    )
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: state["configuration_sha256"],
    )
    monkeypatch.setattr(
        follow_run_automation,
        "_route_json",
        lambda *args, **kwargs: {
            "success": True,
            "complete": True,
            "running": False,
            "fee_approval_id": "e" * 64,
        },
    )
    result = follow_run_automation.advance_approved_follow_run(state["session_id"])
    assert result["reason"] == "PREP_RESULT_UNVERIFIED"
    assert called == []


def test_ready_run_binds_authority_then_starts_without_second_review(monkeypatch):
    import confidence_override
    import database
    import follow_run_automation
    import follow_run_authority_automation
    import follow_run_coordinator

    state = {
        "session_id": "a" * 64,
        "policy_digest": "b" * 64,
        "configuration_sha256": "c" * 64,
        "state": "ready",
        "fee_approval_id": "d" * 64,
    }
    calls = []

    class Coordinator:
        def get_state(self):
            return dict(state)

    monkeypatch.setattr(follow_run_coordinator, "FollowRunCoordinator", Coordinator)
    monkeypatch.setattr(
        database,
        "get_active_follow_run_policy",
        lambda: SimpleNamespace(digest=state["policy_digest"]),
    )
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: state["configuration_sha256"],
    )
    monkeypatch.setattr(
        follow_run_authority_automation,
        "authorize_approved_follow_run",
        lambda session_id: (
            calls.append(("authority", session_id))
            or {"success": True, "state": "ready", "run_id": "e" * 64}
        ),
    )
    monkeypatch.setattr(
        follow_run_automation,
        "_route_json",
        lambda route, path, **kwargs: (
            calls.append(("start", path)) or {"success": True}
        ),
    )
    result = follow_run_automation.advance_approved_follow_run(
        state["session_id"], permit=object()
    )
    assert result["state"] == "running"
    assert calls == [("authority", state["session_id"]), ("start", "/api/bot/start")]


def test_temporary_fee_quote_gap_keeps_approved_setup_pending(monkeypatch):
    import coin_prep_fee_approval
    import confidence_override
    import database
    import follow_run_automation
    import follow_run_coordinator

    state = {
        "session_id": "a" * 64,
        "policy_digest": "b" * 64,
        "configuration_sha256": "c" * 64,
        "state": "prep_pending",
        "fee_approval_id": None,
    }

    class Coordinator:
        def get_state(self):
            return dict(state)

    monkeypatch.setattr(follow_run_coordinator, "FollowRunCoordinator", Coordinator)
    monkeypatch.setattr(
        database,
        "get_active_follow_run_policy",
        lambda: SimpleNamespace(digest=state["policy_digest"]),
    )
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: state["configuration_sha256"],
    )
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "preview_coin_prep_fees",
        lambda _options: {"available": False, "reason": "FEE_ESTIMATE_UNAVAILABLE"},
    )
    result = follow_run_automation.advance_approved_follow_run(state["session_id"])
    assert result["success"] is True
    assert result["state"] == "prep_pending"
    assert result["action_needed"] is False
