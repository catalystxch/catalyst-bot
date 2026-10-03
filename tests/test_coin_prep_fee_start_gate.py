"""Coin Prep launchers must not cross into a worker without fee consent."""

from coin_manager import CoinManager


class _RunningProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def _manager_with_running_worker():
    manager = CoinManager.__new__(CoinManager)
    manager._prep_process = _RunningProcess()
    return manager


def test_manager_rejects_missing_fee_approval_before_touching_existing_worker():
    manager = _manager_with_running_worker()

    assert manager.start_coin_prep() is False
    assert manager._prep_process.terminated is False


def test_manager_rejects_stale_fee_approval_before_touching_existing_worker(
    monkeypatch,
):
    manager = _manager_with_running_worker()
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: {
            "available": False,
            "reason": "FEE_APPROVAL_STALE",
        },
    )

    assert manager.start_coin_prep(fee_approval_id="a" * 64) is False
    assert manager._prep_process.terminated is False
