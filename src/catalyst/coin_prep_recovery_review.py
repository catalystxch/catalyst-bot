"""Pure HTML renderer for owner-only recovery review; no routes or wallet imports."""

from html import escape


def render_recovery_review(snapshot: dict) -> str:
    """Render a sanitized server snapshot, never the raw unsigned wallet response.

    Admission, exact-operation binding and lease checks belong to the caller.
    The caller alone decides whether the reviewed submission action is enabled.
    """

    def text(key):
        value = snapshot.get(key)
        return escape(str(value)) if value is not None else "Unavailable"

    def amount(key):
        value = snapshot.get(key)
        if type(value) is int and value >= 0:
            digits = str(value)
        elif (
            type(value) is str
            and value.isascii()
            and value.isdigit()
            and (value == "0" or not value.startswith("0"))
        ):
            digits = value
        else:
            return "Unavailable"
        padded = digits.zfill(13)
        xch = padded[:-12] + "." + padded[-12:]
        return escape(digits) + " mojos (" + escape(xch) + " XCH)"

    fields = (
        ("Operation", text("operation_id")),
        ("Original transaction", text("original_transaction_id")),
        ("Original fee", amount("original_fee_mojos")),
        ("Replacement fee", amount("fee_mojos")),
        ("Original change", amount("original_change_mojos")),
        ("Replacement change", amount("new_change_mojos")),
        ("Unsigned spend cost", text("cost")),
        ("Observed at (UTC)", text("observed_at")),
        ("Quote expires at (UTC)", text("expires_at")),
        ("Review digest", text("review_digest")),
        ("Replacement attempt", text("attempt_id")),
    )

    def rows(indices):
        return "".join(
            f"<dt>{fields[index][0]}</dt><dd>{fields[index][1]}</dd>"
            for index in indices
        )

    inputs = snapshot.get("original_input_coin_ids")
    input_rows = (
        "".join(
            "<li>" + escape(value) + "</li>" for value in inputs if type(value) is str
        )
        if type(inputs) is list
        else "<li>Unavailable</li>"
    )
    outputs = snapshot.get("outputs")
    output_rows = (
        "".join(
            "<li><strong>"
            + escape(
                {"fee_reserve": "Fee reserve", "top_up": "Wallet change"}.get(
                    row.get("purpose"), "Output"
                )
            )
            + "</strong><br>"
            + escape(str(row.get("coin_id", row.get("puzzle_hash", "Unavailable"))))
            + " — "
            + escape(str(row.get("amount_mojos", "Unavailable")))
            + " mojos</li>"
            for row in outputs
            if type(row) is dict
        )
        if type(outputs) is list
        else "<li>Unavailable</li>"
    )
    consent = ""
    if snapshot.get("preview_available") is True:
        disabled = (
            ""
            if (
                snapshot.get("submission_available") is True
                and snapshot.get("replacement_dispatched") is not True
            )
            else " disabled"
        )
        consent = (
            '<form class="consent card" method="post" action="/api/safety/coin-prep-recovery-submit">'
            "<h2>Approve this exact replacement</h2>"
            '<input type="hidden" name="attempt_id" value="' + text("attempt_id") + '">'
            '<input type="hidden" name="review_digest" value="'
            + text("review_digest")
            + '">'
            '<label><input type="checkbox" name="confirmed" value="on" required> '
            "I approve the replacement fee of "
            + amount("fee_mojos")
            + " for the exact transaction and outputs shown above.</label>"
            '<button type="submit"' + disabled + ">Submit this replacement</button>"
            "</form>"
        )
    footer = (
        "Trading stays blocked until independent chain confirmation."
        if snapshot.get("submission_available") is True
        else "Submission is not available in this review. No wallet action can be initiated from this page."
    )
    return (
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coin Prep recovery review · CATalyst</title>
<style>
:root{color-scheme:dark;--bg-app:#0B0E14;--bg-surface:#111620;
--bg-surface-2:#1A1F2E;--border-default:rgba(255,255,255,.10);
--text-primary:#E6EDF3;--text-secondary:#8B949E;--accent-primary:#6366F1;
--font-sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
--font-mono:'JetBrains Mono','SF Mono','Fira Code','Cascadia Code',monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg-app);color:var(--text-primary);
font:14px/1.6 var(--font-sans)}.topbar{border-bottom:1px solid var(--border-default);
background:#080B11}.bar-inner,main{max-width:1120px;margin:auto;padding:20px 28px}
.bar-inner{display:flex;align-items:center;gap:12px;padding-top:16px;padding-bottom:16px}
.brand{font-size:18px;font-weight:750;letter-spacing:-.6px}.brand b{color:#a5a7ff}
.divider{width:1px;height:20px;background:var(--border-default)}.muted,.subtitle{color:var(--text-secondary)}
.badge{display:inline-flex;align-items:center;gap:7px;padding:4px 10px;border-radius:6px;
font-size:11px;font-weight:650;letter-spacing:.04em;background:rgba(245,158,11,.10);
color:#FBBF24;border:1px solid rgba(245,158,11,.22)}.badge:before{content:'';
height:6px;width:6px;border-radius:50%;background:currentColor}.bar-inner .badge{margin-left:auto}
main{padding-top:38px;padding-bottom:44px}h1{font-size:28px;line-height:1.25;
letter-spacing:-.7px;margin:8px 0 10px}.eyebrow{font-size:11px;color:#A5A7FF;
text-transform:uppercase;letter-spacing:.13em;font-weight:700}.subtitle{margin:0;max-width:720px}
.notice{display:flex;align-items:flex-start;gap:12px;margin:26px 0 24px;padding:17px 20px;
border:1px solid rgba(245,158,11,.22);border-radius:10px;background:rgba(245,158,11,.05)}
.notice-icon{color:#FBBF24;font-size:20px;line-height:1.3}.notice p{margin:3px 0 0;color:var(--text-secondary)}
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}
.card{background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;
overflow:hidden;min-width:0}.card-header{padding:17px 20px;border-bottom:1px solid var(--border-default);
display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:15px;margin:0;
font-weight:650}.tag{font-size:11px;padding:2px 8px;border-radius:5px;background:var(--bg-surface-2);
color:var(--text-secondary)}.tag.preview{color:#A5A7FF;background:rgba(99,102,241,.12)}
dl{padding:2px 20px 20px;margin:0}dt{font-size:12px;color:var(--text-secondary);margin-top:16px}
dd{margin:5px 0 0;font:12px/1.7 var(--font-mono);overflow-wrap:anywhere}
.details{margin-top:20px}.details summary{cursor:pointer;padding:17px 20px;font-weight:600;
font-size:13px}.details[open] summary{border-bottom:1px solid var(--border-default)}
.detail-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;padding:20px}
h3{font-size:12px;color:var(--text-secondary);font-weight:500;margin:0 0 10px}
ul{margin:0;padding:0;list-style:none}li{font:12px/1.7 var(--font-mono);overflow-wrap:anywhere;
padding:10px 12px;margin-bottom:8px;background:var(--bg-app);border-radius:6px;border:1px solid var(--border-default)}
.review-meta{margin-top:20px}.review-meta dl{display:grid;grid-template-columns:145px minmax(0,1fr);
align-items:baseline;column-gap:18px}footer{margin-top:24px;display:flex;align-items:center;
justify-content:space-between;gap:20px;border-top:1px solid var(--border-default);padding-top:24px}
footer p{margin:0;color:var(--text-secondary);font-size:12px}button{font:600 13px var(--font-sans);
border:1px solid var(--border-default);border-radius:7px;padding:11px 16px;white-space:nowrap;
background:var(--bg-surface-2);color:var(--text-secondary);cursor:not-allowed}
.preview-action{margin:20px 0}.preview-action button{cursor:pointer;background:var(--accent-primary);color:#fff}
.consent{margin-top:24px;padding:20px}.consent label{display:block;margin:14px 0;color:var(--text-secondary)}
.consent input[type=checkbox]{accent-color:var(--accent-primary);margin-right:6px}
.consent button:not(:disabled){background:var(--accent-primary);color:#fff;cursor:pointer}
@media(max-width:650px){.bar-inner,main{padding-left:16px;padding-right:16px}main{padding-top:26px}
.grid,.detail-grid{grid-template-columns:minmax(0,1fr)}h1{font-size:24px}.bar-inner>.muted{display:none}
.review-meta dl{display:block}footer{align-items:stretch;flex-direction:column}}
</style></head><body>
<header class="topbar"><div class="bar-inner"><span class="brand">CAT<b>alyst</b></span>
<span class="divider"></span><span class="muted">Wallet recovery</span>
<span class="badge">TRADING PAUSED</span></div></header>
<main><div class="eyebrow">Coin Prep · Recovery review</div>
<h1>Review your pending coin split</h1>
<p class="subtitle">Compare the original transaction with the unsigned replacement.
Check the fee and change before continuing with recovery.</p>
<aside class="notice"><span class="notice-icon" aria-hidden="true">&#9888;</span><div>
<strong>Your wallet needs review before trading can resume</strong>
<p>This preview has not been signed or submitted. Trading remains blocked until
the pending operation is independently reconciled.</p></div></aside>
<form class="preview-action" method="post" action="/api/safety/coin-prep-recovery-preview">
<button type="submit">Build unsigned replacement preview</button></form>
<div class="grid"><section class="card" aria-labelledby="original-heading">
<div class="card-header"><h2 id="original-heading">Original transaction</h2><span class="tag">Pending</span></div>
<dl>"""
        + rows((1, 2, 4))
        + """</dl></section>
<section class="card" aria-labelledby="preview-heading"><div class="card-header">
<h2 id="preview-heading">Replacement preview</h2><span class="tag preview">Unsigned</span></div><dl>"""
        + rows((3, 5, 6))
        + (
            '</dl></section></div><details class="card details"><summary>Inspect exact inputs and outputs</summary>'
            '<div class="detail-grid"><section><h3>Original input coins</h3><ul>'
            + input_rows
            + "</ul></section><section><h3>Replacement outputs</h3><ul>"
            + output_rows
            + '</ul></section></div></details><section class="card review-meta">'
            '<div class="card-header"><h2>Review evidence</h2></div><dl>'
            + rows((0, 7, 8, 9, 10))
            + "</dl></section>"
            + consent
            + "<footer><p>"
            + footer
            + "</p>"
            + (
                "<button disabled>Submission unavailable</button>"
                if snapshot.get("submission_available") is not True
                else ""
            )
            + "</footer></main></body></html>"
        )
    )


def render_recovery_result(
    *, attempt_id: str, fee_mojos: int, attempted: bool, accepted: bool = False
) -> str:
    """Show a one-shot submission outcome without offering a retry action."""
    safe_attempt = escape(attempt_id)
    safe_fee = escape(str(fee_mojos))
    if accepted and attempted:
        title = "Replacement submitted"
        message = (
            "Trading remains paused while CATalyst verifies which transaction "
            "confirmed on chain. Do not submit another replacement."
        )
    elif attempted:
        title = "Replacement submission recorded"
        message = (
            "Trading remains paused while CATalyst verifies which transaction "
            "confirmed on chain. The request may have reached Sage. "
            "Do not submit another replacement."
        )
    else:
        title = "Replacement was not sent"
        message = (
            "Trading remains paused. Open a fresh recovery review to see the "
            "current wallet and fee state."
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Coin Prep recovery · CATalyst</title><style>"
        ":root{color-scheme:dark;font-family:Inter,Segoe UI,sans-serif}"
        "body{margin:0;min-height:100vh;background:#0B0E14;color:#E6EDF3}"
        "header{padding:18px 28px;border-bottom:1px solid #2b3142;background:#080B11}"
        "main{max-width:760px;margin:64px auto;padding:28px;background:#111620;"
        "border:1px solid #2b3142;border-radius:12px}"
        "h1{font-size:28px;margin:0 0 12px}p{color:#8B949E;line-height:1.6}"
        "dl{display:grid;grid-template-columns:150px 1fr;gap:12px;margin:28px 0}"
        "dt{color:#8B949E}dd{margin:0;overflow-wrap:anywhere;font-family:monospace}"
        "a{display:inline-block;padding:11px 16px;border-radius:7px;"
        "background:#6366F1;color:white;text-decoration:none;font-weight:600}"
        "@media(max-width:650px){main{margin:24px 16px}dl{display:block}dt{margin-top:12px}}"
        "</style></head><body><header>CATalyst · Wallet recovery</header><main>"
        "<h1>" + title + "</h1><p>" + message + "</p><dl>"
        "<dt>Attempt</dt><dd>" + safe_attempt + "</dd>"
        "<dt>Reviewed fee</dt><dd>" + safe_fee + " mojos</dd></dl>"
        '<a href="/">Return to recovery</a></main></body></html>'
    )
