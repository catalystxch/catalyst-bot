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
The exact source is `b5725c38009041bdf22803dca7e30df048de31a9`.
A clean detached Windows build produced `Catalyst.exe` SHA-256
`52069C0B1BB243CEFD30318335807CD7AD484766EFACD60FA8DFC4A51A42E7AD`;
the bundled `bot_gui.html` is byte-identical to the prior package at
`A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609`.
Packaged API, synthetic Sage mTLS worker, interrupted-publication recovery,
and isolated native clean/duplicate/persisted/safety smokes passed. The
192-entry ZIP passed CRC and embedded-EXE hash checks; its extracted EXE
passed API and synthetic Sage smokes. A unique-AppId QA installer
clean-installed to E:, its EXE hash matched, installed API and synthetic Sage
smokes passed, and silent uninstall removed its EXE and QA registry key.
Defender real-time protection was enabled and custom EXE/ZIP/installer scans
found no attributable detection.

The [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d23d9d3db3c642ba48d422687930a21fab7f3502/acceptance-artifacts/CATalyst-b5725c3-primary-acceptance.zip)
has SHA-256 `09EF019F3EF0822E6B6205C0013C05FEC2B7E483F0C7D825DF4D8F1A22AA90AB`.
The [unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d23d9d3db3c642ba48d422687930a21fab7f3502/acceptance-artifacts/Catalyst-Setup-b5725c3-1.4.0.exe)
has SHA-256 `69B9C9374399BA1E434ED9637B568B674F12A065FED45799A5B0BBDA71BF79D1`.
Both files and the [manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d23d9d3db3c642ba48d422687930a21fab7f3502/acceptance-artifacts/SHA256SUMS-b5725c3.txt)
are pinned at artifact commit `d23d9d3db3c642ba48d422687930a21fab7f3502`;
independent HTTP downloads matched their hashes. These are acceptance
artifacts, not a release. Exact-source CI unit tests were still running at
this checkpoint. Original-profile acceptance and final review remain open.

This narrows the interval between lease validation and an outbound Sage
request. It does not make host scheduling and Sage delivery atomic: a pause
after the final check and before or during the OS send remains possible without
Sage-side lease enforcement. It also does not identify the instruction that
stalled during the earlier Veeam snapshot. The older original TEST 7 process
remains in terminal read-only `HEARTBEAT_FAILED`; no live wallet effect is
authorized by this evidence. PR #220 stays draft.
