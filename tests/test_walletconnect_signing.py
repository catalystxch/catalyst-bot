from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from chia_rs import AugSchemeMPL, Program

from bootstrap_manifest import canonical_manifest_bytes
from test_bootstrap_manifest import ADDRESS, make_manifest
from walletconnect_signing import (
    SigningError,
    WalletConnectSigningService,
    WalletIdentity,
)


NOW = datetime(2026, 9, 12, 11, 0, tzinfo=timezone.utc)
IDENTITY = WalletIdentity(
    wallet_type="sage",
    fingerprint=736588221,
    network="mainnet",
    signing_address=ADDRESS,
)


def response_for(request, *, secret_key=None, **changes):
    secret_key = secret_key or AugSchemeMPL.key_gen(
        b"catalyst walletconnect signing test" + b"\0" * 2
    )
    message = bytes.fromhex(request.message.removeprefix("0x"))
    tree_hash = bytes(Program.to((b"Chia Signed Message", message)).get_tree_hash())
    response = {
        "requestId": request.request_id,
        "account": request.account,
        "address": request.signing_address,
        "messageDigest": request.message_digest,
        "publicKey": bytes(secret_key.get_g1()).hex(),
        "signature": bytes(AugSchemeMPL.sign(secret_key, tree_hash)).hex(),
    }
    response.update(changes)
    return response


def make_service(identity_reader=lambda: IDENTITY, project_id="project-id"):
    return WalletConnectSigningService(
        project_id=project_id,
        identity_reader=identity_reader,
        clock=lambda: NOW,
        request_ttl=timedelta(minutes=2),
    )


def test_missing_project_id_fails_without_opening_a_request():
    service = make_service(project_id="")

    with pytest.raises(SigningError) as error:
        service.begin_manifest_signature(make_manifest(), IDENTITY)

    assert error.value.code == "walletconnect_project_id_missing"
    assert service.pending_request_count == 0


def test_begin_requests_only_sage_message_signing_on_bound_account():
    service = make_service()

    request = service.begin_manifest_signature(make_manifest(), IDENTITY)

    expected_bytes = canonical_manifest_bytes(make_manifest())
    assert request.method == "chia_signMessageByAddress"
    assert request.required_methods == ("chia_signMessageByAddress",)
    assert request.account == "chia:mainnet:736588221"
    assert request.chain == "chia:mainnet"
    assert request.signing_address == ADDRESS
    assert request.message == f"0x{expected_bytes.hex()}"
    assert request.message_digest == hashlib.sha256(expected_bytes).hexdigest()
    assert "createOffer" not in repr(request)
    assert "cancelOffer" not in repr(request)
    assert "signCoinSpends" not in repr(request)


def test_begin_rechecks_rpc_identity_before_creating_request():
    wrong = WalletIdentity("sage", 999, "mainnet", ADDRESS)
    service = make_service(identity_reader=lambda: wrong)

    with pytest.raises(SigningError) as error:
        service.begin_manifest_signature(make_manifest(), IDENTITY)

    assert error.value.code == "wallet_identity_changed"
    assert service.pending_request_count == 0


def test_valid_response_is_verified_and_consumes_one_time_request():
    service = make_service()
    request = service.begin_manifest_signature(make_manifest(), IDENTITY)

    signed = service.complete_manifest_signature(
        request.request_id, response_for(request), IDENTITY
    )

    assert signed["manifest"] == make_manifest()
    assert signed["signature"]["message_digest"] == request.message_digest
    assert service.pending_request_count == 0
    with pytest.raises(SigningError) as error:
        service.complete_manifest_signature(
            request.request_id, response_for(request), IDENTITY
        )
    assert error.value.code == "signing_request_not_pending"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"requestId": "different"}, "signing_request_id_mismatch"),
        ({"account": "chia:mainnet:1"}, "walletconnect_account_mismatch"),
        ({"address": "xch1different"}, "signing_address_mismatch"),
        ({"messageDigest": "00" * 32}, "message_digest_mismatch"),
        ({"signature": "00" * 96}, "signature_invalid"),
    ],
)
def test_tampered_or_misbound_response_is_rejected(change, code):
    service = make_service()
    request = service.begin_manifest_signature(make_manifest(), IDENTITY)

    with pytest.raises(SigningError) as error:
        service.complete_manifest_signature(
            request.request_id, response_for(request, **change), IDENTITY
        )

    assert error.value.code == code


def test_complete_rechecks_rpc_identity_and_rejects_changed_wallet():
    current = {"identity": IDENTITY}
    service = make_service(identity_reader=lambda: current["identity"])
    request = service.begin_manifest_signature(make_manifest(), IDENTITY)
    current["identity"] = WalletIdentity("sage", 736588222, "mainnet", ADDRESS)

    with pytest.raises(SigningError) as error:
        service.complete_manifest_signature(
            request.request_id, response_for(request), IDENTITY
        )

    assert error.value.code == "wallet_identity_changed"


def test_timeout_rejection_and_disconnect_have_stable_codes():
    service = make_service()
    timeout = service.begin_manifest_signature(make_manifest(), IDENTITY)
    service._clock = lambda: NOW + timedelta(minutes=3)
    with pytest.raises(SigningError) as error:
        service.complete_manifest_signature(timeout.request_id, {}, IDENTITY)
    assert error.value.code == "signing_request_expired"

    service = make_service()
    rejected = service.begin_manifest_signature(make_manifest(), IDENTITY)
    with pytest.raises(SigningError) as error:
        service.fail_request(rejected.request_id, "user_rejected")
    assert error.value.code == "walletconnect_user_rejected"

    disconnected = service.begin_manifest_signature(make_manifest(), IDENTITY)
    with pytest.raises(SigningError) as error:
        service.fail_request(disconnected.request_id, "disconnected")
    assert error.value.code == "walletconnect_disconnected"


def test_non_sage_wallet_cannot_begin_walletconnect_signature():
    identity = WalletIdentity("chia", 736588221, "mainnet", ADDRESS)
    service = make_service(identity_reader=lambda: identity)

    with pytest.raises(SigningError) as error:
        service.begin_manifest_signature(make_manifest(), identity)

    assert error.value.code == "sage_wallet_required"
