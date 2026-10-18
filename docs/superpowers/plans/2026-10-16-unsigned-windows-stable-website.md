# Unsigned Windows Stable Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the protected CATalyst website verify and describe an unsigned stable Windows release without treating it as a beta or a signed installer.

**Architecture:** Extend the existing independent unsigned-beta verifier with a strict stable-channel contract, then teach metadata generation and page rendering a distinct `unsigned_stable` state. Retain the signed and beta paths and their fail-closed behavior. Implement in a feature branch of `Lowestofttim/catalystxch`; the approved design is stored in the bot repository.

**Tech Stack:** Python 3.12, Ed25519 verification, `osslsigncode`, vanilla JavaScript, GitHub Actions, Pages.

**Spec:** `catalyst-bot/docs/superpowers/specs/2026-10-16-unsigned-windows-stable-release-design.md`

## Global Constraints

- `unsigned_stable` requires a public latest non-prerelease release in `Lowestofttim/catalyst-releases` and a signed update manifest with `channel: stable`.
- Verify exact installer URL/name, actual downloaded bytes, GitHub digest, SHA-256 sidecar, Ed25519 signature, and `NotSigned` status; reject any signing-evidence artifact.
- Invalid or missing evidence disables the download; never relabel invalid signed evidence as unsigned.
- Keep `unsigned_beta` and SignPath-verified metadata states distinct.
- Say “Unsigned Windows release” and show exact SHA-256. Do not claim an Authenticode publisher or tell users to disable Windows protection.
- Keep “New Dexie only beta testing” live until the separate general-readiness decision and publication.

## Review Focus

- A release with `isPrerelease: true` must not become unsigned stable (Task 1 test).
- A manifest with valid signature but `channel: beta` must not become unsigned stable (Task 1 test).
- Installer bytes with a valid sidecar but a different GitHub digest must be rejected (Task 1 test).
- A release carrying malformed signing evidence must fail closed, not fall back to unsigned (Task 2 test).
- Smart App Control or policy with no “Run anyway” option must not be described as bypassable (Task 3 copy test).

---

### Task 1: Verify unsigned stable bytes and manifest

**Files:** Modify `scripts/windows_release_verification.py`; modify `scripts/check_windows_release_verification.py`.

**Interfaces:** Add `verify_unsigned_windows_stable_release(release: Mapping[str, object], temp_root: Path | None = None, urlopen=urllib.request.urlopen, runner=subprocess.run, system_name: str | None = None, manifest_public_key_b64: str = UPDATE_MANIFEST_PUBLIC_KEY_B64) -> dict[str, object]`, returning `download_enabled: True`, `distribution_status: "unsigned_stable"`, and a `verification` object with `authenticode_status: "unsigned"`, null publisher/signature evidence, and valid signed-manifest URLs. Reuse byte-download and `NotSigned` helpers from the beta verifier.

- [ ] **Step 1: Write failing fixture tests.** A non-prerelease fixture with exact release URLs, installer bytes, digest, sidecar, signed `stable` manifest, and `NotSigned` succeeds. Variants with prerelease/draft, beta channel, wrong signature, hash, URL, byte size, Authenticode signature, or a signing-evidence asset fail.
- [ ] **Step 2: Run red test.** `python scripts/check_windows_release_verification.py`; expect the new stable test to fail because its verifier is absent.
- [ ] **Step 3: Implement the stable verifier.** Share exact-byte proof where safe; enforce release state and `channel: stable` before returning `unsigned_stable`. Preserve the beta verifier's prerelease and `channel: beta` contract.
- [ ] **Step 4: Run green test.** Repeat Step 2; expect all verifier fixtures to pass.
- [ ] **Step 5: Commit.** `git add scripts/windows_release_verification.py scripts/check_windows_release_verification.py && git commit -m "feat: verify unsigned stable Windows release"`.

### Task 2: Sync fail-closed stable metadata

**Files:** Modify `scripts/sync_release_metadata.py`, `scripts/check_sync_release_fallbacks.py`, `scripts/check_release_metadata.py`, and `.github/workflows/sync-release-metadata.yml`.

**Interfaces:** `build_metadata(..., allow_unsigned_windows_stable: bool = False, windows_unsigned_stable_verifier=verify_unsigned_windows_stable_release)` produces one Windows installer record with `distribution_status: "unsigned_stable"` only after Task 1 proof. CLI adds `--allow-unsigned-windows-stable`; the protected-main workflow uses it and checks the generated HTML fallbacks before proposing a Pages update.

- [ ] **Step 1: Write failing metadata tests.** Assert an exact verified stable fixture generates enabled `unsigned_stable`; prerelease, missing manifest, wrong hash, and malformed signing evidence generate disabled Windows downloads. Assert beta and SignPath fixtures retain their current statuses. Assert the workflow invokes protected metadata/render checks before updating Pages content.
- [ ] **Step 2: Run red tests.** `python scripts/check_sync_release_fallbacks.py && python scripts/check_release_metadata.py`; expect new stable assertions to fail.
- [ ] **Step 3: Implement metadata integration.** Add the explicit stable opt-in flag and verifier call, preserve the no-fallback-on-signing-evidence rule, and update static fallback generation and protected workflow invocation.
- [ ] **Step 4: Run green tests.** Repeat Step 2 plus `python scripts/check_sync_workflow.py`.
- [ ] **Step 5: Commit.** `git add scripts .github/workflows/sync-release-metadata.yml && git commit -m "feat: sync verified unsigned stable metadata"`.

### Task 3: Render honest Windows download guidance

**Files:** Modify `assets/release.js`, `index.html`, `docs.html`, `scripts/check_release_js_behavior.js`, `scripts/check_release_dom_rendering.py`, and `scripts/check_release_metadata.py`.

**Interfaces:** `unsigned_stable` renders the verified exact download link and digest, “Unsigned Windows release,” an explicit absence of verified publisher, and ordinary SmartScreen guidance. Signed and beta views remain unchanged.

- [ ] **Step 1: Write failing DOM and JS tests.** Assert stable copy, exact link/digest, no verified-publisher claim, `More info` and `Run anyway` only for the ordinary “Windows protected your PC” warning, and explicit no-bypass wording for Smart App Control/organization policy. Assert malware/PUA warnings do not get the continuation instruction. Assert wrong status/evidence disables the link.
- [ ] **Step 2: Run red tests.** `node scripts/check_release_js_behavior.js && python scripts/check_release_dom_rendering.py`; expect unsigned-stable rendering assertions to fail.
- [ ] **Step 3: Implement rendering.** Add a distinct `isUnsignedWindowsStable()` state check to `assets/release.js`, use text-safe DOM updates, and update the HTML fallback copy. Keep the live beta headline until the actual general-release handoff.
- [ ] **Step 4: Run green tests.** Repeat Step 2 and `python scripts/check_release_metadata.py`.
- [ ] **Step 5: Commit.** `git add assets/release.js index.html docs.html scripts && git commit -m "feat: explain verified unsigned stable download"`.

### Task 4: Website PR and deployment gate

**Files:** No product files; PR and published-site audit are the deliverables.

**Interfaces:** Consumes the exact bot release artifact contract from the companion plan; does not publish an installer or change the public latest release itself.

- [ ] **Step 1: Run all website metadata, JS, DOM, workflow, and link checks from a fresh checkout; record the exact head SHA.**
- [ ] **Step 2: Open a draft PR into website `main`, inspect CI and independent review, and fix any failure on the branch.**
- [ ] **Step 3: With a staged fixture, prove the protected metadata check rejects mismatched release assets and keeps the live site unchanged.**
- [ ] **Step 4: At the later approved publication handoff, verify Pages deployment and fetch the actual public URL to compare rendered copy, download URL, installer bytes, digest, and manifest against the final release.**

## Execution boundary

This plan produces a tested draft website PR. It does not merge or deploy general-release copy until the exact Windows release exists and the live-readiness ledger plus final review passes. Current unsigned beta copy and URLs remain public meanwhile.
