from __future__ import annotations

from datetime import datetime, timedelta, timezone

import database
import pytest
from degraded_market import DegradedMarketController


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "degraded.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def test_red_freezes_mutations_and_progressively_withdraws(isolated_db):
    controller = DegradedMarketController(asset_id=ASSET_ID)

    immediate = controller.update(confidence_state="RED", now=NOW)
    before_middle = controller.update(
        confidence_state="RED", now=NOW + timedelta(minutes=2, seconds=59)
    )
    middle = controller.update(confidence_state="RED", now=NOW + timedelta(minutes=3))
    final = controller.update(confidence_state="RED", now=NOW + timedelta(minutes=10))

    assert immediate.can_create is False
    assert immediate.can_requote is False
    assert immediate.cancel_tiers == ("inner",)
    assert immediate.stage == "INNER"
    assert before_middle.cancel_tiers == ("inner",)
    assert middle.cancel_tiers == ("inner", "middle")
    assert middle.stage == "MIDDLE"
    assert final.cancel_tiers == ("inner", "middle", "outer", "extreme", "opportunity")
    assert final.stage == "ALL"
    assert final.paused is True


def test_degraded_timer_survives_restart(isolated_db):
    first = DegradedMarketController(asset_id=ASSET_ID)
    first.update(confidence_state="RED", now=NOW)

    restarted = DegradedMarketController(asset_id=ASSET_ID)
    decision = restarted.update(confidence_state="RED", now=NOW + timedelta(minutes=4))

    assert decision.degraded_since == NOW
    assert decision.stage == "MIDDLE"


def test_recovery_requires_three_green_refreshes_spanning_sixty_seconds(isolated_db):
    controller = DegradedMarketController(asset_id=ASSET_ID)
    controller.update(confidence_state="RED", now=NOW)

    one = controller.update(confidence_state="GREEN", now=NOW + timedelta(minutes=11))
    two = controller.update(
        confidence_state="GREEN", now=NOW + timedelta(minutes=11, seconds=30)
    )
    too_soon = controller.update(
        confidence_state="GREEN", now=NOW + timedelta(minutes=11, seconds=59)
    )
    recovered = controller.update(
        confidence_state="GREEN", now=NOW + timedelta(minutes=12)
    )

    assert one.recovering is True and one.recovery_refreshes == 1
    assert two.recovering is True and two.recovery_refreshes == 2
    assert too_soon.recovering is True and too_soon.recovery_refreshes == 3
    assert too_soon.can_create is False
    assert recovered.recovering is False
    assert recovered.recovery_refreshes == 0
    assert recovered.degraded_since is None
    assert recovered.can_create is True
    assert recovered.can_requote is True


def test_flapping_cannot_reset_degraded_clock_or_fake_recovery(isolated_db):
    controller = DegradedMarketController(asset_id=ASSET_ID)
    controller.update(confidence_state="RED", now=NOW)
    controller.update(confidence_state="GREEN", now=NOW + timedelta(minutes=1))
    red_again = controller.update(
        confidence_state="RED", now=NOW + timedelta(minutes=2)
    )
    green_again = controller.update(
        confidence_state="GREEN", now=NOW + timedelta(minutes=9)
    )
    red_at_deadline = controller.update(
        confidence_state="RED", now=NOW + timedelta(minutes=10)
    )

    assert red_again.degraded_since == NOW
    assert red_again.recovery_refreshes == 0
    assert green_again.recovery_refreshes == 1
    assert red_at_deadline.stage == "ALL"
    assert red_at_deadline.paused is True


def test_notifications_only_mark_transitions_and_recovery_completion(isolated_db):
    controller = DegradedMarketController(asset_id=ASSET_ID)

    healthy = controller.update(confidence_state="GREEN", now=NOW)
    red = controller.update(confidence_state="RED", now=NOW + timedelta(seconds=1))
    red_repeat = controller.update(
        confidence_state="RED", now=NOW + timedelta(seconds=2)
    )
    green = controller.update(confidence_state="GREEN", now=NOW + timedelta(minutes=11))
    green_repeat = controller.update(
        confidence_state="GREEN", now=NOW + timedelta(minutes=11, seconds=30)
    )
    complete = controller.update(
        confidence_state="GREEN", now=NOW + timedelta(minutes=12)
    )

    assert healthy.notify is False
    assert red.notify is True
    assert red_repeat.notify is False
    assert green.notify is True
    assert green_repeat.notify is False
    assert complete.notify is True
