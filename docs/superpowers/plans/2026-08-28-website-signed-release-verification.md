# Website Signed Windows Release Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make catalystxch.com expose the CATalyst Windows installer only after the website workflow independently downloads and validates the exact signed installer, checksum, release evidence, publisher, timestamp, origin, and version.

**Architecture:** Add a standard-library Python verifier that downloads the public release assets into an isolated temporary directory, checks every digest and evidence field, and invokes `osslsigncode` on Linux to validate Authenticode. Upgrade website release metadata to schema version 2 with per-asset availability and signature evidence. Make HTML fallbacks and browser JavaScript fail closed for Windows without disabling verified Linux downloads, then install `osslsigncode` in the protected-main synchronization workflow.

**Tech Stack:** Python 3.12 standard library, Node.js 24, vanilla JavaScript, `osslsigncode`, GitHub CLI, GitHub Actions, Playwright, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-08-28-signpath-windows-release-signing-design.md` in `catalystxch/catalyst-bot`.

**Source Plan:** `docs/superpowers/plans/2026-08-28-signpath-windows-release-signing.md` in `catalystxch/catalyst-bot`.

## Global Constraints

- Execute this plan in a new isolated website worktree created from `origin/main` commit `847ef4668c853cabd6712a1bb6a2ee5e2400573b`; do not edit the stale `C:\catalyst\catalystxch-site` checkout directly.
- Use branch `codex/signpath-release-verification` and a pull request into protected `main` in `Lowestofttim/catalystxch`.
- Expected Windows publisher is exactly `SignPath Foundation`; expected product is exactly `CATalyst`.
- Consume `windows-signature-v1.3.17.json` with schema version 1 exactly as defined in the source plan. Do not invent a second evidence schema.
- Treat GitHub's asset digest, the `.sha256` sidecar, downloaded bytes, evidence hash/size, release tag, filename, and version as one trust chain. Any mismatch disables Windows publication.
- `osslsigncode verify` is mandatory in CI. Missing tooling, malformed output, a bad certificate, an absent timestamp, or a verification failure must fail before metadata is written.
- The current unsigned v1.3.16 Windows installer must not remain downloadable or be described as signed. Linux v1.3.16 downloads and the macOS source link may remain available.
- Metadata synchronization is atomic. A failed Windows verification leaves the previous verified metadata unchanged and creates no pull request.
- JavaScript independently enforces the verified per-asset fields. A hand-edited URL alone must never enable the Windows button.
- New signed release is `v1.3.17`; stop and coordinate with the source release plan if either release repository already contains that tag.

---

### Task 1: Isolated Website Worktree and Baseline

**Files:**
- No source changes.

**Interfaces:**
- Consumes: `C:\catalyst\catalystxch-site` and `origin/main`.
- Produces: clean isolated checkout on `codex/signpath-release-verification` with a recorded baseline.

- [ ] **Step 1: Invoke the required worktree skill**

Use `superpowers:using-git-worktrees` before creating the website checkout. Verify that the selected parent directory is outside the repository and ignored where applicable.

- [ ] **Step 2: Fetch and create the exact branch checkout**

```powershell
$websiteRepo = "C:\catalyst\catalystxch-site"
$websiteWorktree = "C:\Users\t_you\.config\superpowers\worktrees\catalystxch-site\signpath-release-verification"
git -C $websiteRepo fetch origin main --prune
if ((git -C $websiteRepo rev-parse origin/main) -ne "847ef4668c853cabd6712a1bb6a2ee5e2400573b") {
  throw "website origin/main moved; inspect the new commits before continuing"
}
git -C $websiteRepo worktree add $websiteWorktree -b codex/signpath-release-verification origin/main
git -C $websiteWorktree status --short
```

Expected: final status output is empty.

- [ ] **Step 3: Run the current website checks**

```powershell
Set-Location $websiteWorktree
python scripts/check_release_metadata.py
python scripts/check_sync_release_fallbacks.py
python scripts/check_sync_workflow.py
node scripts/check_release_js_behavior.js
python scripts/check_release_dom_rendering.py
```

Expected: every current check passes. Record failures as baseline defects before changing release verification.

### Task 2: Pure Windows Release Evidence Validation

**Files:**
- Create: `scripts/windows_release_verification.py`
- Create: `scripts/check_windows_release_verification.py`

**Interfaces:**
- Consumes: GitHub release JSON, exact installer bytes, exact checksum sidecar, exact evidence JSON, and `osslsigncode` output.
- Produces: `ReleaseVerificationError`, `sha256_file`, `find_release_asset`, `parse_sha256_sidecar`, `validate_evidence`, `parse_osslsigncode_output`, and a verified per-asset metadata mapping.

- [ ] **Step 1: Write a failing standalone unit check**

Create fixtures entirely inside `tempfile.TemporaryDirectory`; do not hit GitHub. The check imports:

```python
from windows_release_verification import (
    ReleaseVerificationError,
    find_release_asset,
    parse_osslsigncode_output,
    parse_sha256_sidecar,
    sha256_file,
    validate_evidence,
)
```

Use concrete evidence:

```python
VALID_HASH = "c" * 64
VALID_EVIDENCE = {
    "schema_version": 1,
    "artifact": {
        "name": "Catalyst-Setup-v1.3.17.exe",
        "size_bytes": 16,
        "sha256": VALID_HASH,
    },
    "signature": {
        "authenticode_status": "Valid",
        "publisher": "SignPath Foundation",
        "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
        "signer_thumbprint": "A" * 40,
        "timestamp_status": "Valid",
        "timestamp_subject": "CN=DigiCert Timestamp 2025",
        "timestamp_thumbprint": "B" * 40,
        "product_name": "CATalyst",
        "product_version": "1.3.17",
        "file_version": "1.3.17.0",
    },
    "source": {
        "repository": "catalystxch/catalyst-bot",
        "tag": "v1.3.17",
        "commit": "a" * 40,
        "workflow_run_url": "https://github.com/catalystxch/catalyst-bot/actions/runs/123",
    },
    "signpath": {
        "application_signing_request_id": "application-request-id",
        "installer_signing_request_id": "installer-request-id",
    },
}
```

Assert that valid evidence is normalized and returned. Parameterize mutations for wrong schema, filename, size, hash, publisher, Authenticode status, timestamp status, product, product version, file version, source repository, source tag, source commit length, workflow URL host/path, and blank request IDs; each must raise `ReleaseVerificationError`.

Test sidecars with exact accepted syntax `HASH  Catalyst-Setup-v1.3.17.exe` and reject another filename, another hash, multiple nonblank records, or a malformed digest. Test `osslsigncode` output containing `Succeeded`, `Subject: CN=SignPath Foundation`, and `The signature is timestamped`; reject missing markers and a publisher that merely appears in unrelated text.

- [ ] **Step 2: Run the check and observe the intended import failure**

Run: `python scripts/check_windows_release_verification.py`

Expected: `ModuleNotFoundError: No module named 'windows_release_verification'`.

- [ ] **Step 3: Implement the pure validation functions**

Implement these functions with the exact fail-closed behavior below:

```python
import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse


class ReleaseVerificationError(RuntimeError):
    """Raised when a public Windows release cannot be independently verified."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_release_asset(
    release: Mapping[str, object], name: str
) -> Mapping[str, object]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseVerificationError("release assets are missing")
    matches = [
        item
        for item in assets
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ReleaseVerificationError(f"expected one release asset named {name}")
    return matches[0]


def parse_sha256_sidecar(text: str, expected_name: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ReleaseVerificationError("checksum sidecar must contain one record")
    match = re.fullmatch(r"([a-fA-F0-9]{64})[ \t]+\*?(.+)", lines[0])
    if not match or match.group(2) != expected_name:
        raise ReleaseVerificationError("checksum sidecar filename is invalid")
    return match.group(1).lower()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReleaseVerificationError(f"evidence {field} is missing")
    return value


def validate_evidence(
    evidence: Mapping[str, object],
    installer_name: str,
    installer_sha256: str,
    installer_size: int,
    expected_version: str,
) -> dict[str, object]:
    artifact = _mapping(evidence.get("artifact"), "artifact")
    signature = _mapping(evidence.get("signature"), "signature")
    source = _mapping(evidence.get("source"), "source")
    signpath = _mapping(evidence.get("signpath"), "signpath")
    expected = {
        "schema_version": (evidence.get("schema_version"), 1),
        "artifact name": (artifact.get("name"), installer_name),
        "artifact size": (artifact.get("size_bytes"), installer_size),
        "artifact hash": (artifact.get("sha256"), installer_sha256),
        "Authenticode status": (signature.get("authenticode_status"), "Valid"),
        "publisher": (signature.get("publisher"), "SignPath Foundation"),
        "timestamp status": (signature.get("timestamp_status"), "Valid"),
        "product": (signature.get("product_name"), "CATalyst"),
        "product version": (signature.get("product_version"), expected_version),
        "file version": (signature.get("file_version"), f"{expected_version}.0"),
        "source repository": (source.get("repository"), "catalystxch/catalyst-bot"),
        "source tag": (source.get("tag"), f"v{expected_version}"),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ReleaseVerificationError(f"evidence {field} does not match")
    if not re.fullmatch(r"[A-F0-9]{40}", str(signature.get("signer_thumbprint") or "")):
        raise ReleaseVerificationError("evidence signer thumbprint is invalid")
    if not re.fullmatch(r"[A-F0-9]{40}", str(signature.get("timestamp_thumbprint") or "")):
        raise ReleaseVerificationError("evidence timestamp thumbprint is invalid")
    if not re.fullmatch(r"[a-f0-9]{40}", str(source.get("commit") or "")):
        raise ReleaseVerificationError("evidence source commit is invalid")
    workflow_url = urlparse(str(source.get("workflow_run_url") or ""))
    if (
        workflow_url.scheme != "https"
        or workflow_url.netloc != "github.com"
        or not workflow_url.path.startswith(
            "/catalystxch/catalyst-bot/actions/runs/"
        )
    ):
        raise ReleaseVerificationError("evidence workflow URL is invalid")
    for key in ("application_signing_request_id", "installer_signing_request_id"):
        if not str(signpath.get(key) or "").strip():
            raise ReleaseVerificationError(f"evidence {key} is missing")
    return {
        "signature": dict(signature),
        "source": dict(source),
        "signpath": dict(signpath),
    }


def parse_osslsigncode_output(output: str) -> str:
    subject_match = re.search(r"(?m)^Subject:\s*(.+SignPath Foundation.+)$", output)
    if "Succeeded" not in output or "The signature is timestamped" not in output:
        raise ReleaseVerificationError("osslsigncode did not prove a timestamped signature")
    if not subject_match:
        raise ReleaseVerificationError("osslsigncode publisher is not SignPath Foundation")
    return subject_match.group(1).strip()
```

Use exact equality for all publisher/product/version/status fields. Return the validated signer subject from `parse_osslsigncode_output`; never return success based only on process exit code.

- [ ] **Step 4: Run the standalone check**

Run: `python scripts/check_windows_release_verification.py`

Expected: `Windows release evidence validation checks passed`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/windows_release_verification.py scripts/check_windows_release_verification.py
git commit -m "test: validate signed Windows release evidence"
```

### Task 3: Independent Asset Download and Authenticode Verification

**Files:**
- Modify: `scripts/windows_release_verification.py`
- Modify: `scripts/check_windows_release_verification.py`

**Interfaces:**
- Consumes: a public release mapping and injectable URL opener/process runner.
- Produces: `verify_windows_release(release, temp_root=None, urlopen=urllib.request.urlopen, runner=subprocess.run) -> dict[str, object]`.

- [ ] **Step 1: Add a failing end-to-end pure check with injected I/O**

Build a release mapping whose assets include:

```python
{
    "name": "Catalyst-Setup-v1.3.17.exe",
    "url": "https://github.com/Lowestofttim/catalyst-releases/releases/download/v1.3.17/Catalyst-Setup-v1.3.17.exe",
    "size": len(installer_bytes),
    "digest": f"sha256:{installer_hash}",
}
```

Also include `Catalyst-Setup-v1.3.17.exe.sha256` and `windows-signature-v1.3.17.json` with exact GitHub release URLs. Inject a fake `urlopen` that returns those bytes by URL and a fake runner that asserts this command:

```python
["osslsigncode", "verify", "-in", str(downloaded_installer)]
```

Assert the result is:

```python
{
    "download_enabled": True,
    "verification": {
        "authenticode_status": "valid",
        "publisher": "SignPath Foundation",
        "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
        "signer_thumbprint": "A" * 40,
        "timestamp_status": "valid",
        "evidence_url": "https://github.com/Lowestofttim/catalyst-releases/releases/download/v1.3.17/windows-signature-v1.3.17.json",
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
    },
}
```

Add negative cases for an HTTP error, redirected final URL outside `github.com`/`release-assets.githubusercontent.com`, missing asset, GitHub digest mismatch, sidecar mismatch, evidence mismatch, missing `osslsigncode`, non-zero process result, and malformed successful output.

- [ ] **Step 2: Run the check and observe the missing interface**

Run: `python scripts/check_windows_release_verification.py`

Expected: failure reports missing `verify_windows_release`.

- [ ] **Step 3: Implement fail-closed downloading and verification**

Derive the installer name from the exact tag using `Catalyst-Setup-{tag}.exe`, and derive the two companion names. Permit initial asset URLs only under the public release repository prefix. Stream each response to disk while hashing; set a finite timeout and a CATalyst website verifier user agent. Validate the response's final URL host. Check, in order:

1. downloaded installer size equals GitHub asset size;
2. downloaded hash equals GitHub asset `sha256:` digest;
3. sidecar filename and hash equal the installer;
4. evidence artifact name, size, hash, version, publisher, timestamp, product, source repository/tag, workflow URL, and request IDs match;
5. `osslsigncode verify -in` exits zero; and
6. parsed certificate subject contains the exact `SignPath Foundation` publisher component.

Use `TemporaryDirectory(dir=temp_root)` so no unverified bytes remain. Catch `FileNotFoundError`, `OSError`, `subprocess.CalledProcessError`, `urllib.error.URLError`, JSON errors, and validation errors and re-raise `ReleaseVerificationError` without credentials, signed URLs, or response bodies in the message.

- [ ] **Step 4: Run the complete verifier check**

Run: `python scripts/check_windows_release_verification.py`

Expected: all pure and injected-I/O checks pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/windows_release_verification.py scripts/check_windows_release_verification.py
git commit -m "feat: independently verify public Windows installer"
```

### Task 4: Release Metadata Schema 2 and Atomic Sync

**Files:**
- Modify: `scripts/sync_release_metadata.py`
- Modify: `scripts/check_sync_release_fallbacks.py`
- Modify: `assets/release/latest.json`

**Interfaces:**
- Consumes: release JSON and `verify_windows_release`.
- Produces: schema version 2 metadata with per-asset `download_enabled` and Windows `verification`, written atomically only after all validation succeeds.

- [ ] **Step 1: Add failing schema and atomicity checks**

Extend `check_sync_release_fallbacks.py` with a synthetic release and injected verifier. Assert a verified Windows asset has this shape:

```python
{
    "name": "Catalyst-Setup-v9.8.7.exe",
    "platform": "windows",
    "kind": "installer",
    "size_bytes": 28_169_368,
    "download_url": "https://github.com/Lowestofttim/catalyst-releases/releases/download/v9.8.7/Catalyst-Setup-v9.8.7.exe",
    "sha256": "a" * 64,
    "download_enabled": True,
    "verification": {
        "authenticode_status": "valid",
        "publisher": "SignPath Foundation",
        "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
        "signer_thumbprint": "A" * 40,
        "timestamp_status": "valid",
        "evidence_url": "https://github.com/Lowestofttim/catalyst-releases/releases/download/v9.8.7/windows-signature-v9.8.7.json",
        "evidence_sha256": "c" * 64,
    },
}
```

Assert Linux assets retain `download_enabled: True` without Windows signature claims. Assert `render_release_fallbacks` reports Linux available when Windows is disabled. Patch `Path.replace`/temporary output behavior and prove a verifier exception leaves an existing output file byte-for-byte unchanged.

- [ ] **Step 2: Run the check and observe schema-1 failures**

Run: `python scripts/check_sync_release_fallbacks.py`

Expected: failures show missing per-asset availability/verification and global Windows coupling.

- [ ] **Step 3: Integrate the verifier and atomic output**

Change `build_metadata` to accept `windows_verifier=verify_windows_release`. When download URLs are requested, call it once for the release and merge its result only into the exact Windows installer. Add `download_enabled` to every downloadable asset. Set top-level `downloads_enabled` to `any(asset["download_enabled"] for asset in assets)`, so Linux availability cannot imply Windows availability.

Replace direct `output.write_text` with a temporary sibling created in the same directory, `flush`, `os.fsync`, and `Path.replace`; delete the temporary file on failure. Run verification before rendering or writing HTML fallbacks.

Update `_find_platform_download` and `render_release_fallbacks` to require `asset.get("download_enabled") is True`. Add `data-release-windows-signature` fallback text:

- verified: `Verified publisher: SignPath Foundation`;
- disabled: `Windows installer unavailable - signature verification required`.

- [ ] **Step 4: Disable the current unsigned v1.3.16 Windows asset in committed metadata**

Upgrade `assets/release/latest.json` to schema version 2. Preserve the release name/date/notes and Linux assets. Set the v1.3.16 Windows record to:

```json
{
  "name": "Catalyst-Setup-v1.3.16.exe",
  "platform": "windows",
  "kind": "installer",
  "size_bytes": 28225931,
  "download_url": null,
  "sha256": null,
  "download_enabled": false,
  "verification": {
    "authenticode_status": "unavailable",
    "publisher": null,
    "signer_subject": null,
    "signer_thumbprint": null,
    "timestamp_status": "unavailable",
    "evidence_url": null,
    "evidence_sha256": null
  }
}
```

Give each Linux record `download_enabled: true`. Keep top-level downloads enabled because verified-by-digest Linux downloads remain available, but set `download_status` to `partial` until Windows is signed.

- [ ] **Step 5: Run the sync checks**

Run:

```powershell
python scripts/check_windows_release_verification.py
python scripts/check_sync_release_fallbacks.py
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/sync_release_metadata.py scripts/check_sync_release_fallbacks.py assets/release/latest.json
git commit -m "feat: publish per-asset signed release metadata"
```

### Task 5: Metadata Policy Checker and Browser Enforcement

**Files:**
- Modify: `scripts/check_release_metadata.py`
- Modify: `scripts/check_release_js_behavior.js`
- Modify: `scripts/check_release_dom_rendering.py`
- Modify: `assets/release.js`
- Modify: `index.html`
- Modify: `docs.html`

**Interfaces:**
- Consumes: schema version 2 release metadata.
- Produces: a Windows download button only for an independently verified SignPath Foundation asset; Linux remains independent.

- [ ] **Step 1: Add failing policy assertions**

In `check_release_metadata.py`, require schema 2 and validate every asset. A Windows installer may be enabled only when all of these hold:

```python
asset["download_enabled"] is True
asset["verification"]["authenticode_status"] == "valid"
asset["verification"]["publisher"] == "SignPath Foundation"
asset["verification"]["timestamp_status"] == "valid"
re.fullmatch(r"[A-F0-9]{40}", asset["verification"]["signer_thumbprint"])
re.fullmatch(r"[a-f0-9]{64}", asset["verification"]["evidence_sha256"])
```

Require a disabled Windows asset to have null URL/hash and `authenticode_status: unavailable`. Require enabled Linux assets to retain allowed URL/hash checks without a Windows verification object.

Extend the Node check to prove that:

- a URL/hash-only Windows asset remains disabled;
- a wrong publisher remains disabled;
- a missing/invalid timestamp remains disabled;
- valid SignPath fields enable Windows;
- disabled Windows plus enabled Linux leaves Linux enabled; and
- load, `pageshow`, and visibility refreshes preserve these rules.

Extend the DOM check to assert the disabled v1.3.16 Windows button has no `href`, Linux has an allowed `href`, and the signature status text is visible.

- [ ] **Step 2: Run checks and observe the intended failures**

```powershell
python scripts/check_release_metadata.py
node scripts/check_release_js_behavior.js
python scripts/check_release_dom_rendering.py
```

Expected: failures report schema 1 assumptions, Windows URL-only enablement, and missing signature status hooks.

- [ ] **Step 3: Implement exact browser gating**

Add:

```javascript
const isVerifiedWindowsInstaller = (asset) => (
  asset &&
  asset.download_enabled === true &&
  asset.verification &&
  asset.verification.authenticode_status === "valid" &&
  asset.verification.publisher === "SignPath Foundation" &&
  asset.verification.timestamp_status === "valid" &&
  /^[A-F0-9]{40}$/.test(asset.verification.signer_thumbprint || "") &&
  /^[a-f0-9]{64}$/.test(asset.verification.evidence_sha256 || "")
);
```

Make `findWindowsInstaller` require this function in addition to the existing URL/hash allowlist. Make general asset discovery require `download_enabled === true`. Remove the branch that disables Linux merely because Windows is unavailable.

Add `data-release-windows-signature` hooks to `index.html` and `docs.html`. Replace any unconditional claim that the public Windows channel is signed with: `Windows downloads are enabled only after independent Authenticode verification.` Set the current fallback to `Windows installer unavailable - signature verification required`.

- [ ] **Step 4: Run all metadata/browser checks**

```powershell
python scripts/check_release_metadata.py
python scripts/check_sync_release_fallbacks.py
node scripts/check_release_js_behavior.js
python scripts/check_release_dom_rendering.py
```

Expected: all pass and the current unsigned Windows download is visibly disabled while Linux remains available.

- [ ] **Step 5: Commit**

```powershell
git add scripts/check_release_metadata.py scripts/check_release_js_behavior.js scripts/check_release_dom_rendering.py assets/release.js index.html docs.html
git commit -m "fix: gate Windows download on verified publisher"
```

### Task 6: Protected-Main Workflow Tooling and Failure Semantics

**Files:**
- Modify: `.github/workflows/sync-release-metadata.yml`
- Modify: `scripts/check_sync_workflow.py`

**Interfaces:**
- Consumes: public release assets and Linux runner packages.
- Produces: a sync PR only after independent Authenticode verification.

- [ ] **Step 1: Add failing workflow markers**

Extend `check_sync_workflow.py` to require:

```python
required.update({
    "sudo apt-get install -y osslsigncode": "the independent Authenticode verifier",
    "python scripts/check_windows_release_verification.py": "pure Windows release verifier regression checks",
    "windows-signature-": "the signed evidence companion asset",
})
```

Also assert the sync step appears after the package installation and the metadata check appears after sync. Keep existing immutable-action and protected-main assertions.

- [ ] **Step 2: Run the checker and observe missing tooling**

Run: `python scripts/check_sync_workflow.py`

Expected: failure reports missing `osslsigncode` installation.

- [ ] **Step 3: Install and exercise the verifier in CI**

Before metadata sync, add:

```yaml
- name: Install independent Authenticode verifier
  run: |
    sudo apt-get update
    sudo apt-get install -y osslsigncode

- name: Check Windows release verifier
  run: python scripts/check_windows_release_verification.py
```

Keep the existing sync command, but it must now fail before writing when the release lacks evidence or validation fails. Do not add `continue-on-error`, an unsigned flag, or a catch that converts failure to disabled metadata during an attempted new release sync. Because the worktree stays unchanged, the existing PR creation block will create no commit/PR.

- [ ] **Step 4: Run the workflow and release checks**

```powershell
python scripts/check_sync_workflow.py
python scripts/check_windows_release_verification.py
python scripts/check_release_metadata.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/sync-release-metadata.yml scripts/check_sync_workflow.py
git commit -m "ci: verify Authenticode before website release sync"
```

### Task 7: Public Code-Signing and Privacy Links

**Files:**
- Modify: `index.html`
- Modify: `docs.html`
- Modify: `scripts/check_release_metadata.py`

**Interfaces:**
- Consumes: merged public documents in `catalystxch/catalyst-bot`.
- Produces: visible website links to the policy and privacy disclosure used for SignPath enrollment.

- [ ] **Step 1: Add failing link checks**

Require both HTML files to contain:

```text
https://github.com/catalystxch/catalyst-bot/blob/main/docs/CODE_SIGNING_POLICY.md
https://github.com/catalystxch/catalyst-bot/blob/main/docs/PRIVACY.md
```

Require link text containing `Code signing policy` and `Privacy`.

- [ ] **Step 2: Run the metadata check and observe missing links**

Run: `python scripts/check_release_metadata.py`

Expected: failure reports the missing policy link.

- [ ] **Step 3: Add links near download verification information**

Use normal external anchors with `target="_blank"` and `rel="noopener"`. Do not copy policy text into the site; keep the source repository as the canonical document.

- [ ] **Step 4: Run the checker**

Run: `python scripts/check_release_metadata.py`

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add index.html docs.html scripts/check_release_metadata.py
git commit -m "docs: link release signing and privacy policies"
```

### Task 8: Website Verification, Pull Request, and Merge

**Files:**
- Modify only if verification exposes a defect: files from Tasks 2-7 and their checks.

**Interfaces:**
- Produces: protected-main website PR with green static, browser, and release verification.

- [ ] **Step 1: Run every website check**

```powershell
python scripts/check_windows_release_verification.py
python scripts/check_release_metadata.py
python scripts/check_sync_release_fallbacks.py
python scripts/check_sync_workflow.py
node scripts/check_release_js_behavior.js
python scripts/check_release_dom_rendering.py
npx --yes html-validate@11.4.0 index.html docs.html
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 2: Prove disabled-Windows/available-Linux rendering in a real browser**

Use the existing Playwright setup and `check_release_dom_rendering.py`. Capture a screenshot to a temporary directory, inspect it, and confirm the Windows button is visibly disabled, signature-verification text is present, Linux remains enabled, and no raw JSON is shown.

- [ ] **Step 3: Push and open the PR**

```powershell
git push -u origin codex/signpath-release-verification
gh pr create --repo Lowestofttim/catalystxch --base main --head codex/signpath-release-verification --title "Verify signed CATalyst Windows releases" --body "Fail closed on unsigned Windows releases, independently verify SignPath Authenticode evidence, and keep Linux availability independent."
```

- [ ] **Step 4: Wait for checks and merge only when green**

```powershell
$websitePr = gh pr view codex/signpath-release-verification --repo Lowestofttim/catalystxch --json number --jq .number
if (-not $websitePr) { throw "website release-verification PR number was not found" }
gh pr checks $websitePr --repo Lowestofttim/catalystxch --watch
if ($LASTEXITCODE -ne 0) { throw "website release-verification PR checks failed" }
gh pr merge $websitePr --repo Lowestofttim/catalystxch --squash --delete-branch
```

Expected: protected `main` contains schema-2 and verification logic. If checks fail, fix on the branch and repeat Tasks 8.1-8.4.

### Task 9: Signed v1.3.17 Website Publication and Download Proof

**Files:**
- Generated by automation after successful sync: `assets/release/latest.json`, `index.html`, `docs.html`.

**Interfaces:**
- Consumes: successfully completed source plan v1.3.17 release.
- Produces: live schema-2 website metadata and a website button bound to the verified v1.3.17 installer.

- [ ] **Step 1: Confirm public release assets before sync**

```powershell
gh release view v1.3.17 --repo Lowestofttim/catalyst-releases --json tagName,isDraft,isPrerelease,assets
```

Expected assets include the installer, `.sha256` sidecar, and `windows-signature-v1.3.17.json`. Stop if the release is draft, any asset is missing, or the installer digest is absent.

- [ ] **Step 2: Dispatch the website sync and watch it**

```powershell
gh workflow run sync-release-metadata.yml --repo Lowestofttim/catalystxch --ref main
$syncRun = gh run list --repo Lowestofttim/catalystxch --workflow sync-release-metadata.yml --limit 1 --json databaseId --jq '.[0].databaseId'
if (-not $syncRun) { throw "website sync run was not found" }
gh run watch $syncRun --repo Lowestofttim/catalystxch --exit-status
```

Expected: independent verification succeeds, automation PR merges, and Pages rebuild completes.

- [ ] **Step 3: Verify live metadata without cache**

```powershell
$cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$metadata = Invoke-RestMethod -Uri "https://catalystxch.com/assets/release/latest.json?verify=$cacheBust"
if ($metadata.schema_version -ne 2) { throw "live metadata is not schema 2" }
if ($metadata.latest.version -ne "v1.3.17") { throw "live metadata is not v1.3.17" }
$windows = $metadata.latest.assets | Where-Object { $_.platform -eq "windows" -and $_.kind -eq "installer" }
if ($windows.download_enabled -ne $true) { throw "live Windows download is disabled" }
if ($windows.verification.publisher -ne "SignPath Foundation") { throw "live publisher is not SignPath Foundation" }
if ($windows.verification.authenticode_status -ne "valid" -or $windows.verification.timestamp_status -ne "valid") {
  throw "live Windows signature metadata is invalid"
}
```

- [ ] **Step 4: Verify the live browser behavior**

Open `https://catalystxch.com` in a fresh browser session. Confirm the page shows `v1.3.17`, `Verified publisher: SignPath Foundation`, an enabled Windows download, enabled Linux download, and no stale v1.3.16 download claim.

- [ ] **Step 5: Hand off the exact website button to source-plan installation proof**

Complete source plan Task 9 Steps 5-7: download through the live button, verify byte hash/AuthentiCode/Defender, install into an isolated current-user directory, confirm installed signature/version/hash, and launch the CATalyst desktop interface without starting any trading or wallet action.

- [ ] **Step 6: Record the website acceptance checkpoint**

Report the website commit, sync workflow run, Pages deployment result, live metadata URL/version, installer URL/hash, publisher, timestamp state, evidence URL/hash, and source-plan installation result. Do not describe the release as reputation-established; Authenticode validity and SmartScreen reputation are separate properties.
