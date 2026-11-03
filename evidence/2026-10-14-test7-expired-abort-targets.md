# TEST 7 natural-expiry abort recovery (isolated)

The original TEST 7 profile was fenced before this recovery. Sage's complete
offer book showed no fillable offers or pending transactions; two abort targets
had naturally expired, but their durable intents were still open. The
cancelled refresh parent was already terminal. This discrepancy blocked
restricted startup cleanup. The exact reviewed recovery build was subsequently
run on the profile and completed the proof-only recovery described below.

This patch adds a proof-only route for one exact abort target with no Task 8
cancellation journal. It requires restricted recovery mode, stopped bot, the
owned lease and unchanged abort latch, two matching complete Sage book reads,
no pending transactions, exact wallet/asset/lineage binding, and an
`EXPIRED_PROVEN` Task 9 classification. It never submits a cancellation or
other wallet effect. Each proven target is terminalized separately; the abort
blocker remains until every exact target is terminal and a fresh empty Sage
book permits completion. A submitted cancellation continues through its
existing Task 8 proof path.

Isolated tests cover an unpublished replacement child followed by a visible
target, natural expiry, wrong target, live target, pending transaction, wrong
owner, and wrong latch generation. `tests/test_offer_reconciliation.py`,
`tests/test_refresh_safety.py`, and
`tests/test_plan_04_04_offers_endpoints.py` passed 468 tests locally on
Windows. The visible-target variant passed again after the test was extended.
The normal and restricted recovery views now expose the proof-only step before
empty-book completion; all 13 Chromium recovery UI tests and all 73 offer
endpoint tests passed. Ruff check and formatting passed. The serial local
Windows backend suite completed with 7,760 passed, 292 skipped and 457
subtests passed (exit 0); it started at source `d4be31e`, with the subsequent
UI and endpoint-only changes verified by the focused tests and exact-head CI.
All 11 checks passed on exact PR source
`6ea1ebba7ff3c271a062416388e3c9bb7b590ecc`. Independent read-only review
of that head found no actionable financial safety issue. Its remaining gap is
the restricted recovery flow against real Sage RPC and the original profile.

A clean detached package was built from that exact source. The packaged EXE
SHA-256 is `3ED71E414D23FBE5B3B499F253E08EF3F15690CB3B89B16C65121E84D6AFB0F7`.
The bundled normal and restricted recovery HTML hashes match source; all six
static package tests passed. A custom Defender scan of the package exited 0
and reported no threat detection for that package path. The exact EXE was
subsequently smoke-tested and launched as described below.

## Original TEST 7 recovery

The operator approved the exact `6ea1ebb` EXE launch. Its isolated packaged
API smoke and clean/duplicate/persisted/native-safety desktop smokes passed
before original-profile use. After closing the older read-only safety window,
the exact EXE launched as sole CATalyst PID `45820` on port 5000. The on-disk
EXE matched the hash above; Sage PID `99004` owned port 9257. The native
restricted recovery screen showed TEST 7 fingerprint `736588221`, mainnet,
the exact MZ asset, zero pending or active Sage offers, the stopped campaign,
owned renewing lease, and tripped latch generation `667`.

Through that native screen, each exact target was checked separately. Sage's
authoritative expired offer history and owned, unlocked inputs yielded durable
`EXPIRED_PROVEN` reconciliation for `9d4f…5331e` and then `ab93…901b`.
Both target intents became terminal, each with a `RECONCILE` terminal event
containing no transaction ID or spend identity. The abort latch stayed tripped
between the two checks. A fresh empty-book completion then changed only abort
`ad81…031f7` to `aborted` and resolved the specific latch at
`2026-10-14T11:04:01.470265Z`. The normal and restricted UI both showed no
active Sage offers or pending transactions. The restricted startup server still
returns 423 for normal health until the exact app is restarted, so normal
dashboard acceptance has not been credited.

Read-only poststate: no durable open offer intents; campaign `99b5…b701`
stopped at revision 2 with `0` XCH authoritative fee spend; Sage RPC reports
zero pending transactions and no active offers. Its exact owned and selectable
balances match the earlier checkpoint: `138470190098731` XCH mojos and
`780212284` MZ atomic units. No cancellation, coin preparation, publication,
or wallet transaction was sent during this recovery.

Still required: renewed long-running monitoring, secondary-PC recovery, and
cross-PC Splash peer receipt. Do not resume trading solely because this
specific abort latch resolved.

## Normal restart after recovery

The operator gave fresh action-time approval to restart this same exact EXE.
PID `45820` closed through its native window; port 5000 was free. The EXE hash
was rechecked and the same file restarted as sole CATalyst PID `131188`, owning
port 5000. Its normal `/api/health` returned 200 with `bot_running: false` and
a synced Sage wallet. The native startup connected Sage TEST 7 fingerprint
`736588221`, selected MonkeyZoo Token `MZ_XCH`, and displayed the normal
Dashboard and Offers screens. Offers showed `Active 0`, `Buy 0`, `Sell 0`,
`Pending Cancels 0`, and `No open offers`; the bot remained stopped. The
read-only `/api/safety/status` returned `allowed: true`, an owned renewing
lease, zero blocking operations, and no safety reason code. The stored abort
remained `aborted` and its exact latch remained `resolved` before restart.

The existing Splash binary was started from the native optional Splash gate;
its local process was observed as PID `169136` with ports `4000`, `4001`, and
`11511` listening. The app log confirmed its incoming hook. Market Intel still
reported `Splash offers UNAVAILABLE`, `API Status Disabled`, and zero received
offers because Splash P2P remained off in saved trading settings. Local daemon
startup therefore does not prove reciprocal peer receipt or cross-PC offer
broadcast. The normal native Dashboard, Offers, P&L, Market Intel, Settings,
Logs, Data Reset, Help, and About views were traversed read-only. Settings
showed safety `ALLOWED`, fingerprint `736588221`, and the MZ pair; no settings
were saved and no reset was invoked. No campaign or bot was started and no
wallet transaction was sent. The evidence-only PR head `88a71bd` had ten CI
checks passing and the unit-test check pending at the first post-restart
check. A new read-only exact PID/hash 60-second monitor started at
`2026-10-14T11:16:22.5026766Z` in
`E:\catalyst-stability-monitor-6ea1ebb-recovered-20261014\trace-60s.jsonl`,
PID `217064`. Its first sample showed safety allowed, owned lease, synced Sage,
stopped bot, and Windows Backup ready. This is a new stopped-profile window;
no 24-hour credit is due before `2026-10-15T11:16:22Z` plus a complete-trace
and end-state audit. Secondary-PC recovery and live Splash peer receipt remain
open.
