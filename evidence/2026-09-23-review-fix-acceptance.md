# Review-fix candidate acceptance — 23 September 2026

This is the current acceptance audit, **not release approval**. It supersedes
the `0ad637e` audit and the pre-DNS-fix package for the next acceptance run.
Branch: `codex/coin-prep-fee-approval`; verified corrections are committed locally
as `bc7203d8f1c8ce29e6bb9fab8980422c6688d0ba`, after base
`028e096a36af2624d3d01141e1e11e6ca296ca77`. This code commit is not pushed.
No main merge, release, installed replacement or new live campaign occurred.

## Frozen source and test receipts

The isolated directory is
`.superpowers/sdd/2026-09-16-coin-prep-fee-approval/candidate-review-fixes-dns-20260923`.
All 531 non-doc/evidence source, test and resource files match the worktree.
The SHA-256 of sorted `path SHA256` lines, joined by LF, is:
`ED0A9DDB1DCC702AD60B866C5FEC550E434042617497224E95BB123F31486904`.
This identifies the build snapshot, not a downloadable release. Runtime bytes
match code commit `bc7203d`; only the separately corrected smoke helpers and
their new tests differ from the pre-commit snapshot, as detailed below.

| Gate | Current evidence | Disposition |
| --- | --- | --- |
| Fee estimation, canonical consent, cumulative renewal, protected reserve, exact dispatch and recovery | 318 related tests passed in 150.43s; no manual-fee bypass added | Focused pass |
| Fragmented native prerequisites and bounded stages | Real worker/unsigned CLVM/ledger simulations cover 61/153 roots in one/two-sided plans; 44 bound/staged/worker tests passed | Focused pass; external wallet is synthetic |
| Browser fee workflow and wider UI | 156 Chromium tests passed in 108.13s; unchanged current HTML SHA-256 below | Browser pass, not native/live proof |
| Local lease ownership and startup isolation | 265 tests passed in 119.16s, including 16 hostname/preflight cases and both previously timed-out startup cases | Focused pass; no timeout extension |
| Full default backend regressions | Session 4916 exited 0: 6,981 passed, 157 skipped, 422 subtests in 1,037.25s | Passed for frozen app/source and then-collected tests; separate new helper coverage below |
| Ruff, whitespace, tracked-secret checks | Current changed/new Python files and tracked tree passed | Pass |
| Fresh Windows build | Session 58429 exited 0; Python archive contains the new local-host helper | Build pass |
| Compiled API, mock Sage, upgrade recovery and fee rejection | Current executable passed all four probes with corrected isolated harness; `*-smoke-final.log` / `*-fee-gates-final.log` | Scoped package passes, not native/live proof |
| Native window: clean/duplicate/relaunch/safety fallback | No current-candidate result | Operator check required |
| Live TEST 7 prep and full trading/recovery cycle | Earlier source receipts only; no current-candidate live result | Open, not passed |

Counts overlap and must not be added into a claimed total. See
`2026-09-23-fee-whole-feature-review.md` for the findings, red/green evidence
and all intermediate failures. Run 68774 was deliberately interrupted at
36% to fix the reproduced local-DNS dependency; it has no passing summary.

### Default-suite skip and exclusion audit

A separate default-mode audit on 23 September exited 0 with **157 skipped in
1.19 seconds**: `python -m pytest tests/e2e tests/test_linux_desktop_smoke.py
-q -rs`. Its log is `default-skip-audit-20260923.log` in the plan workspace.
The reasons account for the full default run's skipped total:

- 156 browser cases are opt-in (`--e2e`), not failed or unavailable. Their
  separate enabled Chromium run already passed all 156 in 108.13 seconds.
- One Linux desktop smoke-helper test requires POSIX-executable temporary
  files and skips on Windows. Linux execution remains unverified here;
  this is not evidence for the pending Windows native-window check.

In addition, `tests/conftest.py` excludes eight standalone integration scripts
from collection: `test_parallel_offers.py`, `test_spacescan.py`,
`test_api_data_sources.py`, `test_all_apis.py`, `test_coin_prep.py`,
`test_coin_prep_v2.py`, `test_hidden_coins.py`, and `test_offer_create.py`.
These are outside the reported totals, not eight additional passing tests.
They contain standalone diagnostics/live API or wallet operations; for example,
the old offer script directly splits coins and creates offers. They were not
executed as a substitute for the current approval-bound live acceptance workflow.
No application code, skip rule, wallet, installed package or strategy changed
during this audit.

Source and bundled UI must match:
`D70A871D6E58D24751092B80A9CE2AB40B58A63B44A6841A9CE77FF093BE2432`.
Executable SHA-256 after successful build:
`703E707F74977FEE071C93B0940FBEE665446C3620782B393A72DF229C990223`.

Two package-test harness defects were exposed by the new runs: generated
`client.crt` did not pass the actual Sage `ssl/wallet.crt` selector, and the mock
reported unsupported Sage 0.12.0. The harness also inherited real wallet-discovery
roots and public exchange DNS dependencies, while checking presence of an
authentication flag rather than its truth. Six then two focused tests failed;
the corrected helper group passed **14 tests in 3.64s**. These are test-harness
changes only; the executable/application source has not changed during full
run 4916. That run collected before the new eight harness cases existed;
their evidence is the separate 14-test run, not an inflated full-suite count.

The immutable build snapshot above retains the original helper scripts; final
package probes explicitly used the corrected worktree helpers against the same
hashed executable. This distinction avoids claiming those scripts were rebuilt
into the app. Final probes use Sage-valid synthetic TLS paths, isolated Windows
discovery roots, supported mock version and localhost-only exchange diagnostics.
They verify actual RPC authentication again after startup. No live exchange
reachability or wallet action is implied. Both earlier failed package attempts
are retained under the original and `-corrected` log suffixes; only `-final`
logs contain the final passing probes.

The final post-build byte comparison found drift only in
`scripts/packaged_api_smoke.py` and `scripts/packaged_sage_rpc_smoke.py`, plus
the subsequently added `tests/test_packaged_mock_sage_validation.py`.
Application source/resources and executable hash are unchanged. Staged-source
Ruff, whitespace and secret checks passed before committing `bc7203d`.

## Separate live and operator gates

Native-window tests use disposable data and localhost ports, not the real
wallet or installed profile. The previous `0ad637e` native command is obsolete
for current acceptance; use `2026-09-23-review-fix-native-check.md`. That handoff
was requested asynchronously; no operator result has yet been received.

Before any live action, verify actual Sage mainnet TEST 7 fingerprint
736588221, MZ wallet ID 2 and asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
An API status with a hashed fingerprint is not that full verification. Preserve
the existing strategy, reserves and historical authority data. The saved
pre-fee 45/45 strategy exceeds available MZ and must not be activated or resized
silently. A browser draft is not a confirmed Bootstrap campaign.

Remaining live receipts: actual displayed budget/campaign confirmation,
Coin Prep chain confirmation and exact fee readback, both-side offer publication,
genuine fill/requote, stop, active-load cancellation, remake and restart
accounting. Unhealthy-market RED and unavailable funding are legitimate blockers,
not passing tests or reasons to bypass safety. Historical fills cannot satisfy
a current-candidate live test. Final financial actions require operator handoff.

The earlier localhost runtime was observed read-only at about 15:25 UTC:
running, 280 loops, zero recorded loop errors and zero active offers. Its three
fills date to 15 September. That runtime was not restarted or upgraded during
these tests and does not establish current-candidate live readiness.
