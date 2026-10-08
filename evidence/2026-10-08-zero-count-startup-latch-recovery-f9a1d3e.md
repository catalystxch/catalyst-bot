# Proof-cleared cancellation latch and startup authorization refresh

Draft PR #220 remains unpublished. This note records an isolated secondary-PC
restart defect and the source correction at
`f9a1d3e4f7443595c44352d714d2aea3f1fef755`. It does not claim live
wallet acceptance or public readiness.

## Isolated observation

The secondary PC reproduced a cancellation restart under synthetic Sage with
the prior exact `54464960fdad711c378e521f3969593e24439717` package. The
first app process exited normally and released its mutation lease and API port.
The next app process read a tripped `UNRESOLVED_OPERATIONS` cancellation latch.
Proof-only legacy recovery then cleared that latch and found no remaining
journal blockers, but returned `recovered=0, remaining=0`. The launcher kept
its earlier denied authorization and opened read-only diagnostics on its
fallback port. Durable state already had zero blockers. There was no second
writer, wallet effect, or safety bypass. The secondary report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\exact-544-immediate-restart-investigation-20261008T1600BST\REPORT.md`,
SHA-256 `792993735E53DB5AA96AA910B70D3ECE9A90FF0B7396DBC3E7C8389DBF48DEB5`.

## Cause and correction

Both `desktop_app._initialize_startup_ownership()` and
`api_server.promote_wallet_setup_bootstrap()` refreshed
`initialize_mutation_runtime()` only if legacy recovery reported at least one
newly recovered row. That count did not include a proof-cleared latch. Both
paths now refresh the authoritative mutation gate when a completed recovery
reports either newly recovered rows or zero remaining blockers, before ending
the bounded retry. An exception or non-dictionary result keeps the earlier
denial.
If the latch remains after a zero-count recovery, the refreshed gate still
denies startup.

Two regressions were run red against the prior implementation: desktop startup
and wallet setup promotion both incorrectly returned `allowed=False` after a
zero-count, zero-remaining recovery cleared the latch. They passed green with
the correction. Each regression also covers an uncleared latch and verifies
the outcome remains denied. The affected
`tests/test_mutation_gate.py`/`tests/test_first_run_bootstrap.py` suite passed
305 tests before the negative cases were parameterized; the four final
positive/negative cases passed separately. Ruff, format, and `git diff --check`
passed.

## Exact Windows candidate

A clean detached checkout of source `f9a1d3e` at
`E:\catalyst-startup-recovery-f9a1d3e-build` produced the following unsigned
acceptance package. The frontend remains byte-identical to the preceding
`5446496` candidate, whose isolated Chromium suite passed 245 tests.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `8FD7BCA2BC8D5F996F1E3F92FE7FBCF319F5AD81C6BC9F1A2016126F1CA18804` |
| bundled `bot_gui.html` | `7001176B04758A5079D1460BBB23FCB51677BDDDD66F92AE03A56F4269AE578C` |
| acceptance ZIP | `BC71EA8DB5392BF0F34C6300EA9FBE3C970BCDD1D7FCBA2CA074F19D39C5B56C` |
| unsigned installer | `866090EC211FB49A83659B308BC535100CD9913FEAD9F528E2FF423AB1E5714A` |

The three acceptance files are pinned at artifact commit
`fa4b58858f777b373894a117af7b74bb9c3692a7`:

- [Windows acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/fa4b58858f777b373894a117af7b74bb9c3692a7/acceptance-artifacts/CATalyst-f9a1d3e-primary-acceptance.zip)
- [Unsigned Windows installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/fa4b58858f777b373894a117af7b74bb9c3692a7/acceptance-artifacts/Catalyst-Setup-f9a1d3e-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/fa4b58858f777b373894a117af7b74bb9c3692a7/acceptance-artifacts/SHA256SUMS-f9a1d3e.txt)

The ZIP contains 192 files and passes CRC checking. Its extracted EXE and UI
match the above hashes. Clean bundle and independently downloaded/extracted
bundle passed isolated packaged API and synthetic Sage mTLS smokes. Publication
recovery and native clean/duplicate/persisted/safety startup smokes passed.
The unique-AppId QA installer installed the exact EXE, passed installed API and
Sage smokes, and uninstalled cleanly without changing the production
registration. Defender custom scans of the bundle and official installer
found no new detection attributable to this package. Independently downloaded
ZIP and installer hashes matched the pinned files; the downloaded manifest
matched its committed text. The production installer remains unsigned.

A separate unique-AppId QA sequence installed exact `5446496`, upgraded in
place to exact `f9a1d3e` at the same version, rolled back to `5446496`,
restored `f9a1d3e`, and uninstalled. Every Setup and uninstall log reported
success; the installed EXE hash matched the expected candidate at each step.
An unrelated QA sentinel survived every same-version transition. Installed
exact-f9 API and synthetic Sage smokes passed after the first upgrade. This
isolated sequence did not exercise a genuine installer crash or alter an
existing production registration. Logs are under
`E:\catalyst-f9a1d3e-upgrade-qa`.

An exact-installer local beta-manifest dry run used an ephemeral Ed25519 key
held only in process memory. The signed canonical manifest and public-key
verification passed, binding `beta`, `v1.4.0`, full source commit `f9a1d3e`,
the exact unsigned installer name/size/SHA-256, and the intended release URL.
The local manifest at `E:\catalyst-f9a1d3e-beta-manifest-dryrun\manifest.json`
has SHA-256
`9AB4930A9C54205CBE498A55D9457C5501FAFB65729844C25206474A52085AA3`.
This is not a production-key signature, public source tag, GitHub release, or
website synchronization.

The complete serial local Windows backend finished **7,451 passed, 246
skipped, 455 subtests** in 21 minutes 32 seconds. Its log is
`E:\catalyst-pr220-startup-zero-recovery-full-pytest.log`, SHA-256
`28714BE4D3965C2080305963FABBDF18ED91844D07869AA67D947FA3A84C8043`.
The run collected the two initial positive regressions before the final tests
were parameterized with the two negative controls; all four final cases passed
in a separate focused run. All **11 PR checks** passed on the exact source
commit, including GitHub unit tests. The byte-identical frontend retains the
prior candidate's 245-test Chromium result.

The other PC independently matched the downloaded ZIP, installer and embedded
EXE hashes. Its isolated synthetic Sage replay of the exact former trigger
passed: the first process exited cleanly with an inactive lease and a tripped
`UNRESOLVED_OPERATIONS` latch; the immediate second process opened the normal
API with `allowed=True` only after the latch resolved, without another mock
wallet mutation. Its separate control used an inactive lease and a genuinely
nonterminal cancellation. Normal startup stayed closed, diagnostics reported
`UNRESOLVED_OPERATIONS` from the durable latch, the lease remained inactive,
and no synthetic Sage mutation RPC occurred. The secondary exact-source patch
review found no issue; its four focused cases and 307 affected tests passed.
The report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\exact-f9a1d3e-immediate-restart-20261008T1730BST\REPORT.md`.
This is isolated evidence, not secondary original-profile live acceptance.
The secondary C: drive dropped below 1 GiB during the runs, so further test
launches there stopped pending safe recovery of disk space. Its older exact-544
canary recorded a low-disk alert and cannot count toward this final source.
The secondary read-only inventory found C: at 610,938,880 bytes free, with no
suitable alternate data volume. Eleven inactive, user-owned pytest temporary
directories total 2,404,734,427 bytes; none was deleted. The active Harvestr
and synthetic canaries and their monitors remained intact. Secondary exact-f9
endurance remains paused until the machine has adequate free space.

## Primary original-profile stopped start

Immediately before rollover, a fresh read-only monitor sample of the older
`5446496` app confirmed its exact process/hash and sole port 5000 ownership,
mainnet Sage TEST 7 fingerprint `736588221`, CAT wallet ID 2 and the MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Balances were unchanged at 138470301476875 XCH mojos and 780212284 MZ
atomic units. The complete 4,095-offer Sage history had no nonterminal offer;
there were no pending transactions or DB open/unresolved offers. The bot was
stopped, no Bootstrap campaign was active, and safety was allowed with an
owned lease. The verified old native window closed normally, the process
exited, and port 5000 became free.

Exact `f9a1d3e` EXE then started on the original profile as sole PID `38104`
and port 5000 owner. Its exact-PID/hash monitor PID `153112` began at
**2026-10-08T16:38:35.606045Z**. The first sample had zero alerts, a stopped
bot, no active campaign/open offers/unresolved operations, safety allowed with
an owned lease, synced mainnet TEST 7, unchanged balances, and zero pending
or nonterminal Sage offers. The monitor script is
`E:\catalyst-stability-monitor-f9a1d3e\monitor.py`, SHA-256
`B3F09C5B61A70F56313CD1D700EA2D3D438B94B2877F03BCF9CA7C008E53A066`;
its initial trace is `trace-60s.jsonl` in that directory. The old `5446496`
monitor was stopped after preserving its clean pre-rollover samples; it is
historical evidence.

At 16:42:35Z, the initial exact-f9 monitor recorded one
`PROCESS_COUNT_NOT_ONE` alert while isolated QA installer upgrade work was
running. Port 5000 still belonged solely to original-profile PID 38104,
and the app retained its allowed safety state and owned lease. The QA logs
place the same-version upgrade between 16:42:28Z and rollback at 16:43:06Z.
That trace cannot count as a clean 24-hour window. Once QA finished and only
PID 38104 remained, the verified monitor PID 153112 was stopped. A new
exact-PID/hash monitor PID 39492 started `trace-60s-clean.jsonl` at
**2026-10-08T16:47:12.356808Z**. Its first sample had no alerts, sole
process and port ownership, an owned lease, synced TEST 7, unchanged
balances, and zero pending/nonterminal offers. This clean stopped-profile
window cannot pass before **2026-10-09T16:47:12.356808Z**, followed by
complete trace and end-state review.

No mainnet wallet action, new campaign, fee approval, or offer effect occurred.
The separate live offer lifecycle, final-candidate active-profile window,
secondary original-profile identity decision, full native UI, and final review
remain open.

This correction changes packaged runtime source, so the older exact-544
package and its current 24-hour traces remain historical evidence and cannot
count as final-candidate acceptance. Both PR #220 and website PR #89 remain
draft. No merge, tag, release, website deployment, or wallet mutation occurred.
