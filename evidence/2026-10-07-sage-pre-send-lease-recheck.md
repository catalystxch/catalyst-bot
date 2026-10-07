# Sage RPC pre-send lease recheck

## Finding and correction

The wallet adapter checked a mutation's identity and lease before calling
`_sage_post`, but `_get_sage_connection()` could take longer than the remaining
lease. After it returned, the adapter sent the RPC without checking again. A
stale connection could likewise fail, spend time reconnecting, and then retry
the send after the lease had expired. Direct cancel, sign, submit, bulk cancel,
and delete paths also called `_sage_post` without forwarding their recheck.

`_sage_post` now invokes the supplied recheck immediately before its first
`conn.request` and immediately before a transport retry. `MutationBlocked`
propagates through `_sage_post`, `rpc`, sign/submit and delete paths instead of
becoming a connection failure or a normal false result. The direct mutating
paths forward their existing callback to that final boundary.

Isolated red/green regressions used fake Sage connections and a simulated
clock advancing beyond a 30-second lease during connection setup or retry.
Before the correction, they reached the fake `request`; afterward, the
expired-lease block propagated and no request was sent. Separate cases cover
ordinary `rpc`, retry, direct cancel, direct signing, direct submission, bulk
cancel construction, and delete. No real Sage RPC or wallet mutation is used.

## Verification and limits

The focused wallet adapter suite passed 244 tests and 342 subtests. The full
serial Windows backend passed **7,368 tests, 246 skipped, 447 subtests** in
21 minutes 4 seconds. During the run, only the older original-profile app
owned connections to the operator's Sage RPC port; the pytest process did
not connect to it. Ruff check, format check, and `git diff --check` passed.
Exact-source CI, clean package, installer, original-profile acceptance, and
final review remain pending at this checkpoint.

This narrows the interval between lease validation and an outbound Sage
request. It does not make host scheduling and Sage delivery atomic: a pause
after the final check and before or during the OS send remains possible without
Sage-side lease enforcement. It also does not identify the instruction that
stalled during the earlier Veeam snapshot. The older original TEST 7 process
remains in terminal read-only `HEARTBEAT_FAILED`; no live wallet effect is
authorized by this evidence. PR #220 stays draft.
