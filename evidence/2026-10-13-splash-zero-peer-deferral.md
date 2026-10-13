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
samples leave local queued items and durable publication claims untouched. A
later loop can submit the same exact claim after fresh positive-peer evidence
appears. Dexie publication and wallet actions are unchanged.

The regression test was observed failing before the change. It proves a
durable claim stays queued and makes no local POST with missing metrics, a
provider error, unreachable metrics, zero peers, a stale positive sample, a
sample from an older process generation or a stopped process. It then
completes local submission after a fresh positive sample. An independent
review identified the initial fail-open metrics gap; the expanded regression
test failed before that correction and passed afterward. A separate runtime
test checks the metrics snapshot's process identity metadata. Related local
verification: 352 tests and four subtests passed together, the new snapshot
test passed, and Ruff plus `git diff --check` passed. Full CI and final package
validation are pending on this corrected candidate.

This prevents the observed zero-peer local acknowledgement loss but does not
prove delivery to an independent peer. Peers can disconnect after the metrics
sample and before daemon broadcast. The original-profile runtime is an older
binary and remains untouched; genuine two-PC Splash receipt and the final
24-hour audits remain open.
