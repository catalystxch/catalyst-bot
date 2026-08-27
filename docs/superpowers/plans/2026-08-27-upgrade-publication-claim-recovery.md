# Upgrade Publication Claim Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow CATalyst to restart safely after an in-app upgrade interrupts a publication claim before any Dexie or Splash network dispatch begins.

**Architecture:** Add one bounded database recovery transaction that only releases structurally complete `claimed` publication rows when both dispatch-evidence fields are absent and the singleton mutation lease is inactive. Run that local recovery before the existing exact Dexie provider-readback recovery, re-authorize startup after each successful recovery, and keep dispatched, partially evidenced, unresolved, malformed, or actively owned claims fail-closed.

**Tech Stack:** Python 3.12, SQLite WAL transactions, pytest, PyInstaller/Windows release workflow.

**Spec:** `docs/superpowers/specs/2026-08-15-catalyst-stability-kernel-design.md` (startup reconciliation and publication-claim recovery requirements)

## Global Constraints

- Never infer that a remote publication did not occur after dispatch evidence exists.
- Never recover publication authority while the singleton mutation lease is active.
- Preserve exact Dexie provider-readback recovery for expired dispatched claims.
- Recover both Dexie and Splash claims when no network dispatch began.
- Keep all recovery bounded, transactional, idempotent, and fail-closed.

---

### Task 1: Durable undispatched-claim recovery

**Files:**
- Modify: `src/catalyst/database.py`
- Test: `tests/test_publication_outbox.py`

**Interfaces:**
- Consumes: the singleton `runtime_mutation_lease` and durable `publication_outbox` rows.
- Produces: `recover_undispatched_publication_claims_at_startup(*, recovered_at=None) -> dict[str, int]` with `examined`, `recovered`, and `remaining` counts.

- [ ] **Step 1: Write the failing recovery tests**

Add parameterized real-database coverage proving that a future-dated, undispatched claim for either `dexie` or `splash` becomes immediately retryable when no mutation owner is active. Assert the claim authority is cleared, `next_attempt_at` is the supplied recovery time, durable recovery evidence is stored, and the startup snapshot has no publication blocker.

Add fail-closed coverage proving the same function leaves a claim untouched while the singleton mutation lease is active and leaves any claim with dispatch evidence untouched.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_publication_outbox.py -k "upgrade_restart or undispatched_publication" -q`

Expected: FAIL because `database.recover_undispatched_publication_claims_at_startup` does not exist.

- [ ] **Step 3: Implement the bounded recovery transaction**

Validate the recovery timestamp, start `BEGIN IMMEDIATE`, verify a resolved safety latch and inactive singleton mutation lease, select at most `_MAX_STARTUP_RECOVERY_ROWS + 1` claimed rows, and reject an over-limit set. Only transition structurally complete claims with `dispatch_started_at IS NULL` and `request_sha256 IS NULL` to `retryable`; clear the expiring claim fields, preserve monotonic counters, set `next_attempt_at` to the recovery timestamp, and record canonical `UPGRADE_RESTART_RECOVERED_UNDISPATCHED_PUBLICATION_CLAIM` evidence. Return exact counts after the transaction.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/test_publication_outbox.py -k "upgrade_restart or undispatched_publication" -q`

Expected: PASS with no network access.

### Task 2: Desktop startup integration

**Files:**
- Modify: `desktop_app.py`
- Test: `tests/test_mutation_gate.py`

**Interfaces:**
- Consumes: `database.recover_undispatched_publication_claims_at_startup()` and the existing `dexie_manager.recover_expired_dexie_publications_at_startup()`.
- Produces: startup authorization that retries immediately after safe local recovery and only proceeds to Dexie readback if a publication blocker remains.

- [ ] **Step 1: Write the failing upgrade-restart orchestration test**

Model the authorization sequence `PUBLICATION_CLAIM_RECOVERY_REQUIRED -> allowed`, assert local undispatched recovery runs before any provider recovery, and assert startup re-authorizes immediately after one locally recovered claim.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_mutation_gate.py -k "upgrade_restart_undispatched_publication" -q`

Expected: FAIL because startup does not call the local recovery function.

- [ ] **Step 3: Implement the minimal startup order**

When the publication-claims check blocks startup, invoke the local undispatched recovery first. Re-run startup authorization when it recovered at least one row. Only if publication claims still block startup should the existing exact Dexie provider-readback recovery run. Preserve all exception handling as fail-closed.

- [ ] **Step 4: Run targeted startup and publication tests**

Run: `python -m pytest tests/test_publication_outbox.py tests/test_mutation_gate.py tests/test_stability_startup_recovery.py -q`

Expected: PASS.

### Task 3: Release verification and publication

**Files:**
- Modify only if required by release tooling: `_version.py`

**Interfaces:**
- Consumes: the completed branch and repository release workflows.
- Produces: a merged pull request, a new tagged installer, synchronized website metadata, and a public installer whose digest matches the release sidecar and website JSON.

- [ ] **Step 1: Run repository verification**

Run Ruff/check/format gates, the full pytest suite, the Windows PyInstaller build, packaged API/Sage smoke tests, and packaged clean/duplicate/persisted/native safety-launch smokes.

- [ ] **Step 2: Review and merge**

Commit the focused fix, push `codex/upgrade-publication-claim-recovery`, open a pull request into `main`, wait for required checks, resolve review findings, and merge only after every gate passes.

- [ ] **Step 3: Publish the replacement release**

Create the next patch tag from merged `main`, wait for the cross-platform release workflow and public update channel to succeed, then trigger and verify the website release-metadata workflow.

- [ ] **Step 4: Independently verify the public artifact**

Open the live website, confirm it displays the new version and exact Windows URL, download that public installer into `C:\catalyst\.release-verification`, and verify its byte size and SHA-256 against both the release sidecar and the public `latest.json`.
