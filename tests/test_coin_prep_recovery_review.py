from coin_prep_recovery_review import render_recovery_review


def test_review_escapes_identifiers_and_excludes_unsigned_material():
    page = render_recovery_review({
        "operation_id": '<script>alert("x")</script>',
        "original_input_coin_ids": ["<img src=x onerror=alert(1)>"],
        "unsigned": {"secret": "must-not-render"},
        "outputs": [{"puzzle_hash": "<hostile>", "amount_mojos": "20000000000"}],
    })
    assert "<script>" not in page
    assert "<img" not in page
    assert "&lt;hostile&gt;" in page
    assert "must-not-render" not in page
    assert "fetch(" not in page
    assert 'action="/api/safety/coin-prep-recovery-preview"' in page
    assert "recovery-submit" not in page
    assert "<button disabled>" in page


def test_review_formats_mojos_without_float_or_javascript_precision_loss():
    page = render_recovery_review({"fee_mojos": "9007199254740993"})
    assert "9007199254740993 mojos (9007.199254740993 XCH)" in page
    assert "Replacement fee</dt><dd>Unavailable" in render_recovery_review({"fee_mojos": True})
    assert "Replacement fee</dt><dd>Unavailable" in render_recovery_review({"fee_mojos": "2e7"})


def test_review_matches_app_theme_and_keeps_exact_evidence_available():
    page = render_recovery_review({"original_transaction_id": "exact-transaction-id"})
    assert "--bg-app:#0B0E14" in page
    assert "--accent-primary:#6366F1" in page
    assert 'aria-labelledby="original-heading"' in page
    assert 'aria-labelledby="preview-heading"' in page
    assert "@media(max-width:650px)" in page
    assert "<summary>Inspect exact inputs and outputs</summary>" in page
    assert "exact-transaction-id" in page
    assert "TRADING PAUSED" in page
    assert "<script" not in page


def test_consent_form_is_explicit_unchecked_and_submission_requires_server_enable():
    snapshot = {"preview_available": True, "attempt_id": "a" * 64,
                "review_digest": "b" * 64, "fee_mojos": "20000000"}
    page = render_recovery_review(snapshot)
    assert 'name="confirmed" value="on" required' in page
    assert "checked" not in page
    assert '<button type="submit" disabled>Submit this replacement</button>' in page
    assert 'name="attempt_id" value="' + "a" * 64 in page
    snapshot["submission_available"] = True
    page = render_recovery_review(snapshot)
    assert '<button type="submit">Submit this replacement</button>' in page
    assert "Trading stays blocked until independent chain confirmation." in page
    snapshot["replacement_dispatched"] = True
    assert '<button type="submit" disabled>Submit this replacement</button>' in render_recovery_review(snapshot)
