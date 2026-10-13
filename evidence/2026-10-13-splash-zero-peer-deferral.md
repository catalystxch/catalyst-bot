# Splash zero-peer durable publication deferral (2026-10-13)

The primary original-profile CATalyst process accepted two live offers through
the local Splash HTTP endpoint, then logged two asynchronous
`Broadcasting Offer failed: InsufficientPeers` warnings. Its node metrics
reported zero peers and zero received offers. The durable outbox previously
completed a Splash publication when the local endpoint returned HTTP success;
that acknowledgement does not establish peer delivery. The completed claim
was not retried when peers later became available.

The candidate in draft PR #268 now injects the managed node's read-only
metrics into `SplashManager`. When the metrics endpoint is reachable and
reports zero peers, `flush_queue` leaves local queued items and durable
publication claims untouched. A later loop can submit the same exact claim
after peers appear. Dexie publication and wallet actions are unchanged.

The regression test was observed failing before the change. It proves a
durable claim stays queued and makes no local POST with zero peers, then
completes its local submission after the injected peer count becomes one.
Related local verification: 154 bot-loop tests, 155 publication/Splash runtime
tests, and 43 additional Splash/config tests passed; Ruff and `git diff --check`
passed. Full CI and package validation are pending on this candidate.

This prevents the observed zero-peer local acknowledgement loss but does not
prove delivery to an independent peer. Peers can disconnect after the metrics
sample and before daemon broadcast. The original-profile runtime is an older
binary and remains untouched; genuine two-PC Splash receipt and the final
24-hour audits remain open.
