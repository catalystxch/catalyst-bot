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

The exact runtime/source is `eadb82aef284fd6ef4ec80f163e067d104d3ad46`.
Its clean detached Windows `Catalyst.exe` has SHA-256
`8E8EFDD7A175FE50D5BF168AF0EB4D6A4E7FB557BC8C6B68B2111C834356EF02`;
the bundled UI is byte-identical to the prior package at
`A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609`.
Packaged API, synthetic Sage mTLS, interrupted-publication recovery, and
isolated native clean/duplicate/persisted/safety smokes passed. The 192-entry
ZIP passed CRC and embedded-EXE checks; its extracted EXE passed API and
synthetic Sage smokes. A unique-AppId QA installer clean-installed to E:,
matched the EXE hash, passed installed API and Sage smokes, and silently
uninstalled without leaving its EXE or QA registry key. Defender real-time
protection was enabled and custom EXE/ZIP/installer scans found no attributable
detection.

The [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e851d452f6af8877e94a9bb7c20e08df9c9c3028/acceptance-artifacts/CATalyst-eadb82a-primary-acceptance.zip)
has SHA-256 `72C5F9C66666DA84AAB403AC955CBB01A8B06FF0396AECB5A329B667FD8B7F5B`.
The [unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e851d452f6af8877e94a9bb7c20e08df9c9c3028/acceptance-artifacts/Catalyst-Setup-eadb82a-1.4.0.exe)
has SHA-256 `567EF072A4BFE4C941F59BDF6F5D571F35051BFBC4561D26D3C4BD947DEA73EB`.
Both files and the [manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e851d452f6af8877e94a9bb7c20e08df9c9c3028/acceptance-artifacts/SHA256SUMS-eadb82a.txt)
are pinned at artifact commit `e851d452f6af8877e94a9bb7c20e08df9c9c3028`;
independent HTTP downloads matched both binary hashes. These are acceptance
artifacts, not a release.

Exact-source CI was running at this checkpoint. Original-profile acceptance,
both final-candidate 24-hour windows, and final review remain pending. The
`b5725c3` package is historical and does not include this correction. PR #220
stays draft.
