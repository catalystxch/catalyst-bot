# Secondary-PC public-readiness acceptance — 27 September 2026

## Identity and scope

- Repository: `catalystxch/catalyst-bot`.
- Remote branch: `codex/coin-prep-fee-approval`.
- Final exact head: `54a3aebf398b61c7952b03573c223c6f66497816`.
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
- Repository-wide `python -m ruff check .`: passed. Ruff check and format-check
  on both changed Python blueprints passed. `git diff --check` passed.

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
  `C533379A74592C08174C3F03E2D128036D049099DDFA48A474F094D302B43755`.
- ZIP:
  `acceptance-artifacts/54a3aeb/CATalyst-54a3aeb-secondary-public-readiness.zip`.
- ZIP SHA-256:
  `1F5BE9EFB0154C702076B78386C78DD1AC5F198BAE558DF415670116EAF29C71`.
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

That prior package created a new isolated profile. Exact `54a3aeb` then opened
the same profile and was relaunched once more. Both current launches reported
v1.4.0 health, preserved the migration marker and database, and remained
fail-closed with `WALLET_IDENTITY_BINDING_INVALID` because the synthetic
profile deliberately had no wallet identity. No wallet service was contacted.
Evidence is at
`outputs/54a3aeb-upgrade-smoke/upgrade-result.json` and
`outputs/54a3aeb-upgrade-smoke/upgrade-smoke.log`.

## Remaining public-release gates

The exact source/build/package and isolated upgrade gates pass, but this is not
authority to publish a release. The repository release checklist still leaves
these external/process gates open:

- both required 24-hour clean windows;
- merge of PR #214 to `main` and the approved v1.4.0 tag/workflow;
- installer version, signature/hash, clean installation and updater-path test;
- live website update and clean-Windows download verification;
- closure or supersession of older integration PRs.

Those are release-process blockers rather than defects in this exact package.
No main merge, tag, release publication, website update or installed-package
replacement was performed during this secondary acceptance.
