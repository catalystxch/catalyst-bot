# Unsigned Windows Stable Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a protected, manually dispatched unsigned Windows stable release path without weakening the existing beta or signed paths.

**Architecture:** Reuse the proven exact-tag beta build sequence in a dedicated stable workflow. Keep Ed25519 update-manifest signing, SHA-256, Defender, packaged smokes, and staged publication. Make the existing SignPath workflow manual so unsigned stable tags do not trigger an expected failed signed build.

**Tech Stack:** GitHub Actions YAML, PowerShell, Python 3.12, PyInstaller, Inno Setup, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-unsigned-windows-stable-release-design.md`

## Global Constraints

- Build only from an exact `vMAJOR.MINOR.PATCH` commit on protected main and a matching public non-draft, non-prerelease source release.
- Stable release-channel tags are immutable; never replace an existing tag or use `--clobber`.
- Installer and installed app must be `NotSigned`; no publisher or Authenticode evidence claim.
- Preserve exact SHA-256 sidecar, Defender scans, four packaged smoke gates, and Ed25519-signed `stable` update manifest.
- Publish as latest non-prerelease only after all gates; no unsigned fallback inside the signed workflow.
- Keep the beta prerelease workflow and assets unchanged; do not dispatch public publication before live acceptance and final review.

## Review Focus

- A version tag whose commit is absent from protected main must fail before build (Task 2 test).
- A source release marked prerelease or draft must fail before build (Task 2 test).
- A signed installer or payload must fail the unsigned path (Task 2 test).
- A changed installer after sidecar or manifest generation must fail before publication (Task 2 test).
- A pre-existing release-channel tag must fail without changing assets (Task 2 test).

---

### Task 1: Keep signed releases opt-in

**Files:** Modify `.github/workflows/build-release.yml`; modify `tests/test_unsigned_windows_beta_release.py`, `tests/test_windows_release_signing.py`, and any cross-platform workflow tests that assert tag triggering.

**Interfaces:** Signed workflow consumes a manual `tag` input and produces the same verified signed artifacts as before; it does not own unsigned stable publication.

- [ ] **Step 1: Write failing workflow tests.** Assert `build-release.yml` has `workflow_dispatch.inputs.tag`, no version-tag `push` trigger, and validates an exact protected-main tag before any SignPath request. Assert its existing ability to create the source release, signature checks, smoke checks, checksum, and publication order remain intact.
- [ ] **Step 2: Run red tests.** `python -m pytest tests/test_unsigned_windows_beta_release.py tests/test_windows_release_signing.py tests/test_cross_platform_release_packaging.py tests/test_linux_desktop_release.py -q`; expect the new manual-trigger assertion to fail.
- [ ] **Step 3: Implement.** Replace the tag trigger with manual dispatch, resolve `inputs.tag` explicitly in every job, and fail on invalid tag or missing protected-main ancestry. Keep SignPath preflight, artifact verification, and its source-release creation intact; preserve the independent Linux release workflow.
- [ ] **Step 4: Run green tests.** Repeat Step 2 and run `python -m pytest tests/test_ci_security_workflows.py tests/test_app_update.py -q`.
- [ ] **Step 5: Commit.** `git add .github/workflows/build-release.yml tests && git commit -m "ci: dispatch signed Windows releases explicitly"`.

### Task 2: Publish exact-tag unsigned stable Windows assets

**Files:** Create `.github/workflows/publish-unsigned-windows-stable.yml` and `tests/test_unsigned_windows_stable_release.py`; modify `docs/CODE_SIGNING_POLICY.md`.

**Interfaces:** Consumes `inputs.tag`, protected-main source release, `CATALYST_UPDATE_SIGNING_KEY_B64`, and `CATALYST_RELEASE_CHANNEL_TOKEN`; produces `Catalyst-Setup-vX.Y.Z.exe`, matching `.sha256`, `latest.json` with `channel: stable`, `latest.json.sig`, and versioned manifest copies in an immutable latest release. No `windows-signature-vX.Y.Z.json` is emitted.

- [ ] **Step 1: Write failing tests.** Parse the new workflow with PyYAML. Assert ordered gates: tag validation, exact-tag build, `NotSigned`/hash/Defender proof, clean install plus four packaged smokes, stable-manifest signing, immutable draft upload, and latest non-prerelease publication. Assert malformed tag, non-main commit, draft/prerelease source release, signed bytes, mutated digest, missing secret, and existing release tag each fail before publication.
- [ ] **Step 2: Run red tests.** `python -m pytest tests/test_unsigned_windows_stable_release.py -q`; expect missing-workflow failure.
- [ ] **Step 3: Implement.** Adapt the beta workflow without a shared mode switch. Require non-prerelease source release, omit `--channel beta`, include exact source commit in release evidence/notes, label bytes unsigned, and set final release `--draft=false --prerelease=false --latest=true`. Keep staged release immutable. Update signing policy to permit an explicitly verified unsigned stable path.
- [ ] **Step 4: Run green tests.** `python -m pytest tests/test_unsigned_windows_stable_release.py tests/test_unsigned_windows_beta_release.py tests/test_app_update.py tests/test_windows_release_signing.py -q`; expect all pass. Run `python -m pytest tests -q` and `ruff check .` before PR.
- [ ] **Step 5: Commit.** `git add .github/workflows/publish-unsigned-windows-stable.yml tests/test_unsigned_windows_stable_release.py docs/CODE_SIGNING_POLICY.md && git commit -m "ci: add gated unsigned Windows stable release"`.

### Task 3: Bot PR and non-publishing release rehearsal

**Files:** No product files; PR and test evidence are the deliverable.

**Interfaces:** Website plan consumes the exact stable manifest and asset contract from Task 2.

- [ ] **Step 1: Run checkout-fresh verification.** From the feature head, run full tests, `python build.py`, packaged Sage/API/native/upgrade smokes, and Defender on the package; record exact source and package SHA-256.
- [ ] **Step 2: Open a draft PR into `main`.** Report the changed signed-workflow trigger, unsigned stable gate order, artifacts, and the absence of a published release.
- [ ] **Step 3: Inspect CI and independently review the diff.** Fix any failure on the branch, rerun exact-head checks, and keep the PR draft until the final readiness decision.

## Execution boundary

The plan ends with a tested draft PR and a non-publishing rehearsal. Merging, tagging, dispatching the stable workflow, and changing the public latest release require the full live-acceptance audit and separate final operator handoff described in the spec.
