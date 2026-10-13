# Splash zero-peer durable publication deferral (2026-10-13)

The primary original-profile CATalyst process accepted two live offers through
the local Splash HTTP endpoint, then logged two asynchronous
`Broadcasting Offer failed: InsufficientPeers` warnings. Its node metrics
reported zero peers and zero received offers. The durable outbox previously
completed a Splash publication when the local endpoint returned HTTP success;
that acknowledgement does not establish peer delivery. The completed claim
was not retried when peers later became available.

The candidate in draft PR #268 now injects the managed node's read-only
metrics into `SplashManager`. `flush_queue` requires a running managed process,
reachable metrics, a positive peer count and a sample no older than 15 seconds
that was taken after this process started. Missing, failed, stale or zero-peer
samples leave local queued items and durable publication claims untouched. The
durable flush checks the sample again before each claim and immediately before
each external POST. If the sample goes stale after a dispatch is marked, the
claim is atomically deferred to retryable before transport, clearing the
dispatch marker and request digest. A later loop can submit the same exact
claim after fresh positive-peer evidence appears. Dexie publication and wallet
actions are unchanged.

The regression test was observed failing before the change. It proves a
durable claim stays queued and makes no local POST with missing metrics, a
provider error, unreachable metrics, zero peers, a stale positive sample, a
sample from an older process generation or a stopped process. It then
completes local submission after a fresh positive sample. An independent
review identified the initial fail-open metrics gap; the expanded regression
test failed before that correction and passed afterward. Two further real-DB
regressions failed before their corrections and passed afterward: a batch
loses fresh peer evidence after its first POST, and a marked dispatch loses
fresh evidence before transport. A separate runtime test checks the metrics
snapshot's process identity metadata. On exact source
`b2d75331fa929e6c716f21b9a0acc4cac1640b4d`, 114 publication tests and
338 related Splash, bot, and UI tests passed, with four subtests. Ruff format,
Ruff check, and `git diff --check` passed. An independent reviewer found no
Critical or Important regression in this final refinement.

The clean Windows package built from that exact source. Its EXE SHA-256 is
`61D5B7CE7926E6587785D2718001E6258EC7EF44F31402EF6A14C75C35903944`.
Isolated packaged API, mock Sage RPC, native clean/duplicate/persisted/safety
launches, and interrupted-publication upgrade recovery all passed. Exact-head
CI was still completing at the time of this evidence update.

This prevents the observed zero-peer local acknowledgement loss but does not
prove delivery to an independent peer. Peers can disconnect after the metrics
sample and before daemon broadcast. The original-profile runtime is an older
binary and remains untouched; genuine two-PC Splash receipt and the final
24-hour audits remain open.
