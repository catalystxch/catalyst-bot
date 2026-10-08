# Dexie-only beta gate ledger — exact `f9a1d3e`

This ledger supersedes the [exact-544 checkpoint](2026-10-08-dexie-beta-gate-ledger.md)
after a packaged-runtime startup recovery correction. A prior package, monitor
window, or green check does not establish acceptance for this source.

| Gate | Evidence at 2026-10-08 16:38 UTC | State |
| --- | --- | --- |
| Source and PR | Runtime/source `f9a1d3e4f7443595c44352d714d2aea3f1fef755` on draft [bot PR #220](https://github.com/catalystxch/catalyst-bot/pull/220), targeting `main`. All 11 exact-source checks passed. | Source CI passed; PR draft |
| Backend and UI tests | Serial Windows backend 7,451 passed/246 skipped/455 subtests; final four zero-count latch positive/negative regressions passed separately because the negative cases were added after full collection. GitHub exact-commit unit tests passed. Bundled UI bytes equal the prior source whose isolated Chromium suite passed 245 tests. | Tested; no new frontend code |
| Windows package | Clean detached EXE `8FD7BCA2BC8D5F996F1E3F92FE7FBCF319F5AD81C6BC9F1A2016126F1CA18804`, ZIP `BC71EA8DB5392BF0F34C6300EA9FBE3C970BCDD1D7FCBA2CA074F19D39C5B56C`, unsigned installer `866090EC211FB49A83659B308BC535100CD9913FEAD9F528E2FF423AB1E5714A`; pinned at artifact commit `fa4b58858f777b373894a117af7b74bb9c3692a7`. Bundle/API/Sage/recovery/native, ZIP CRC/extracted API/Sage, unique-AppId QA installer install/API/Sage/uninstall, Defender and independent HTTP hashes passed. | Candidate package verified; tagged release build open |
| Independent restart | Secondary independently matched exact ZIP/installer/EXE hashes. Its isolated synthetic replay of the former `recovered=0, remaining=0` cancellation-latch failure reached allowed normal startup after latch resolution with no duplicate mutation. The distinct genuinely unresolved cancellation control stayed diagnostics-only with inactive lease and zero mock Sage mutation RPCs. Four focused and 307 affected tests passed; patch review found no issue. | Positive and fail-closed controls passed in isolation |
| Incremental security review | Sealed Codex Security diff scan `0cb61faa-3d74-4501-ac75-915dfea0364f` reviewed all 10 changed source/workflow files from the prior reviewed baseline `1a1aeaaca6d54d035ff56cbe1db4f5bd532df40a` through exact runtime `f9a1d3e4f7443595c44352d714d2aea3f1fef755`, including API/bridge boundaries, startup mutation gates, updater and beta release provenance. It recorded complete changed-source coverage and zero reportable findings. The read-only source review did not exercise a live wallet. The sealed local report is under `C:\Users\t_you\.codex\state\plugins\codex-security\scans\catalyst-pr220-alias-integration\f9a1d3e4f7443595c44352d714d2aea3f1fef755_20261008T183700Z_pb39zecs\report.md`. | Source diff review passed; live gates independent |
| Primary original TEST 7 stopped profile | Verified old process exited normally with zero offers/pending and unchanged balances. Exact `f9a1d3e` app became sole PID 38104/port 5000 owner; its first monitor sample at `2026-10-08T16:38:35.606045Z` had synced mainnet TEST 7, fingerprint 736588221, CAT wallet 2, exact MZ asset, stopped bot, zero offers/pending, unchanged balances, and safety allowed with owned lease. | Initial read-only start passed |
| Primary stopped-profile 24 hours | Initial exact-f9 trace had one process-count alert during isolated QA installer upgrade, so it is historical. Clean exact-PID/hash monitor PID 39492 writes `E:\catalyst-stability-monitor-f9a1d3e\trace-60s-clean.jsonl` every 60 seconds, starting **2026-10-08T16:47:12.356808Z**. The 24-hour threshold is **2026-10-09T16:47:12.356808Z**. The monitor is configured for 25 hours, so its terminal record is expected no earlier than approximately **2026-10-09T17:47:12Z**; the gate also requires complete trace and end-state audit. | In progress |
| Secondary 24 hours and live identity | Secondary exact-544 synthetic canary is historical. On 2026-10-08 the secondary operator removed 11 verified disposable pytest temp directories and independently rechecked C: at 2,527,465,472 bytes free after exact-f9 setup. The exact-f9 ZIP and extracted EXE matched the pinned hashes above. An isolated, stopped-profile synthetic Sage monitor began at **2026-10-08T17:21:01.793739Z** with app PID 16960 on port 50324 and monitor PID 21376. Its first sample had the exact EXE hash, owned renewing lease, safety allowed, zero offers/operations/fee reservations/publications, and zero mutating synthetic Sage RPC paths. The exact 24-hour threshold is **2026-10-09T17:21:01.793739Z**; its terminal record and `summary.json` are written only after the final snapshot and shutdown. A complete trace and end-state audit must follow. Secondary evidence is `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\monitor-f9a1d3e-synthetic-20261008T1820BST`. Original Sage has Harvestr fingerprint 3702373391, not required TEST 7 fingerprint 736588221; no Harvestr wallet action is authorized. | Exact-f9 isolated secondary stopped-profile window in progress; original-profile TEST 7 identity and live acceptance open |
| Live wallet lifecycle | No new TEST 7 campaign or valid fee approval. A specific 24-hour campaign/fee question remains unanswered. No exact-f9 mainnet offer create/requote/fill/cancel/recovery, Coin Prep, fee-ledger or active 24-hour window has run. The older `c665` fee approval is invalid. | Open; no wallet effect authorized by this ledger |
| Native UI and final review | Earlier isolated packaged UI traversal and Chromium checks passed. Full exact-f9 original-profile native UI and active-state checks, final release review, signed/tagged beta manifest and website synchronization remain open. | Open |
| Website | Draft [website PR #89](https://github.com/Lowestofttim/catalystxch/pull/89) at `8c214258eb2b76fb159b4931fe42dac17f316f9e` targets `main`, is mergeable, and its validator passed. It retains the older v1.3.21 public download until the exact beta is approved and published. | Staged, not deployed |

At `2026-10-08T18:15Z`, the secondary PC preserved an
`unexpected_catalyst_process_count` alert in its **older exact-196** Harvestr
monitor. That historical window is not a clean 24-hour pass. The alert arose
when the isolated exact-f9 synthetic app ran alongside the stopped exact-196
app. A read-only audit of the exact-f9 monitor confirmed that it checks its
own executable path, PID and port owner rather than a global process count:
55 exact-f9 samples had zero alerts, path/PID/port drift or mutating Sage RPCs.
This is interim evidence only; the exact-f9 window still requires its complete
24-hour trace and end-state review. The secondary C: drive had 2,939,863,040
bytes free at that audit.

The [exact correction and package evidence](2026-10-08-zero-count-startup-latch-recovery-f9a1d3e.md)
records the red/green regression, pinned package links, independent download
hashes, QA installer, and original-profile rollover. Keep both PRs draft until
the open gates are reviewed; no merge, tag, release, website deployment or
public-readiness claim has occurred.
