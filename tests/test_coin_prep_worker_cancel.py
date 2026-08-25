from unittest.mock import MagicMock

import coin_prep_worker


def _worker():
    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.log = MagicMock()
    worker.update_status = MagicMock()
    return worker


def test_coin_prep_cancel_all_denies_unjournaled_worker_cancellation():
    worker = _worker()
    worker.get_all_open_offers_rpc = MagicMock(
        return_value=[{"id": "trade-a"}, {"id": "trade-b"}]
    )
    worker._call_wallet_mutation = MagicMock()

    assert worker.cancel_all_offers() is False
    worker._call_wallet_mutation.assert_not_called()


def test_coin_prep_cancel_all_succeeds_when_no_open_offers():
    worker = _worker()
    worker.get_all_open_offers_rpc = MagicMock(return_value=[])
    worker._call_wallet_mutation = MagicMock()

    assert worker.cancel_all_offers() is True
    worker._call_wallet_mutation.assert_not_called()
