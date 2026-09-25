# Combined secondary-PC fixes: verification checkpoint

Started: 24 September 2026, 18:08 UTC.

Later runtime note: `2026-09-25-combined-runtime-reopened.md` records the exact
combined executable reopened with intact TEST 7 fee accounting. It supersedes
the runtime-unavailable observation below, not the remaining live-cycle gate.

## Scope and provenance

- Feature branch: `codex/coin-prep-fee-approval`; frozen source `088d9d6`.
- Includes reviewed CAT spare/live-tier sizing and verified-owner desktop
  handoff fixes. Source review and focused results are recorded in
  `2026-09-24-primary-review-secondary-fixes.md`.
- New isolated archive: `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/candidate-088d9d6-combined-20260924.zip`.
- Archive SHA-256:
  `AA43817C87A31D1D44DD431B049660A9606D6BE86EE1B8FE20D40E3D4CB0DC69`.
- Build and tests use the extracted tracked-source archive, not a changing
  checkout. Existing live and earlier candidate packages are untouched.

## Verification results

- Frozen-source full default suite: `C:\Python312\python.exe -m pytest tests -q`;
  session `68347` exited **0**: **6,993 passed, 157 skipped, 422 subtests passed
  in 1006.55s**. Log: `candidate-088d9d6-combined-full.log`. Skips retain the
  earlier classification: 156 opt-in browser tests (separately passed) and
  one POSIX-only helper. Standalone live scripts remain excluded, not passed.
- The corrected probe harness and six new regression cases were added after
  frozen-source collection. The fresh whole-worktree suite completed with
  **6,999 passed, 157 skipped, 422 subtests passed in 1039.94s**, exit code 0.
  Log: `combined-helper-final-full.log`.
- Fresh isolated Windows build: `C:\Python312\python.exe build.py --no-clean`;
  session `1148` exited **0**, log `candidate-088d9d6-combined-build.log`.
  Python 3.12.6, PyInstaller 6.21.0; the existing
  `importlib_resources.trees` hidden-import warning remains recorded.
- Executable: `candidate-088d9d6-combined-20260924/dist/Catalyst/Catalyst.exe`;
  SHA-256 `02F090A74B6E7FA16954B3F5AEAEB3849DE63A67B84F0F3CE6B9B684B1F2A845`.
- Source and bundled `bot_gui.html` SHA-256 both
  `D70A871D6E58D24751092B80A9CE2AB40B58A63B44A6841A9CE77FF093BE2432`.
  PyInstaller TOCs point to this snapshot's desktop, worker and prep route.
- The 198-file bundle manifest is
  `candidate-088d9d6-combined-bundle-manifest.csv`, SHA-256
  `A47B164F71AAEFC8098F8D4033FBB722505C5923B16DA3D840700367C8DD1CFB`.
- Opt-in Chromium suite: **156 passed in 75.47s**, session `15009` exited 0;
  log `candidate-088d9d6-combined-browser.log`.
- Packaged API smoke: **passed**, eight endpoints plus post-startup mock
  authentication; log `candidate-088d9d6-combined-api.log`.
- Packaged mock-Sage RPC worker smoke: **passed**;
  log `candidate-088d9d6-combined-sage.log`.
- Packaged interrupted-publication upgrade/recovery smoke: **passed**;
  log `candidate-088d9d6-combined-recovery.log`.
- Exact combined executable native desktop smoke on the primary PC: **passed**
  clean-profile launch, duplicate verified-owner handoff, persisted-profile
  relaunch and native safety launch. The executable SHA-256 was rechecked as
  `02F090A74B6E7FA16954B3F5AEAEB3849DE63A67B84F0F3CE6B9B684B1F2A845`
  immediately before the smoke run.
- Ruff on the six changed production/test files and `git diff --check` passed.

## Result reconciliation at the 20:25 UTC heartbeat

- Read the completed `combined-helper-final-full.log`: its terminal summary is
  **6,999 passed, 157 skipped, 422 subtests passed in 1039.94s**. The former
  session `97189` is retired, not still running. Commit `eaca304` records the
  exit-zero result and the same-executable native acceptance receipt above.
- Recomputed the executable and manifest SHA-256 values: both match the
  recorded values above. Independently checked all **198 manifest entries**
  against the current bundle's file sizes and SHA-256 values: zero mismatches
  or missing files. No production source changed after the frozen snapshot;
  subsequent code changes concern only the isolated probe helper and its tests.
- Native acceptance is a recorded receipt from `eaca304`; this heartbeat did
  not rerun native launches. The separate older operator receipt for executable
  `703E707F...` is not used to certify this executable. No repeat native smoke
  is required for this unchanged bundle.
- A fresh read-only status request still received connection refusal at
  `127.0.0.1:5000`, and process inventory found no Catalyst process. One Sage
  process remains (`sage-tauri.exe`, PID `60824`). This does not establish
  live wallet identity or current market authority, and is not a crash finding.
- No verification job remains active. Live offer creation/publication,
  requoting, active cancellation and remake remain unverified. Resume those
  observations only after the candidate is reopened, with fresh identity and
  market evidence and the existing action/budget safeguards. The goal remains
  blocked, not complete; the automation is not paused or deleted.

## Package probe failure and test-first isolation correction

- The first extended fee-gate probe (session `14320`, exit 1) timed out at
  `/api/doctor?force=true` after the preceding seven API checks passed. Its
  normal 25-second Doctor deadline was not increased. Fee endpoints were not
  reached in that attempt. Preserve `candidate-088d9d6-combined-fee-gates.log`.
- Inspected Doctor's sequential checks and the actual isolated mock harness.
  Added timing-only instrumentation to the scratch probe, not production code.
- Instrumented immediate retry passed: Doctor **0.515s**, all three fee
  denial paths rejected invalid/unapproved input with false dispatch authority,
  and the mock RPC allowlist saw no wallet-effect request. Log:
  `candidate-088d9d6-combined-fee-gates-diagnostic.log`.
- A second diagnostic run delayed only the start of Doctor by five seconds
  to test whether async startup settling reproduced the problem. It also
  passed, Doctor **0.500s**, with unchanged request deadlines and the same
  fee-denial and RPC assertions. Log:
  `candidate-088d9d6-combined-fee-gates-delayed.log`.
- At that initial stage the helpers used by the scratch probe were byte-identical
  to the frozen snapshot helpers (API SHA-256 `FA32E694341435551182801EF7CFB9B9155FD4E8185F6EAC984F501D45C44261`,
  Sage SHA-256 `04DFF3FB387B79A3D8DF9930601E14317550D63F537597191252F0154792DADA`).
- A repeat reproduced the 25.016-second Doctor timeout after mock sync/key
  RPCs (`candidate-088d9d6-combined-fee-gates-repeat-1.log`). The bounded repeat
  group stopped at that first failure; later repeat numbers were not run.
- Added runtime configuration readback showed `DEXIE_API_BASE` had actually
  reverted to `https://api.dexie.space`. Thus even passing initial probes
  depended on uncontrolled public-network access. The shipped default `.env`
  overrides process values; the process-preservation allowlist covers wallet
  keys, not Dexie. This is a confirmed probe-isolation defect, not evidence
  of a fee-budget or wallet-effect failure.
- Two failing regressions preceded persisting only allowlisted synthetic
  settings into the disposable profile. The real Config reload now retains
  loopback and mock identity; host secrets are not copied into the profile.
- Four further failing cases preceded runtime `/api/config` validation before
  Doctor. The probe now refuses wrong Dexie URLs and non-false Splash states
  before doing those diagnostics, rather than masking the problem with longer
  deadlines. Final helper selection: **20 passed in 2.62s**; log
  `combined-probe-isolation-final-green.log`. RED logs are retained as
  `combined-probe-isolation-red.log` and `combined-probe-readback-red.log`.
- Corrected immediate and three delayed-start package probes all passed with
  actual loopback readback and Doctor around 2.1s. Final normal probe passed
  nine API endpoints, all three fee-denial checks, post-startup authentication
  and no wallet-effect RPC assertion; log
  `candidate-088d9d6-combined-fee-gates-final.log`.
- Corrected upgrade/recovery helper also passed against the unchanged EXE;
  log `candidate-088d9d6-combined-recovery-isolated.log`.
- Final API helper SHA-256 is
  `D2D02D07BE950C58F9D147A45B0D31235AF6DA49412A03C25C385F7455076D05`.
  It lives in the worktree, not the earlier frozen snapshot. All corrected
  package probes explicitly use that helper against the same unchanged EXE.
  No production runtime setting, deadline or market gate was changed.
- The public-network dependency causing this unreliable probe is removed and
  guarded. This does not claim that live provider latency is fixed or that
  public exchange reachability was tested by the corrected isolated probe.

## Acceptance boundaries and monitoring correction

- Secondary-PC live Coin Prep evidence uses fingerprint `3702373391`, not
  this task's required TEST 7 fingerprint `736588221`. Keep their approvals,
  balances, fee receipts and acceptance provenance separate.
- Earlier live receipts remain evidence for their exact source and executable;
  they do not automatically certify new wallet effects. The new combined
  executable's native launch gate is now independently verified above.
- CATalyst localhost:5000 was connection-refused at this heartbeat. A broader
  process inventory found two `sage-tauri.exe` processes (PIDs 60824 and
  72516), created at 10:15 BST. The earlier exact-name `sage` check missed
  these; statements that Sage was closed are withdrawn. Process presence
  does not establish wallet connectivity, network or selected identity.
- No live app launch, wallet action, fee approval, strategy change, offer
  publication, main merge or release occurred in this verification pass.
- Live create/publication/requote/cancel/remake acceptance is still open.
  Recorded RED market evidence was the last live gate; app unavailability
  prevents a current assessment. No safety threshold is changed.
