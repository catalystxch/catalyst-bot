import json
import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "bot_gui.html"


def _live_status(**overrides):
    status = {
        "allowed": False,
        "reason_code": "UNRESOLVED_OPERATIONS",
        "source": "operation_journal",
        "blocking_operation_count": 4,
        "lease": {
            "active": True,
            "version": 12,
            "expires_at": "2026-08-21T12:00:30.000000Z",
            "owned_by_this_run": False,
            "owner_run_id": "owner-secret-<script>alert(1)</script>",
            "owner_pid": 4455,
            "owner_host": "C:\\private\\host",
        },
    }
    status.update(overrides)
    return status


def _startup_status(**overrides):
    status = {
        "allowed": False,
        "reason_code": "UNRESOLVED_OPERATIONS",
        "source": "startup_recovery",
        "failed_check": "unresolved_operations",
        "blocker_counts": {
            "operations": 4,
            "prepared_creations": 1,
            "submitted_cancels": 2,
            "contradictory_history": 1,
            "reservations": 3,
            "publication_claims": 2,
        },
        "checks": [
            {
                "name": "lease",
                "ok": True,
                "reason_code": "",
                "source_age_seconds": 2,
                "source": "durable_snapshot",
            },
            {
                "name": "authority_revalidation",
                "ok": False,
                "reason_code": "UNRESOLVED_OPERATIONS",
                "source_age_seconds": 7,
                "source": "authorized_snapshot",
            },
        ],
        "raw_evidence": "<img src=x onerror=alert(1)>",
        "trade_id": "trade-secret",
        "offer": "offer1qqqq-secret",
    }
    status.update(overrides)
    return status


def _install_status_fakes(monkeypatch, api_server, *, live=None, startup=None):
    monkeypatch.setattr(
        api_server.mutation_gate,
        "status",
        lambda: SimpleNamespace(to_dict=lambda: live or _live_status()),
    )
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        startup or _startup_status(),
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: ("f" * 64, "mainnet"),
    )
    monkeypatch.setattr(
        api_server.database,
        "get_stability_diagnostic_counts",
        lambda: {"registry": 3, "lineage": 1, "reserve": 4, "publication": 2},
    )
    monkeypatch.setattr(api_server.database, "DB_PATH", str(GUI))
    monkeypatch.setattr(api_server.database, "_db_initialized_path", str(GUI))


def test_safety_status_adds_exact_operator_summary_without_identifier_leaks(monkeypatch):
    """Catches status expansion leaking evidence instead of fixed count/provenance fields."""
    import api_server

    _install_status_fakes(monkeypatch, api_server)

    before = datetime.now(timezone.utc)
    response = api_server.app.test_client().get("/api/safety/status")
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    body = response.get_json()
    safety = body["safety"]
    assert type(safety["allowed"]) is bool
    assert type(safety["reason_code"]) is str
    assert type(safety["source"]) is str
    assert safety["lease"] == {
        "active": True,
        "owner": "other_run",
        "version": 12,
        "expires_at": "2026-08-21T12:00:30.000000Z",
        "owned_by_this_run": False,
    }
    assert set(safety["recovery"]) == {
        "failed_check",
        "checks",
        "freshness",
        "durable_counts",
    }
    freshness = safety["recovery"]["freshness"]
    assert set(freshness) == {
        "observed_at_utc",
        "age_seconds",
        "max_age_seconds",
        "provenance",
        "valid",
    }
    observed = datetime.fromisoformat(freshness["observed_at_utc"].replace("Z", "+00:00"))
    assert before <= observed <= after
    assert freshness == {
        "observed_at_utc": freshness["observed_at_utc"],
        "age_seconds": 0,
        "max_age_seconds": 30,
        "provenance": "live_gate_and_durable_snapshot",
        "valid": True,
    }
    assert safety["recovery"]["durable_counts"] == {
        "registry": 3,
        "lineage": 1,
        "reserve": 4,
        "publication": 2,
    }
    serialized = json.dumps(body, sort_keys=True)
    for secret in (
        "secret-parent",
        "secret-child",
        "secret-publication",
        "trade-secret",
        "offer1qqqq-secret",
        "owner-secret",
        "4455",
        "C:\\private\\host",
        "<img",
        "<script>",
        "f" * 64,
    ):
        assert secret not in serialized


def test_malformed_internal_status_fails_closed_to_allowlisted_values(monkeypatch):
    """Catches optimistic green or arbitrary strings when internal status is hostile."""
    import api_server

    hostile = '<img src=x onerror="alert(1)">&\' / C:\\secret'
    _install_status_fakes(
        monkeypatch,
        api_server,
        live=_live_status(
            allowed=True,
            reason_code=hostile,
            source=hostile,
            blocking_operation_count=True,
            lease={
                "active": "yes",
                "version": -99,
                "expires_at": hostile,
                "owned_by_this_run": True,
            },
        ),
        startup=_startup_status(
            allowed=True,
            reason_code=hostile,
            source=hostile,
            failed_check=hostile,
            blocker_counts={"operations": "many"},
            checks=[
                {
                    "name": hostile,
                    "ok": True,
                    "reason_code": hostile,
                    "source_age_seconds": -1,
                    "source": hostile,
                }
            ],
        ),
    )
    monkeypatch.setattr(
        api_server.database,
        "get_stability_diagnostic_counts",
        lambda: {
            "registry": "<img onerror=alert(1)>",
            "lineage": -1,
            "reserve": True,
            "publication": None,
        },
    )

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 200
    safety = response.get_json()["safety"]
    assert safety["allowed"] is False
    assert safety["reason_code"] == "DURABLE_STATE_UNAVAILABLE"
    assert safety["source"] == "durable_read"
    assert safety["lease"] == {
        "active": False,
        "owner": None,
        "version": 0,
        "expires_at": None,
        "owned_by_this_run": False,
    }
    assert safety["identity"]["lease_owner"] is None
    assert safety["blocking_operation_count"] == 0
    assert safety["recovery"]["failed_check"] == "startup_recovery"
    assert safety["recovery"]["checks"] == []
    assert safety["recovery"]["freshness"] == {
        "observed_at_utc": None,
        "age_seconds": None,
        "max_age_seconds": 30,
        "provenance": "unavailable",
        "valid": False,
    }
    assert safety["recovery"]["durable_counts"] == {
        "registry": 0,
        "lineage": 0,
        "reserve": 0,
        "publication": 0,
    }
    assert hostile not in json.dumps(safety, sort_keys=True)


def test_app_bridge_safety_status_is_structured_and_never_raises(monkeypatch):
    """Catches desktop diagnostics bypassing the existing safe bridge contract."""
    import api_server
    import app_bridge

    _install_status_fakes(monkeypatch, api_server)
    result = app_bridge.AppBridge().get_safety_status()
    assert result["success"] is True
    assert result["safety"]["recovery"]["durable_counts"] == {
        "registry": 3,
        "lineage": 1,
        "reserve": 4,
        "publication": 2,
    }

    monkeypatch.setattr(
        api_server,
        "api_safety_status",
        lambda: (_ for _ in ()).throw(RuntimeError("C:\\secret\\bot.db")),
    )
    assert app_bridge.AppBridge().get_safety_status() == {
        "success": False,
        "error": "Internal error — check bot logs for details",
    }


def test_canonical_extensible_api_reason_code_is_preserved(monkeypatch):
    """Catches legitimate durable latch codes being replaced by a generic blocker."""
    import api_server

    _install_status_fakes(
        monkeypatch,
        api_server,
        live=_live_status(reason_code="RUNTIME_DISCONTINUITY"),
        startup=_startup_status(allowed=True, reason_code="", failed_check=None),
    )

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 200
    safety = response.get_json()["safety"]
    assert safety["allowed"] is False
    assert safety["reason_code"] == "RUNTIME_DISCONTINUITY"
    assert safety["recommended_action"] == "REVIEW_SAFETY_DIAGNOSTICS"

def test_app_bridge_safety_status_rejects_non_dict_route_payload(monkeypatch):
    """Catches malformed Flask results escaping the bridge's dict contract."""
    import api_server
    import app_bridge

    monkeypatch.setattr(
        api_server,
        "api_safety_status",
        lambda: api_server.jsonify(["<script>alert(1)</script>"]),
    )

    assert app_bridge.AppBridge().get_safety_status() == {
        "success": False,
        "error": "Internal error — check bot logs for details",
    }


def test_database_diagnostic_counts_use_real_fixed_aggregate(tmp_path, monkeypatch):
    """Catches wrong aggregate predicates against real temporary durable rows."""
    import hashlib
    import database

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "diagnostics.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    conn = database.get_connection()
    selected_json = '["' + ("c" * 64) + '"]'
    selected_sha = hashlib.sha256(selected_json.encode("utf-8")).hexdigest()
    intent_values = {
        "run_id": "run-test",
        "wallet_fingerprint_hash": "f" * 64,
        "network": "mainnet",
        "asset_id": "a" * 64,
        "side": "buy",
        "tier": "small",
        "purpose": "lifecycle",
        "offered_amount_atomic": "1",
        "requested_amount_atomic": "2",
        "selected_coin_ids_json": selected_json,
        "selected_coin_ids_sha256": selected_sha,
        "lifecycle_state": "terminal",
        "prepared_at": "2026-08-21T12:00:00.000000Z",
        "updated_at": "2026-08-21T12:00:00.000000Z",
    }
    for intent_id, parent_id in (
        ("intent-parent", None),
        ("intent-child", "intent-parent"),
        ("intent-standalone", None),
    ):
        conn.execute(
            "INSERT INTO offer_intents (intent_id,run_id,wallet_fingerprint_hash,"
            "network,asset_id,side,tier,purpose,parent_intent_id,offered_amount_atomic,"
            "requested_amount_atomic,selected_coin_ids_json,selected_coin_ids_sha256,"
            "lifecycle_state,prepared_at,updated_at) VALUES "
            "(:intent_id,:run_id,:wallet_fingerprint_hash,:network,:asset_id,:side,"
            ":tier,:purpose,:parent_intent_id,:offered_amount_atomic,"
            ":requested_amount_atomic,:selected_coin_ids_json,"
            ":selected_coin_ids_sha256,:lifecycle_state,:prepared_at,:updated_at)",
            {**intent_values, "intent_id": intent_id, "parent_intent_id": parent_id},
        )
    for coin_id, status, trade_id in (
        ("coin-locked", "locked", None),
        ("coin-owned", "free", "trade-owner"),
        ("coin-both", "locked", "trade-owner-2"),
        ("coin-free", "free", None),
    ):
        conn.execute(
            "INSERT INTO coins (coin_id,wallet_type,amount_mojos,status,trade_id,"
            "first_seen,last_seen) VALUES (?,?,1,?,?,?,?)",
            (
                coin_id,
                "xch",
                status,
                trade_id,
                "2026-08-21T12:00:00.000000Z",
                "2026-08-21T12:00:00.000000Z",
            ),
        )
    for index in range(2):
        conn.execute(
            "INSERT INTO publication_outbox (publication_id,idempotency_key,network,"
            "offer_fingerprint,publication_epoch,publisher,payload_json,payload_sha256,"
            "queued_at,updated_at) VALUES (?,?,?,?,?,'dexie','{}',?,?,?)",
            (
                f"publication-{index}",
                f"key-{index}",
                "mainnet",
                f"fingerprint-{index}",
                f"epoch-{index}",
                hashlib.sha256(b"{}").hexdigest(),
                "2026-08-21T12:00:00.000000Z",
                "2026-08-21T12:00:00.000000Z",
            ),
        )
    conn.commit()

    assert database.get_stability_diagnostic_counts() == {
        "registry": 3,
        "lineage": 1,
        "reserve": 3,
        "publication": 2,
    }
    database.close_connection()


def test_safety_status_never_calls_unbounded_row_repository_reads(monkeypatch):
    """Catches frequent operator polling enumerating registry or publication rows."""
    import api_server

    _install_status_fakes(monkeypatch, api_server)
    calls = []

    def forbidden(name):
        def fail(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"unbounded diagnostics read: {name}")

        return fail

    monkeypatch.setattr(
        api_server.database,
        "get_offer_intents_for_registry",
        forbidden("registry"),
    )
    monkeypatch.setattr(
        api_server.database,
        "list_publication_outbox",
        forbidden("publication"),
    )

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 200
    assert calls == []
    assert response.get_json()["safety"]["recovery"]["durable_counts"] == {
        "registry": 3,
        "lineage": 1,
        "reserve": 4,
        "publication": 2,
    }


def test_existing_preinit_database_never_hides_persisted_diagnostic_counts(monkeypatch):
    """Catches a process-local init marker turning an existing DB into false zeros."""
    import api_server

    _install_status_fakes(monkeypatch, api_server)
    calls = []

    def aggregate():
        calls.append("aggregate")
        return {"registry": 9, "lineage": 4, "reserve": 6, "publication": 3}

    monkeypatch.setattr(
        api_server.database,
        "get_stability_diagnostic_counts",
        aggregate,
    )
    monkeypatch.setattr(api_server.database, "_db_initialized_path", "")

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 200
    assert calls == ["aggregate"]
    assert response.get_json()["safety"]["recovery"]["durable_counts"] == {
        "registry": 9,
        "lineage": 4,
        "reserve": 6,
        "publication": 3,
    }

class _PanelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.panel_seen = False
        self.panel_attrs = {}
        self.descendant_attrs = []
        self.ids = set()
        self.data_actions = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "safetyDiagnosticsPanel":
            self.panel_seen = True
            self.depth = 1
            self.panel_attrs = attrs
        elif self.depth:
            self.depth += 1
        if self.depth:
            self.descendant_attrs.append(attrs)
            if attrs.get("id"):
                self.ids.add(attrs["id"])
            if "data-safety-action" in attrs:
                self.data_actions.append(attrs["data-safety-action"])

    def handle_endtag(self, _tag):
        if self.depth:
            self.depth -= 1


def test_panel_is_semantic_blocked_while_unknown_and_has_only_fixed_actions():
    """Catches missing/unknown status appearing green or dynamic data entering handlers."""
    parser = _PanelParser()
    parser.feed(GUI.read_text(encoding="utf-8"))

    assert parser.panel_seen
    assert parser.panel_attrs["role"] == "status"
    assert parser.panel_attrs["aria-live"] == "polite"
    assert "is-blocked" in parser.panel_attrs["class"].split()
    assert {
        "safetyDiagnosticsState",
        "safetyDiagnosticsReason",
        "safetyDiagnosticsFreshness",
        "safetyDiagnosticsUnresolved",
        "safetyDiagnosticsLease",
        "safetyDiagnosticsBinding",
        "safetyDiagnosticsCounts",
        "safetyDiagnosticsAction",
        "safetyDiagnosticsError",
    } <= parser.ids
    assert parser.data_actions == ["refresh"]
    assert all(
        name == "data-safety-action"
        for attrs in parser.descendant_attrs
        for name in attrs
        if name.startswith("data-")
    )
    assert all(
        not any(name.lower().startswith("on") for name in attrs)
        for attrs in parser.descendant_attrs
    )


def _diagnostics_javascript() -> str:
    html = GUI.read_text(encoding="utf-8")
    start_marker = "// SAFETY_DIAGNOSTICS_BEGIN"
    end_marker = "// SAFETY_DIAGNOSTICS_END"
    start = html.index(start_marker) + len(start_marker)
    end = html.index(end_marker, start)
    return html[start:end]


def _run_node(assertions: str) -> None:
    harness = r"""
const assert = require('assert');
class FakeClassList {
  constructor() { this.values = new Set(); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  toggle(value, force) {
    if (force === true) this.values.add(value);
    else if (force === false) this.values.delete(value);
    else if (this.values.has(value)) this.values.delete(value);
    else this.values.add(value);
  }
}
class FakeElement {
  constructor(id) {
    this.id = id;
    this.textContent = '';
    this.disabled = false;
    this.classList = new FakeClassList();
    this.listeners = {};
    this.attrs = {};
  }
  set innerHTML(_value) { throw new Error('diagnostics must not assign innerHTML'); }
  addEventListener(type, callback) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(callback);
  }
  removeEventListener(type, callback) {
    if (!this.listeners[type]) return;
    this.listeners[type] = this.listeners[type].filter(item => item !== callback);
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  contains(element) { return element === this || element.panel === this; }
}
const ids = [
  'safetyDiagnosticsPanel', 'safetyDiagnosticsState', 'safetyDiagnosticsReason',
  'safetyDiagnosticsFreshness', 'safetyDiagnosticsUnresolved',
  'safetyDiagnosticsLease', 'safetyDiagnosticsBinding', 'safetyDiagnosticsCounts',
  'safetyDiagnosticsAction', 'safetyDiagnosticsError',
  'safetyDiagnosticsRefresh'
];
const elements = Object.fromEntries(ids.map(id => [id, new FakeElement(id)]));
const document = { getElementById: id => elements[id] || null };
const API_URL = '/api';
let timeoutCalls = 0;
let clearCalls = 0;
let queuedTimers = [];
function setTimeout(callback, _delay) {
  timeoutCalls += 1;
  queuedTimers.push(callback);
  return timeoutCalls;
}
function clearTimeout(_timer) { clearCalls += 1; }
let apiCalls = 0;
let apiPayload = null;
async function apiFetch(path) {
  apiCalls += 1;
  assert.strictEqual(path, '/api/safety/status');
  return { ok: true, json: async () => apiPayload };
}
"""
    script = harness + _diagnostics_javascript() + "\n" + assertions
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_hostile_payload_is_redacted_and_rendered_without_executable_markup():
    """Catches hostile server strings entering markup, attributes, or operator copy."""
    _run_node(
        r"""
const hostile = '<img src=x onerror=alert(1)>\'\"&<script>alert(2)</script>';
renderSafetyDiagnosticsStatus({
  allowed: true,
  reason_code: hostile,
  source: hostile,
  blocking_operation_count: 9,
  blocker_counts: { operations: 9, reservations: 2, publication_claims: 3 },
  lease: { active: true, owner: hostile, version: 4, expires_at: hostile },
  recovery: {
    failed_check: hostile,
    freshness: { age_seconds: 5, provenance: hostile },
    durable_counts: { registry: 8, lineage: 3, reserve: 11, publication: 6 }
  },
  recommended_action: hostile,
  raw_evidence: hostile,
  blocker_ids: [hostile]
});
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsReason.textContent, 'Unknown safety status');
assert.strictEqual(elements.safetyDiagnosticsFreshness.textContent, 'Unknown / stale · unavailable');
assert.strictEqual(elements.safetyDiagnosticsLease.textContent, 'Unknown');
assert.strictEqual(elements.safetyDiagnosticsAction.textContent, 'Review safety diagnostics');
const rendered = Object.values(elements).map(el => el.textContent).join(' ');
assert.ok(!rendered.includes('<img'));
assert.ok(!rendered.includes('<script>'));
assert.ok(!rendered.includes('onerror'));
assert.ok(elements.safetyDiagnosticsPanel.classList.values.has('is-blocked'));
assert.ok(!elements.safetyDiagnosticsPanel.classList.values.has('is-allowed'));
"""
    )


def test_canonical_extensible_reason_code_remains_operator_visible():
    """Catches legitimate new latch blockers being collapsed into unknown UI copy."""
    _run_node(
        r"""
Date.now = () => Date.parse('2026-08-21T12:00:05.000Z');
renderSafetyDiagnosticsStatus({
  allowed: false,
  reason_code: 'RUNTIME_DISCONTINUITY',
  source: 'durable_latch',
  blocking_operation_count: 1,
  blocker_counts: { operations: 1, reservations: 0, publication_claims: 0 },
  identity: { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'mainnet', lease_owner: 'this_run' },
  lease: { active: true, owner: 'this_run', version: 4, expires_at: '2026-08-21T12:00:30.000000Z' },
  recovery: {
    failed_check: 'authority_revalidation',
    freshness: {
      observed_at_utc: '2026-08-21T12:00:00.000000Z',
      age_seconds: 0,
      max_age_seconds: 30,
      provenance: 'live_gate_and_durable_snapshot',
      valid: true
    },
    durable_counts: { registry: 2, lineage: 1, reserve: 1, publication: 0 }
  },
  recommended_action: 'REVIEW_SAFETY_DIAGNOSTICS'
});
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsReason.textContent, 'RUNTIME_DISCONTINUITY');
assert.strictEqual(elements.safetyDiagnosticsError.textContent, '');
"""
    )


def test_recognized_reason_keeps_exact_stable_code_visible():
    """Catches friendly copy replacing the stable operator reason code."""
    _run_node(
        r"""
Date.now = () => Date.parse('2026-08-21T12:00:05.000Z');
renderSafetyDiagnosticsStatus({
  allowed: false,
  reason_code: 'UNRESOLVED_OPERATIONS',
  source: 'operation_journal',
  blocking_operation_count: 2,
  blocker_counts: { operations: 2, reservations: 1, publication_claims: 0 },
  identity: { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'mainnet', lease_owner: 'this_run' },
  lease: { active: true, owner: 'this_run', version: 4, expires_at: '2026-08-21T12:02:00.000000Z' },
  recovery: {
    failed_check: 'unresolved_operations',
    freshness: {
      observed_at_utc: '2026-08-21T12:00:00.000000Z',
      age_seconds: 0,
      max_age_seconds: 30,
      provenance: 'live_gate_and_durable_snapshot',
      valid: true
    },
    durable_counts: { registry: 2, lineage: 1, reserve: 1, publication: 0 }
  },
  recommended_action: 'RUN_AUTHORITATIVE_RECONCILIATION'
});
assert.strictEqual(
  elements.safetyDiagnosticsReason.textContent,
  'UNRESOLVED_OPERATIONS — Unresolved operations require review'
);
"""
    )


def test_stale_current_authority_observation_is_visibly_blocked():
    """Catches an old but otherwise valid cached payload remaining green."""
    _run_node(
        r"""
Date.now = () => Date.parse('2026-08-21T12:01:00.000Z');
renderSafetyDiagnosticsStatus({
  allowed: true,
  reason_code: '',
  source: 'lease',
  blocking_operation_count: 0,
  blocker_counts: { operations: 0, reservations: 0, publication_claims: 0 },
  identity: { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'mainnet', lease_owner: 'this_run' },
  lease: { active: true, owner: 'this_run', version: 4, expires_at: '2026-08-21T12:02:00.000000Z' },
  recovery: {
    failed_check: null,
    freshness: {
      observed_at_utc: '2026-08-21T12:00:00.000000Z',
      age_seconds: 0,
      max_age_seconds: 30,
      provenance: 'live_gate_and_durable_snapshot',
      valid: true
    },
    durable_counts: { registry: 2, lineage: 1, reserve: 1, publication: 0 }
  },
  recommended_action: 'NONE'
});
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsFreshness.textContent, '60s old · live gate + durable snapshot');
assert.ok(elements.safetyDiagnosticsError.textContent.includes('stale'));
assert.ok(elements.safetyDiagnosticsPanel.classList.values.has('is-blocked'));
assert.ok(!elements.safetyDiagnosticsPanel.classList.values.has('is-allowed'));
"""
    )


def test_nonexistent_utc_observation_date_fails_closed():
    """Catches format-shaped but noncanonical UTC dates being treated as fresh."""
    _run_node(
        r"""
Date.now = () => Date.parse('2026-03-03T12:00:05.000Z');
renderSafetyDiagnosticsStatus({
  allowed: true,
  reason_code: '',
  source: 'lease',
  blocking_operation_count: 0,
  blocker_counts: { operations: 0, reservations: 0, publication_claims: 0 },
  identity: { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'mainnet', lease_owner: 'this_run' },
  lease: { active: true, owner: 'this_run', version: 4, expires_at: '2026-03-03T12:02:00.000000Z' },
  recovery: {
    failed_check: null,
    freshness: {
      observed_at_utc: '2026-02-31T12:00:00.000000Z',
      age_seconds: 0,
      max_age_seconds: 30,
      provenance: 'live_gate_and_durable_snapshot',
      valid: true
    },
    durable_counts: { registry: 2, lineage: 1, reserve: 1, publication: 0 }
  },
  recommended_action: 'NONE'
});
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsFreshness.textContent, 'Unknown / stale · unavailable');
"""
    )


def test_inconsistent_reported_freshness_age_fails_closed():
    """Catches a bounded but contradictory server age being accepted as fresh."""
    _run_node(
        r"""
Date.now = () => Date.parse('2026-08-21T12:00:05.000Z');
renderSafetyDiagnosticsStatus({
  allowed: true,
  reason_code: '',
  source: 'lease',
  blocking_operation_count: 0,
  blocker_counts: { operations: 0, reservations: 0, publication_claims: 0 },
  identity: { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'mainnet', lease_owner: 'this_run' },
  lease: { active: true, owner: 'this_run', version: 4, expires_at: '2026-08-21T12:02:00.000000Z' },
  recovery: {
    failed_check: null,
    freshness: {
      observed_at_utc: '2026-08-21T12:00:00.000000Z',
      age_seconds: 36000,
      max_age_seconds: 30,
      provenance: 'live_gate_and_durable_snapshot',
      valid: true
    },
    durable_counts: { registry: 2, lineage: 1, reserve: 1, publication: 0 }
  },
  recommended_action: 'NONE'
});
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsFreshness.textContent, 'Unknown / stale · unavailable');
"""
    )


def test_redacted_wallet_network_binding_is_rendered_and_required():
    """Catches the API binding being omitted from the operator panel."""
    _run_node(
        r"""
Date.now = () => Date.parse('2026-08-21T12:00:05.000Z');
const safety = {
  allowed: true,
  reason_code: '',
  source: 'lease',
  blocking_operation_count: 0,
  blocker_counts: { operations: 0, reservations: 0, publication_claims: 0 },
  identity: { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'mainnet', lease_owner: 'this_run' },
  lease: { active: true, owner: 'this_run', version: 4, expires_at: '2026-08-21T12:02:00.000000Z' },
  recovery: {
    failed_check: null,
    freshness: {
      observed_at_utc: '2026-08-21T12:00:00.000000Z',
      age_seconds: 0,
      max_age_seconds: 30,
      provenance: 'live_gate_and_durable_snapshot',
      valid: true
    },
    durable_counts: { registry: 2, lineage: 1, reserve: 1, publication: 0 }
  },
  recommended_action: 'NONE'
};
renderSafetyDiagnosticsStatus(safety);
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Allowed');
assert.strictEqual(elements.safetyDiagnosticsBinding.textContent, 'Wallet sha256:ffffffffffff… · Network mainnet');
safety.identity = { wallet_fingerprint: 'sha256:ffffffffffff…', network: 'unknown', lease_owner: 'this_run' };
renderSafetyDiagnosticsStatus(safety);
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsBinding.textContent, 'Unknown');
safety.identity = { wallet_fingerprint: '<img onerror=alert(1)>', network: 'mainnet<script>', lease_owner: 'this_run' };
renderSafetyDiagnosticsStatus(safety);
assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
assert.strictEqual(elements.safetyDiagnosticsBinding.textContent, 'Unknown');
assert.ok(!elements.safetyDiagnosticsBinding.textContent.includes('<'));
"""
    )


def test_listener_and_bounded_polling_are_idempotent_and_do_not_retry_mutations():
    """Catches tab switches multiplying listeners/timers or diagnostics mutating state."""
    source = _diagnostics_javascript()
    assert "/quarantine" not in source
    assert "confirmed: true" not in source
    _run_node(
        r"""
(async () => {
  apiPayload = {
    success: true,
    safety: {
      allowed: false,
      reason_code: 'UNRESOLVED_OPERATIONS',
      source: 'operation_journal',
      blocking_operation_count: 2,
      blocker_counts: { operations: 2, reservations: 1, publication_claims: 0 },
      lease: { active: true, owner: 'this_run', version: 3, expires_at: '2026-08-21T12:00:30.000000Z' },
      recovery: {
        failed_check: 'unresolved_operations',
        freshness: { age_seconds: 4, provenance: 'authorized_snapshot' },
        durable_counts: { registry: 5, lineage: 2, reserve: 7, publication: 1 }
      },
      recommended_action: 'RUN_AUTHORITATIVE_RECONCILIATION'
    }
  };
  installSafetyDiagnosticsActions();
  installSafetyDiagnosticsActions();
  assert.strictEqual(elements.safetyDiagnosticsPanel.listeners.click.length, 1);
  startSafetyDiagnosticsPolling();
  startSafetyDiagnosticsPolling();
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(apiCalls, 1);
  assert.strictEqual(timeoutCalls, 1);
  assert.strictEqual(elements.safetyDiagnosticsState.textContent, 'Blocked');
  assert.strictEqual(elements.safetyDiagnosticsCounts.textContent, 'Registry 5 · Lineage 2 · Reserve 7 · Publication 1');
  stopSafetyDiagnosticsPolling();
  stopSafetyDiagnosticsPolling();
  assert.strictEqual(clearCalls, 1);
  assert.strictEqual(elements.safetyDiagnosticsPanel.listeners.click.length, 0);
  startSafetyDiagnosticsPolling();
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(elements.safetyDiagnosticsPanel.listeners.click.length, 1);
  assert.strictEqual(apiCalls, 2);
  assert.strictEqual(timeoutCalls, 2);
  stopSafetyDiagnosticsPolling();
  assert.strictEqual(clearCalls, 2);
  assert.strictEqual(elements.safetyDiagnosticsPanel.listeners.click.length, 0);
  const replacementPanel = new FakeElement('safetyDiagnosticsPanel');
  elements.safetyDiagnosticsPanel = replacementPanel;
  installSafetyDiagnosticsActions();
  installSafetyDiagnosticsActions();
  assert.strictEqual(replacementPanel.listeners.click.length, 1);
})().catch(error => { console.error(error); process.exit(1); });
"""
    )


def test_desktop_api_abstraction_maps_the_existing_safety_status_bridge():
    """Catches desktop mode bypassing AppBridge while browser mode uses the same route."""
    html = GUI.read_text(encoding="utf-8")
    assert "clean === 'safety/status'" in html
    assert "return 'get_safety_status'" in html
    assert "apiFetch(`${API_URL}/safety/status`)" in html
