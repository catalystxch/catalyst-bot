# Secondary-PC public-readiness acceptance — 27 September 2026

## Identity and scope

- Repository: `catalystxch/catalyst-bot`.
- Remote branch: `codex/coin-prep-fee-approval`.
- Final exact head: `4ebd9e7a369bd53f974ae421261d173396dc84fd`.
- The candidate was tested in a detached isolated worktree. The remote ref and
  `git rev-parse HEAD` matched before final-head testing and packaging.
- No CATalyst process was pointed at the live Sage profile. No wallet read,
  approval, signature, transaction, offer or fee spend was performed.

## Suite and security results

- Exact `780120565142688a37bc86f84e0baf1bfdabe618` baseline complete serial
  suite: **7,048 passed, 166 skipped, 422 subtests passed in 1,320.01s**, with
  one pre-existing pytest deprecation warning.
- After that baseline, the branch added the CodeQL hardening and confirmation
  presentation follow-ups through exact final head `54a3aeb`. The final-head
  affected security, fee-preview, fee-confirmation and complete Coin Prep
  endpoint set passed **206 tests in 66.18s**.
- The exact Bootstrap reload readiness browser regression passed **1/1 in
  3.30s**. The backend Start mutation-boundary regression passed **1/1 in
  0.95s** and logged the expected `must_resize` fail-closed decision.
- Both inline JavaScript blocks parsed successfully under Node 24.14.0.
- A complete serial suite on the exact production tree at `54a3aeb` (the only
  additional commit was this evidence Markdown) passed **7,054 tests, 166
  skipped and 422 subtests in 1,284.55s**, with the same single pytest
  deprecation warning.
- Reconciliation merge `fbe56b95e0a9cb8bbfb443cd3ece2f6c1ff86508` has parents
  `54a3aebf398b61c7952b03573c223c6f66497816` and current `main`
  `bfa25b6eac12faa4585dcf6c710ad63278431509`. Both parents are ancestors and
  its tree is byte-identical to `54a3aeb` (`git diff --quiet` exited zero).
- Formatting commit `e3123b53a2303d48ec9357d033e04aa547eb0d32`
  changed 67 Python files. An AST comparison of every changed Python file
  against `fbe56b9` found all 67 semantically equivalent. Final head
  `4ebd9e7` changes only the fee-approval plan's Python examples.
- On exact final head, repository-wide `python -m ruff check .` passed,
  `python -m ruff format --check .` reported all 530 files formatted,
  `compileall src scripts tests` passed, 24 CodeQL/readiness regressions passed
  in 1.73s, the exact reload E2E passed 1/1 in 2.89s, and
  `git diff --check` passed.

The secondary review caught a presentation regression at intermediate head
`a0c5e82`: the secure switch to `textContent` left ten callers passing HTML
markup, so safety confirmations would display literal tags. Primary fixed it
test-first at `89cf27f` by converting all callers and dynamic warning arrays to
plain text/newlines while retaining `textContent`. `54a3aeb` added
`white-space: pre-line` plus a regression assertion so the safe newlines render
as paragraphs. Primary also added explicit literal mappings for two established
recovery reason codes at `8e1015c`. The final 206-test set covers all of these
follow-ups. No further final-head CATalyst defect was reproduced.

## Exact Windows build and package

- Clean `python build.py` completed under Python 3.12.10 and PyInstaller
  6.22.3. Bundled HTML and certifi CA checks passed. The only warnings were the
  known optional `pycparser.lextab` and `pycparser.yacctab` hidden imports.
- Executable: `dist/Catalyst/Catalyst.exe`.
- Executable SHA-256:
  `5F7076A7C5EAFEB37F98D67A1296E114ED94A370835E834A85C2100260FAFE52`.
- ZIP:
  `acceptance-artifacts/4ebd9e7/CATalyst-4ebd9e7-secondary-public-readiness.zip`.
- ZIP SHA-256:
  `8E8AEEBE6715ABF81BF3010E13CB24ECA0D96C1DED6D82382E362EE58142D23F`.
- The ZIP was extracted into a new directory. Its executable hash exactly
  matched the build hash, and no `.env`, database, log, Coin Prep status,
  secrets or backup runtime artifact was present.

Against the exact executable, all package gates exited zero:

- packaged API smoke passed all nine endpoints and reported v1.4.0;
- packaged synthetic Sage mTLS worker smoke passed;
- interrupted-publication upgrade/recovery smoke passed;
- native desktop smoke passed clean launch, duplicate handoff,
  persisted-profile relaunch and native safety launch.

## Prior-package upgrade

The prior accepted package
`CATalyst-9bbf972-secondary-integration.zip` was verified at SHA-256
`0DD2CF7D0631C6F4E595314E7F0ABF6E77094B851E32E3A474D705DF4BFFDB4C`.
Its extracted executable matched the recorded SHA-256
`3210144F8DB7E6D85D13193D2B0CB5B59EF4F5089F581CD602534F20C13C8649`.

That prior package created a new isolated profile. Exact `4ebd9e7` then opened
the same profile and was relaunched once more. Both current launches reported
v1.4.0 health, preserved the migration marker and database, and remained
fail-closed with `WALLET_IDENTITY_BINDING_INVALID` because the synthetic
profile deliberately had no wallet identity. No wallet service was contacted.
Evidence is at
`outputs/4ebd9e7-upgrade-smoke/upgrade-result.json` and
`outputs/4ebd9e7-upgrade-smoke/upgrade-smoke.log`.

## Remaining public-release gates

The exact source/build/package and isolated upgrade gates pass, but this is not
authority to publish a release. The repository release checklist still leaves
these external/process gates open:

- both required 24-hour clean windows;
- PR #220 remains a draft. At the final-head check, GitHub reported the exact
  head SHA, ten successful checks, no failures, and `unit-tests` still in
  progress; mergeability was `true` but state `unstable`;
- approved merge of PR #220 to `main` and the v1.4.0 tag/workflow;
- installer version, signature/hash, clean installation and updater-path test;
- live website update and clean-Windows download verification;
- closure or supersession of older integration PRs.

Those are release-process blockers rather than defects in this exact package.
No main merge, tag, release publication, website update or installed-package
replacement was performed during this secondary acceptance.
