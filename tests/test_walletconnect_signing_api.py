from __future__ import annotations

from types import SimpleNamespace

import api_server
from walletconnect_signing import SigningError, WalletIdentity


IDENTITY = WalletIdentity(
    wallet_type="sage",
    fingerprint=736588221,
    network="mainnet",
    signing_address="xch1" + "q" * 58,
)


def test_signing_routes_do_not_acquire_financial_mutation_authority():
    for endpoint in (
        "api_bootstrap_manifest_sign_begin",
        "api_bootstrap_manifest_sign_complete",
        "api_bootstrap_manifest_sign_fail",
        "api_bootstrap_participation_sign_begin",
        "api_bootstrap_participation_sign_complete",
    ):
        assert api_server._write_endpoint_requires_mutation(endpoint) is False


def test_bundled_walletconnect_client_is_served_from_local_assets():
    with api_server.app.test_request_context("/assets/walletconnect-signing.js"):
        response = api_server.serve_brand_asset("walletconnect-signing.js")

    assert response.status_code == 200
    assert response.mimetype in {"application/javascript", "text/javascript"}


def test_config_route_reports_exact_nonfinancial_method(monkeypatch):
    monkeypatch.setattr(api_server.cfg, "WALLETCONNECT_PROJECT_ID", "public-id")

    with api_server.app.test_request_context(
        "/api/bootstrap/walletconnect/config", environ_base={"REMOTE_ADDR": "127.0.0.1"}
    ):
        response = api_server.api_bootstrap_walletconnect_config()

    payload = response.get_json()
    assert payload == {
        "success": True,
        "enabled": True,
        "project_id": "public-id",
        "allowed_method": "chia_signMessageByAddress",
        "financial_authority": False,
    }


def test_begin_route_returns_stable_appbridge_style_failure(monkeypatch):
    class FailingService:
        def begin_manifest_signature(self, _manifest, _identity):
            raise SigningError("walletconnect_project_id_missing")

    monkeypatch.setattr(
        api_server, "_get_walletconnect_signing_service", lambda: FailingService()
    )
    monkeypatch.setattr(api_server, "_read_walletconnect_identity", lambda: IDENTITY)

    with api_server.app.test_request_context(
        "/api/bootstrap/manifest/sign/begin",
        method="POST",
        json={"manifest": {}},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        response, status = api_server.api_bootstrap_manifest_sign_begin()

    assert status == 400
    assert response.get_json() == {
        "success": False,
        "code": "walletconnect_project_id_missing",
        "error": "walletconnect_project_id_missing",
    }


def test_begin_route_returns_only_public_request(monkeypatch):
    request = SimpleNamespace(
        to_public_dict=lambda: {
            "request_id": "request-1",
            "method": "chia_signMessageByAddress",
        }
    )

    class Service:
        def begin_manifest_signature(self, manifest, identity):
            assert manifest == {"schema": "example"}
            assert identity == IDENTITY
            return request

    monkeypatch.setattr(api_server, "_get_walletconnect_signing_service", Service)
    monkeypatch.setattr(api_server, "_read_walletconnect_identity", lambda: IDENTITY)

    with api_server.app.test_request_context(
        "/api/bootstrap/manifest/sign/begin",
        method="POST",
        json={"manifest": {"schema": "example"}},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        response = api_server.api_bootstrap_manifest_sign_begin()

    assert response.get_json() == {
        "success": True,
        "signing_request": {
            "request_id": "request-1",
            "method": "chia_signMessageByAddress",
        },
    }


def test_complete_route_rechecks_identity_through_service(monkeypatch):
    class Service:
        def complete_manifest_signature(self, request_id, response, identity):
            assert request_id == "request-1"
            assert response == {"publicKey": "pk", "signature": "sig"}
            assert identity == IDENTITY
            return {"manifest": {}, "signature": {}}

    monkeypatch.setattr(api_server, "_get_walletconnect_signing_service", Service)
    monkeypatch.setattr(api_server, "_read_walletconnect_identity", lambda: IDENTITY)

    with api_server.app.test_request_context(
        "/api/bootstrap/manifest/sign/complete",
        method="POST",
        json={
            "request_id": "request-1",
            "response": {"publicKey": "pk", "signature": "sig"},
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        response = api_server.api_bootstrap_manifest_sign_complete()

    assert response.get_json() == {
        "success": True,
        "signed_manifest": {"manifest": {}, "signature": {}},
    }


def test_participation_signing_routes_share_the_nonfinancial_service(monkeypatch):
    signing_request = SimpleNamespace(
        to_public_dict=lambda: {
            "request_id": "proof-request-1",
            "purpose": "bootstrap_participation",
            "method": "chia_signMessageByAddress",
        }
    )

    class Service:
        def begin_participation_signature(self, report, identity):
            assert report == {"schema": "proof"}
            assert identity == IDENTITY
            return signing_request

        def complete_participation_signature(self, request_id, response, identity):
            assert request_id == "proof-request-1"
            assert response == {"publicKey": "pk", "signature": "sig"}
            assert identity == IDENTITY
            return {"report": {"schema": "proof"}, "signature": {}}

    monkeypatch.setattr(api_server, "_get_walletconnect_signing_service", Service)
    monkeypatch.setattr(api_server, "_read_walletconnect_identity", lambda: IDENTITY)

    with api_server.app.test_request_context(
        "/api/bootstrap/participation/sign/begin",
        method="POST",
        json={"report": {"schema": "proof"}},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        begin = api_server.api_bootstrap_participation_sign_begin()

    assert begin.get_json()["signing_request"] == {
        "request_id": "proof-request-1",
        "purpose": "bootstrap_participation",
        "method": "chia_signMessageByAddress",
    }

    with api_server.app.test_request_context(
        "/api/bootstrap/participation/sign/complete",
        method="POST",
        json={
            "request_id": "proof-request-1",
            "response": {"publicKey": "pk", "signature": "sig"},
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        complete = api_server.api_bootstrap_participation_sign_complete()

    assert complete.get_json() == {
        "success": True,
        "signed_report": {"report": {"schema": "proof"}, "signature": {}},
    }
