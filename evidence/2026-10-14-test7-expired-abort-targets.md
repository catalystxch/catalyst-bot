# TEST 7 natural-expiry abort recovery (isolated)

The original TEST 7 profile remains fenced. The installed app is a read-only
Startup Safety diagnostic, and this patch has **not** been run on that profile.
Sage's complete offer book showed no fillable offers or pending transactions;
two abort targets had naturally expired, but their durable intents were still
open. The cancelled refresh parent was already terminal. This discrepancy
blocked restricted startup cleanup.

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
and reported no threat detection for that package path. The EXE has not been
launched or smoke-tested.

Still required: packaged isolated and native smoke, a fresh action-time
wallet/safety preflight, and operator-approved launch of this exact reviewed
build before original-profile proof-only reconciliation. Do not clear the live
latch or resume trading based on isolated tests alone.
