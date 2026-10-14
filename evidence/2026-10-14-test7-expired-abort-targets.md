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
Ruff check and formatting passed.

Still required: full CI on this exact PR head, independent review, clean
package/Defender and native smoke, a fresh action-time wallet/safety preflight,
and operator-approved launch of an exact reviewed build before original-profile
proof-only reconciliation. Do not clear the live latch or resume trading based
on isolated tests alone.
