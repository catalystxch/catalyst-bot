# Sage TLS handshake before final lease recheck

The preceding `b5725c3` change rechecked the mutation lease immediately
before `http.client.HTTPSConnection.request()`. Python's HTTP connection can
perform its TLS handshake lazily inside that call. A handshake lasting beyond
the lease could therefore occur after the check and before the request bytes
were sent.

Two isolated red regressions reproduced the gap with fake connections whose
implicit handshake advanced a simulated clock beyond a 30-second lease. One
covered the initial request and one the stale-connection retry. Before this
correction, both reached the fake `request` and did not raise the expired-lease
block. `_sage_post` now explicitly completes a new connection's TLS handshake
before its final lease recheck. The same order applies to retry. Both tests
turned green, and the focused wallet suite passed **246 tests, 342 subtests**.
The full serial Windows backend passed **7,370 tests, 246 skipped, 447
subtests** in 22 minutes 9 seconds. During that run, only the older fenced
app owned connections to the operator's Sage RPC port; pytest did not connect
to it. Ruff check, format check, and `git diff --check` passed. No real Sage
RPC or wallet mutation was used in the new regressions.

This closes the identifiable lazy-handshake interval. It still cannot make a
local lease check and network delivery atomic: the host may pause after the
final check or the socket write may block. Sage-side fencing would be needed
for an absolute guarantee. This change does not explain the Veeam-associated
heartbeat stall or turn the failed original TEST 7 24-hour trace into a pass.

Exact-source CI, clean package, installer, original-profile acceptance, both
final-candidate 24-hour windows, and final review remain pending at this
checkpoint. The `b5725c3` package is historical and does not include this
correction. PR #220 stays draft.
