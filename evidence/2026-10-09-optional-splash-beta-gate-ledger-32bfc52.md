# Optional-Splash beta gate ledger — exact `32bfc52`

This ledger applies only to runtime/source
`32bfc526d37e5599bf9612a60ccfcca4c8c90902` on draft bot PR #220.
Splash remains an optional offer broadcaster. The website's draft
[PR #89](https://github.com/Lowestofttim/catalystxch/pull/89) was verified
draft at `6c706f0871111ef27fab08782ecd707b573fc84f` with optional Splash in
its title; it is not deployed.

| Gate | Exact-candidate evidence | Status |
| --- | --- | --- |
| Source and regression | Local and independent secondary focused Splash: 144 passed, four subtests each; full serial Windows backend: 7,514 passed, 259 skipped, 455 subtests; repo-wide Ruff/format and 11 PR checks passed. | Passed |
| Browser UI | Complete isolated Chromium suite: 258 passed. | Passed |
| Windows package | Clean detached EXE, ZIP and unsigned installer; package API, synthetic Sage, publication recovery, native startup/safety, ZIP CRC/extracted API, isolated installer clean/update/rollback/restore/uninstall, Defender. Pinned at artifact commit `f8c2e6227a439c248a7305e21b9a8f9bf3003236`; primary and secondary HTTP hashes passed. | Passed |
| Splash optional behavior | Outbound publication and startup failure paths covered by focused/integration tests. The managed submission bind now stays on loopback and does not terminate unowned listeners. Actual remote peer receipt of a real offer remains unverified. | Partial |
| Primary original TEST 7 profile | Still runs historical `515b41c` package with stopped bot, zero open offers. The exact `32bfc52` package has not run against it. | Open |
| Primary exact 24-hour window | Read-only exact-PID/hash monitor and auditors are prepared at `E:\catalyst-stability-monitor-32bfc52-prepared` but have not started. Its negative guard rejected historical PID 150240 before writing a trace. The running historical monitor recorded `PROCESS_COUNT_NOT_ONE` at sample 282 (2026-10-09T08:41:27Z), so it is non-clean and cannot count. The transient second process has not been attributed. | Open |
| Secondary original Harvestr profile | Exact-source static/focused tests and HTTP artifact checks passed. Fresh C: free space was 1,297,870,848 bytes, which is 960,967,250 bytes short of staging ZIP plus extraction while retaining the 2 GiB reserve. The exact package has not been staged or run there. | Open |
| Secondary exact 24-hour window | Historical exact-`196caa8` monitor completed with 755 alert-bearing samples and a 123.162-second gap; it is non-clean. No `32bfc52` window has started. | Open |
| Live wallet lifecycle/recovery | New campaign/fee scope has no specific approval. No live active-offer publish, fill, requote, cancel/restart/recovery evidence on this candidate. | Open |
| Full original-profile UI and final review | Not complete on both profiles. | Open |

Before any mainnet wallet action, recheck exact process/path/hash, Sage
network/fingerprint, wallet ID and asset, balances, pending and open offers,
safety, campaign and fee ledger. The prior campaign and its old approval do
not authorize a new campaign. The operator must perform the final UI handoff
for consequential actions.

PR #220 and website PR #89 remain draft. There is no merge, tag, release,
website deployment or public-readiness claim.
