# Optional-Splash beta gate ledger — exact `6e579f4`

This ledger applies only to runtime/source
`6e579f4ec62857e6b7051ee94ec733def74a02bf` on draft bot PR #220.
Splash remains an optional offer broadcaster. Website
[PR #89](https://github.com/Lowestofttim/catalystxch/pull/89) remains draft;
no beta has been deployed.

| Gate | Exact-candidate evidence | Status |
| --- | --- | --- |
| Source and regression | HTTP 200 application rejection reproduced red/green. Primary and independent secondary nine-file focused suites each passed 262 tests and four subtests; secondary 12-case transport matrix passed. Full serial local Windows backend passed 7,516 tests, 259 skipped, 455 subtests; repository-wide Ruff and all 11 PR checks passed. | Passed |
| Browser UI | No frontend bytes changed from the preceding `32bfc52` candidate, whose complete isolated Chromium suite passed 258 tests. | Passed for unchanged UI |
| Windows package | Clean detached EXE, ZIP and unsigned installer; package API, synthetic Sage, publication recovery, native, ZIP CRC/extracted API, unique-AppId QA installer clean install, installed API/Sage, update/rollback/restore/uninstall, Defender and independent primary/secondary pinned HTTP hashes passed. Secondary verified 206 safe ZIP entries, full CRC, embedded EXE/UI hashes, and the separate pinned manifest. Artifacts pinned at `0cc901931342798eef67f2876b58b2a20a249014`. | Passed |
| Splash local semantics | Only exact JSON boolean `success: true` acknowledges the local Splash submission. Exact `success: false` is retryable no-effect; malformed response is unresolved. | Passed in isolated tests |
| Splash remote peer receipt | No separate peer has received a byte-identical signed offer from this candidate. Local HTTP acknowledgement alone does not prove peer delivery. | Open |
| Primary original TEST 7 profile | Historical `515b41c` app remains the observed stopped-profile owner; exact `6e579f4` has not run there. | Open |
| Primary exact 24-hour window | Historical monitor recorded `PROCESS_COUNT_NOT_ONE` at sample 282; it cannot count for this source. No exact `6e579f4` window started. | Open |
| Secondary original Harvestr profile | Exact-source focused tests passed in an isolated worktree. Exact package and original-profile live acceptance remain open. A prior 24-hour monitor completed with 755 alert-bearing samples and a 123.162-second gap. | Open |
| Live wallet lifecycle/recovery | No new campaign/fee scope has specific approval. No exact-candidate active-offer publish, fill, requote, cancellation or restart/recovery evidence. | Open |
| Full original-profile UI and final review | Neither profile has completed all required exact-candidate native acceptance. | Open |

Before any mainnet wallet action, recheck exact process path/hash, Sage
network/fingerprint, wallet ID and asset, balances, pending and open offers,
safety, campaign and fee ledger. The stopped prior campaign and old approval
do not authorize a new campaign. Consequential actions require the final
operator UI handoff. No merge, tag, release, website deployment, or
public-readiness claim has occurred.
