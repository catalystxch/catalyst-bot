"""Real manual cancellation DOM, isolated from every live network/wallet action."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture
def cancel_page(page):
    source = (Path(__file__).resolve().parents[2] / "bot_gui.html").read_text(
        encoding="utf-8"
    )
    markup = source.split('    <div class="modal" id="cancelConfirmModal">', 1)[
        1
    ].split('    <div class="modal" id="boostConfirmModal">', 1)[0]
    script = (
        "let _cancelAllContext = null;"
        + source.split("let _cancelAllContext = null;", 1)[1].split(
            "// ---- Close the Gap button ----", 1
        )[0]
    )
    script += (
        "function updateCancelAllButtonState"
        + source.split("function updateCancelAllButtonState", 1)[1].split(
            "// =================================================================", 1
        )[0]
    )
    page.route("**/*", lambda route: route.abort())
    page.set_content(
        '<button id="cancelAllBtn" onclick="cancelAllOffers()">Cancel All</button><div class="modal" id="cancelConfirmModal">'
        + markup
    )
    page.add_script_tag(
        content="""
        const API_URL='/api';
        let bot_state={running:false,offers:{buy:[{},{}],sell:[]}};
        window.calls=[]; window.logs=[]; window.toasts=[];
        window.stopResponses=[{success:true,stopped:true}];
        window.cancelStatus={success:true,confirmation_mode:true,running:false,
            phase:'complete',complete:true,total:2,pending:0,failed:0,
            cancelled:2,closed:0,resolved:2,remaining:0,authoritative_complete:true};
        window.cancelResponse={success:true,async:true,total:2};
        const originalInterval=window.setInterval.bind(window);
        window.setInterval=(fn,ms)=>originalInterval(fn,Math.min(ms,20));
        function addLogEntry(level,message){logs.push({level,message});}
        function showToast(message,severity){toasts.push({message,severity});}
        function debugWarn(){}
        async function fetchStatus(){}
        function updateResumeOverview(){}
        async function apiFetch(path,options={}){
            calls.push({path,body:options.body?JSON.parse(options.body):null});
            let value;
            if(path.endsWith('/bot/stop')) value=stopResponses.length>1?stopResponses.shift():stopResponses[0];
            else if(path.endsWith('/cancel_all/status')) value=cancelStatus;
            else if(path.endsWith('/cancel_all')) value=cancelResponse;
            else throw Error('Unexpected request '+path);
            return {json:async()=>value};
        }
    """
        + script
    )
    page.evaluate("cancelAllOffers()")
    return page


def test_manual_cancel_drains_and_requests_authoritative_confirmation(cancel_page):
    page = cancel_page
    page.locator("#cancelAllConfirmBtn").click()
    page.wait_for_function("!_cancelAllInProgress")
    calls = page.evaluate("calls")
    assert calls[0]["path"] == "/api/bot/stop"
    assert calls[0]["body"] == {"wait_for_workers": True, "settle_cancellations": True}
    submission = next(c for c in calls if c["path"] == "/api/offers/cancel_all")
    assert submission["body"] == {"wait_for_confirmation": True}
    assert (
        "2 cancellations confirmed"
        in page.locator("#cancelProgressMessage").inner_text()
    )


@pytest.mark.parametrize(
    "response", [{"success": False, "error": "stop failed"}, {"stopped": True}]
)
def test_manual_cancel_never_submits_after_unverified_stop(cancel_page, response):
    page = cancel_page
    page.evaluate("s=>{stopResponses=[s]}", response)
    page.locator("#cancelAllConfirmBtn").click()
    page.wait_for_function("!_cancelAllInProgress")
    assert not any(
        c["path"] == "/api/offers/cancel_all" for c in page.evaluate("calls")
    )
    assert page.evaluate("toasts.some(t=>t.severity==='error')")


def test_manual_cancel_waits_for_late_proof_before_submission(cancel_page):
    page = cancel_page
    page.evaluate(
        "stopResponses=[{success:true,stopped:false,status:'confirming'},{success:true,stopped:true}]"
    )
    page.locator("#cancelAllConfirmBtn").click()
    page.wait_for_function("calls.some(c=>c.path==='/api/offers/cancel_all')")
    assert [c["path"] for c in page.evaluate("calls")][:3] == ["/api/bot/stop"] * 2 + [
        "/api/offers/cancel_all"
    ]


@pytest.mark.parametrize(
    "changes", [{"pending": 1}, {"resolved": 1}, {"authoritative_complete": False}]
)
def test_manual_completion_requires_consistent_authoritative_totals(
    cancel_page, changes
):
    page = cancel_page
    page.evaluate("s=>{Object.assign(cancelStatus,s)}", changes)
    page.locator("#cancelAllConfirmBtn").click()
    page.wait_for_function("!_cancelAllInProgress")
    assert page.evaluate("toasts.some(t=>t.severity==='error')")
    assert not page.evaluate("toasts.some(t=>t.severity==='success')")


def test_manual_confirmation_progress_counts_proof_not_pending_requests(cancel_page):
    view = cancel_page.evaluate(
        "cancelAllProgressView({...cancelStatus,phase:'confirming',running:true,complete:false,total:5,resolved:2,cancelled:2,pending:1,remaining:3,authoritative_complete:false},5)"
    )
    assert view["processed"] == 2
    assert view["severity"] == "info"
    assert "2" in view["message"] and "3 remaining" in view["message"]


def test_empty_local_book_does_not_disable_authoritative_wallet_check(cancel_page):
    page = cancel_page
    page.evaluate(
        "bot_state.offers={buy:[],sell:[]}; updateCancelAllButtonState(false)"
    )
    assert page.locator("#cancelAllBtn").is_enabled()


@pytest.mark.parametrize("hung_path", ["/bot/stop", "/offers/cancel_all"])
def test_unanswered_manual_request_surfaces_timeout_without_stuck_close_guard(
    cancel_page, hung_path
):
    page = cancel_page
    page.clock.install()
    page.evaluate(
        "suffix=>{const previous=apiFetch; apiFetch=(path,options)=>path.endsWith(suffix)?new Promise(resolve=>{window.resolveLate=resolve}):previous(path,options)}",
        hung_path,
    )
    page.locator("#cancelAllConfirmBtn").click()
    page.clock.fast_forward(120001)
    page.wait_for_function("!_cancelAllInProgress")
    assert page.evaluate("window._catalystCancelAllFlowActive") is False
    assert "timed out" in page.locator("#cancelProgressMessage").inner_text()
    if hung_path == "/bot/stop":
        page.evaluate(
            "async()=>{resolveLate({json:async()=>({success:true,stopped:true})}); await Promise.resolve(); await Promise.resolve();}"
        )
        assert not any(
            c["path"] == "/api/offers/cancel_all" for c in page.evaluate("calls")
        )


def test_authoritative_empty_wallet_completes_without_submission_worker(cancel_page):
    page = cancel_page
    page.evaluate(
        "cancelResponse={success:true,cancelled:0,authoritative_complete:true}"
    )
    page.locator("#cancelAllConfirmBtn").click()
    page.wait_for_function("!_cancelAllInProgress")
    assert page.locator("#cancelProgressProcessed").inner_text() == "0 / 0"
    assert page.evaluate(
        "logs.some(e=>e.level==='success' && e.message.includes('No active offers remain'))"
    )


def test_manual_timeout_extends_only_for_increasing_proven_count(cancel_page):
    page = cancel_page
    page.clock.install()
    page.evaluate(
        "cancelStatus={...cancelStatus,phase:'confirming',running:true,complete:false,authoritative_complete:false,resolved:0,cancelled:0,remaining:2}; cancelResponse.total=2"
    )
    page.evaluate("confirmCancelAll()")
    page.evaluate("stopCancelAllProgressPolling()")
    page.clock.fast_forward(890000)
    page.evaluate(
        "async()=>{cancelStatus.resolved=1; cancelStatus.cancelled=1; cancelStatus.remaining=1; await pollCancelAllProgressOnce(2);}"
    )
    page.clock.fast_forward(20000)
    assert page.evaluate("_cancelAllInProgress") is True
    page.evaluate("pollCancelAllProgressOnce(2)")
    page.clock.fast_forward(880001)
    page.wait_for_function("!_cancelAllInProgress")
    assert "timed out" in page.locator("#cancelProgressMessage").inner_text()


def test_manual_keeps_waiting_past_five_minutes_for_confirmed_worker(cancel_page):
    page = cancel_page
    page.clock.install()
    page.evaluate(
        "cancelStatus={...cancelStatus,phase:'confirming',running:true,complete:false,authoritative_complete:false,resolved:0,cancelled:0,remaining:2}"
    )
    page.evaluate("confirmCancelAll()")
    page.clock.fast_forward(480000)
    assert page.evaluate("_cancelAllInProgress") is True
    assert page.evaluate("window._catalystCancelAllFlowActive") is True
    page.evaluate(
        "cancelStatus={...cancelStatus,phase:'complete',running:false,complete:true,authoritative_complete:true,resolved:2,cancelled:2,remaining:0}; pollCancelAllProgressOnce(2)"
    )
    page.clock.run_for(2100)
    assert page.evaluate("_cancelAllInProgress") is False
    assert (
        "2 cancellations confirmed"
        in page.locator("#cancelProgressMessage").inner_text()
    )
