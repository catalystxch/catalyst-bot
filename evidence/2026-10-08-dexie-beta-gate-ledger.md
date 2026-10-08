# v1.4 Dexie-only beta gate ledger — 2026-10-08 13:19 UTC

This ledger supplements `docs/testing/v1.4.0-release-acceptance.md`. It records the exact candidate and the evidence still needed before a public beta decision. A green check from another commit or an elapsed clock does not close an exact-candidate gate.

| Gate | Current evidence | State |
| --- | --- | --- |
| Source and PR | Runtime `8cd81e4213c884b694d4e880e0f179cbcf3448bc`; test-only child `cd726e45d0e3f0e9914cb120437fd9d5df93358a`; docs-only PR head `a84a3713a3f08945aa773df71e8fe967b878cd0c`. PR #220 remains draft; 11/11 checks green. | Verified for this candidate |
| Windows package | Clean detached EXE SHA-256 `142BC2014765AE5E4F54B3E51B91FD4679109EB4D9376529C24490FDBD30C781`; ZIP and unsigned installer pinned at artifact commit `c5964c8d3eb40a4e22d5c4c8042b605cc852261a`. Primary package, ZIP, installer, Defender, independent HTTP hashes and secondary extracted-package probes passed. | Verified for this candidate |
| Automated tests | Complete serial Windows backend 7,448 passed, 246 skipped, 455 subtests; Chromium 245 passed. | Verified for this candidate |
| Primary original-profile startup | Sole exact EXE PID 149044, port 5000 owner, Sage mainnet TEST 7 fingerprint 736588221, CAT wallet 2, exact MZ asset, unchanged balances, zero pending/open offers, stopped bot and allowed safety at start. See `evidence/2026-10-08-primary-8cd81e4-live-readonly-start-and-monitor.md`. | Read-only start verified |
| Primary stopped-profile 24-hour window | Exact-PID/hash monitor PID 129684 began `2026-10-08T12:58:12Z` in `E:\catalyst-stability-monitor-8cd81e4-clean\trace-60s.jsonl`. Complete trace and end-state audit cannot be credited before `2026-10-09T12:58:12Z`. | In progress |
| Secondary original-profile acceptance | Secondary independently verified exact package and security probes. Its historical exact-196 Harvestr stopped-profile window continues to its own endpoint; it is not an exact-8cd pass. Exact-8cd original-profile rollover and full independent acceptance remain open. | Open |
| Live wallet lifecycle and recovery | Exact-8cd offer creation, publication, requote, cancel, remake, Coin Prep, restart/recovery, fee ledger, Sage/Dexie reconciliation and active 24-hour window have not been run. The prior campaign is stopped; old fee approval is invalid. Specific new campaign/fee scope and final action-time UI handoff are still required. | Open |
| Original-profile native UI | Prior candidates had inactive UI traversal. Full exact-8cd original-profile native UI and active-state checks remain open. The user interrupted a prior mouse traversal; no new original-profile mouse operation has been attempted. | Open |
| Security and final review | A sealed PR security diff review covered its earlier immutable worklist through `1a1aeaa` with no reportable findings. Secondary is independently reviewing the later bot/security delta and website draft. Final candidate review remains open. | Open |
| Website beta | Dexie-only unsigned beta website PR #89 at `fe6d7151b37a9b92a18fe18dc7ae6f413ca7942d` is draft and its validator passed. The beta release, tag, download metadata switch, website merge/deploy and public-readiness claim are withheld. | Staged, not published |

At this checkpoint there is no authorization to treat the remaining live or stability gates as passed. Keep PR #220 and website PR #89 draft until their evidence and final review are complete.
