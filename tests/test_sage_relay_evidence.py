from __future__ import annotations

import hashlib

import wallet_sage


TXID = "8" * 64


def test_exact_all_peer_rejection_is_bound_to_submitted_transaction():
    text = "\n".join(
        [
            f"2026-09-13T14:55:29Z INFO Submitting transaction with id {TXID}: [abc]",
            f'2026-09-13T14:55:30Z INFO Transaction response received with ack TransactionAck {{ txid: {TXID}, status: 3, error: Some("INVALID_FEE_TOO_CLOSE_TO_ZERO") }}',
            '2026-09-13T14:55:31Z INFO Transaction inclusion in mempool failed for all peers with status 3 and error Some("INVALID_FEE_TOO_CLOSE_TO_ZERO"), removing transaction',
        ]
    )

    result = wallet_sage._parse_transaction_relay_log_text(TXID, text)

    assert result == {
        "status": "rejected",
        "transaction_id": TXID,
        "reason_code": "INVALID_FEE_TOO_CLOSE_TO_ZERO",
        "evidence_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def test_rejection_for_another_transaction_is_not_reused():
    other = "9" * 64
    text = "\n".join(
        [
            f"INFO Submitting transaction with id {other}: [abc]",
            'INFO Transaction inclusion in mempool failed for all peers with status 3 and error Some("INVALID_FEE_TOO_CLOSE_TO_ZERO"), removing transaction',
        ]
    )

    assert wallet_sage._parse_transaction_relay_log_text(TXID, text) == {
        "status": "unknown",
        "transaction_id": TXID,
    }


def test_later_success_wins_over_an_earlier_rejection_for_same_transaction():
    text = "\n".join(
        [
            f"INFO Submitting transaction with id {TXID}: [abc]",
            'INFO Transaction inclusion in mempool failed for all peers with status 3 and error Some("INVALID_FEE_TOO_CLOSE_TO_ZERO"), removing transaction',
            f"INFO Submitting transaction with id {TXID}: [abc]",
            "INFO Transaction inclusion in mempool successful, updating timestamp",
        ]
    )

    result = wallet_sage._parse_transaction_relay_log_text(TXID, text)

    assert result["status"] == "accepted"
    assert result["transaction_id"] == TXID
    assert result["evidence_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
