"""Sage transport retries must not replay an ambiguous wallet effect."""

import pytest

import mutation_gate
import wallet_sage


@pytest.mark.parametrize("endpoint", ["submit_transaction", "send_xch", "make_offer"])
def test_response_loss_does_not_replay_wallet_mutation(monkeypatch, endpoint):
    sends = []

    class LostResponseConnection:
        def request(self, method, path, **_kwargs):
            sends.append((method, path))

        def getresponse(self):
            raise ConnectionResetError("response lost after Sage may have accepted it")

    class RetryConnection:
        def request(self, method, path, **_kwargs):
            sends.append((method, path))

        def getresponse(self):
            return type(
                "Response",
                (),
                {"status": 200, "read": lambda self: b'{"success": true}'},
            )()

    monkeypatch.setattr(
        wallet_sage, "_get_sage_connection", lambda _timeout: LostResponseConnection()
    )
    monkeypatch.setattr(
        wallet_sage.http.client,
        "HTTPSConnection",
        lambda *_args, **_kwargs: RetryConnection(),
    )
    monkeypatch.setattr(wallet_sage, "CERT_PATH", None)
    monkeypatch.setattr(wallet_sage, "KEY_PATH", None)
    monkeypatch.setattr(wallet_sage._conn_local, "conn", None, raising=False)

    with pytest.raises(wallet_sage.SageConnectionError):
        wallet_sage._sage_post(endpoint, {})

    assert sends == [("POST", f"/{endpoint}")]


def test_response_loss_retries_read_only_sage_request(monkeypatch):
    sends = []

    class LostResponseConnection:
        def request(self, method, path, **_kwargs):
            sends.append((method, path))

        def getresponse(self):
            raise ConnectionResetError("response lost")

    class RetryConnection:
        def request(self, method, path, **_kwargs):
            sends.append((method, path))

        def getresponse(self):
            return type(
                "Response",
                (),
                {"status": 200, "read": lambda self: b'{"synced": true}'},
            )()

    monkeypatch.setattr(
        wallet_sage, "_get_sage_connection", lambda _timeout: LostResponseConnection()
    )
    monkeypatch.setattr(
        wallet_sage.http.client,
        "HTTPSConnection",
        lambda *_args, **_kwargs: RetryConnection(),
    )
    monkeypatch.setattr(wallet_sage, "CERT_PATH", None)
    monkeypatch.setattr(wallet_sage, "KEY_PATH", None)
    monkeypatch.setattr(wallet_sage._conn_local, "conn", None, raising=False)

    result = wallet_sage._sage_post("get_sync_status", {})

    assert result == {"synced": True}
    assert sends == [("POST", "/get_sync_status")] * 2


@pytest.mark.parametrize("operation", ["send_transaction", "split_coins_rpc"])
def test_wallet_effect_rechecks_lease_after_delayed_connection(monkeypatch, operation):
    lease_expired = False
    sends = []

    class DelayedConnection:
        sock = None

        def connect(self):
            nonlocal lease_expired
            lease_expired = True
            self.sock = object()

        def request(self, method, path, **_kwargs):
            if self.sock is None:
                self.connect()
            sends.append((method, path))

        def getresponse(self):
            return type(
                "Response",
                (),
                {"status": 200, "read": lambda self: b'{"success": true}'},
            )()

    def require_live_lease(_step):
        if lease_expired:
            raise mutation_gate.MutationBlocked("LEASE_EXPIRED", operation)

    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, *, context: address,
    )
    monkeypatch.setattr(
        wallet_sage, "_get_sage_connection", lambda _timeout: DelayedConnection()
    )
    monkeypatch.setattr(wallet_sage._conn_local, "conn", None, raising=False)

    with pytest.raises(mutation_gate.MutationBlocked):
        if operation == "send_transaction":
            wallet_sage.send_transaction(
                1, 1, "xch1test", _identity_recheck=require_live_lease
            )
        else:
            wallet_sage.split_coins_rpc(
                1, "a" * 64, 2, 1, _identity_recheck=require_live_lease
            )

    assert sends == []
