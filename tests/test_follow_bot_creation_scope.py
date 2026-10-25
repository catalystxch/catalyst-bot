"""The normal BotLoop producer must bind every new offer to a reviewed run."""

import pytest

import bot_loop
import confidence_override


RUN_ID = "a" * 64


def test_bot_loop_reads_exact_follow_run_before_creation(monkeypatch):
    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: {"follow_run_id": RUN_ID},
    )
    assert bot_loop.BotLoop._require_follow_creation_run_id() == RUN_ID


@pytest.mark.parametrize("scope", [{}, {"follow_run_id": "bad"}, None])
def test_bot_loop_refuses_missing_follow_run(monkeypatch, scope):
    monkeypatch.setattr(confidence_override, "current_scope", lambda: scope)
    with pytest.raises(ValueError, match="FOLLOW_"):
        bot_loop.BotLoop._require_follow_creation_run_id()


def test_bot_loop_propagates_revoked_authority(monkeypatch):
    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: (_ for _ in ()).throw(ValueError("FOLLOW_FEE_AUTHORITY_REQUIRED")),
    )
    with pytest.raises(ValueError, match="FOLLOW_FEE_AUTHORITY_REQUIRED"):
        bot_loop.BotLoop._require_follow_creation_run_id()
