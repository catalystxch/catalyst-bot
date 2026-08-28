# SignPath Windows Release Signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a v1.3.17 Windows release whose installed CATalyst executable and website installer both carry valid SignPath Foundation Authenticode signatures, with publication blocked unless every verification gate passes.

**Architecture:** Keep the current PyInstaller onedir bundle and Inno Setup installer, but add two sequential SignPath requests: sign `Catalyst.exe`, build the installer from that signed bundle, then sign the installer. A Python verifier provides pure testable validation plus real PowerShell and `signtool` gates, and emits evidence tied to the final installer bytes. Release checksums, updater manifests, and uploads move after signing.

**Tech Stack:** Python 3.12, pytest, PowerShell, Windows SDK `signtool`, PyInstaller, Inno Setup 6, GitHub Actions, SignPath GitHub action v2, Ed25519 updater manifests, GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-08-28-signpath-windows-release-signing-design.md`

## Global Constraints

- Work in `C:\Users\t_you\.config\superpowers\worktrees\catalyst\signpath-release-signing` on `codex/signpath-release-signing`; do not edit the dirty `C:\catalyst` checkout.
- SignPath project slug is `catalyst`; policy slug is `release-signing`.
- Artifact configuration slugs are `catalyst-windows-application-v1` and `catalyst-windows-installer-v1`.
- Expected Authenticode publisher is exactly `SignPath Foundation`; expected product is exactly `CATalyst`.
- Sign CATalyst-owned `Catalyst.exe` and the final Inno installer only. Never sign optional upstream `splash.exe` or third-party DLLs with CATalyst's certificate.
- Pin `signpath/github-action-submit-signing-request` to `c92b958760219087e01f8d67a1669ed57afe2627`.
- Pin `actions/upload-artifact` to `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` and `actions/download-artifact` to `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` if download-artifact is needed.
- Secrets are `SIGNPATH_API_TOKEN`, `CATALYST_UPDATE_SIGNING_KEY_B64`, and `CATALYST_RELEASE_CHANNEL_TOKEN`; `SIGNPATH_ORGANIZATION_ID` is a repository variable.
- Missing credentials, rejected or timed-out signing, a wrong publisher/version/product, a missing timestamp, a signature failure, or a Defender detection must fail the release. There is no unsigned fallback.
- Checksums and updater manifests are generated only after installer signing and verification.
- New release tag is `v1.3.17`; stop before tagging if that tag appears in either release repository.
- All source changes use a feature branch and pull request into protected `main`.

---

### Task 1: Pure Authenticode Validation and Evidence Schema

**Files:**
- Create: `scripts/verify_windows_authenticode.py`
- Create: `tests/test_windows_authenticode.py`

**Interfaces:**
- Consumes: a mapping produced from PowerShell signature and PE version metadata.
- Produces: `VerificationError`, `sha256_file(path: Path) -> str`, `validate_signature_metadata(metadata: Mapping[str, object], expected_version: str, expected_publisher: str = "SignPath Foundation", expected_product: str = "CATalyst") -> dict[str, str]`, and `build_evidence(artifact: Path, metadata: Mapping[str, object], source_repository: str, source_tag: str, source_commit: str, workflow_run_url: str, application_signing_request_id: str, installer_signing_request_id: str) -> dict[str, object]`.
- Evidence schema consumed by the website plan:

```json
{
  "schema_version": 1,
  "artifact": {
    "name": "Catalyst-Setup-v1.3.17.exe",
    "size_bytes": 28225931,
    "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "signature": {
    "authenticode_status": "Valid",
    "publisher": "SignPath Foundation",
    "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
    "signer_thumbprint": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "timestamp_status": "Valid",
    "timestamp_subject": "CN=DigiCert Timestamp 2025",
    "timestamp_thumbprint": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
    "product_name": "CATalyst",
    "product_version": "1.3.17",
    "file_version": "1.3.17.0"
  },
  "source": {
    "repository": "catalystxch/catalyst-bot",
    "tag": "v1.3.17",
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "workflow_run_url": "https://github.com/catalystxch/catalyst-bot/actions/runs/123"
  },
  "signpath": {
    "application_signing_request_id": "application-request-id",
    "installer_signing_request_id": "installer-request-id"
  }
}
```

- [ ] **Step 1: Write the failing pure-validation tests**

```python
from pathlib import Path

import pytest

from scripts.verify_windows_authenticode import (
    VerificationError,
    build_evidence,
    sha256_file,
    validate_signature_metadata,
)


def valid_metadata() -> dict[str, str]:
    return {
        "status": "Valid",
        "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
        "signer_thumbprint": "A" * 40,
        "timestamp_subject": "CN=DigiCert Timestamp 2025",
        "timestamp_thumbprint": "B" * 40,
        "product_name": "CATalyst",
        "product_version": "1.3.17",
        "file_version": "1.3.17.0",
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "NotSigned", "Authenticode status"),
        ("signer_subject", "CN=Unknown Publisher", "publisher"),
        ("timestamp_subject", "", "timestamp"),
        ("product_name", "Other", "product"),
        ("product_version", "1.3.16", "product version"),
        ("file_version", "1.3.16.0", "file version"),
    ],
)
def test_validate_signature_metadata_rejects_invalid_fields(field, value, message):
    metadata = valid_metadata()
    metadata[field] = value
    with pytest.raises(VerificationError, match=message):
        validate_signature_metadata(metadata, expected_version="1.3.17")


def test_build_evidence_binds_final_bytes_and_origin(tmp_path: Path):
    artifact = tmp_path / "Catalyst-Setup-v1.3.17.exe"
    artifact.write_bytes(b"signed-installer")
    evidence = build_evidence(
        artifact=artifact,
        metadata=valid_metadata(),
        source_repository="catalystxch/catalyst-bot",
        source_tag="v1.3.17",
        source_commit="a" * 40,
        workflow_run_url="https://github.com/catalystxch/catalyst-bot/actions/runs/123",
        application_signing_request_id="application-request",
        installer_signing_request_id="installer-request",
    )
    assert evidence["artifact"]["sha256"] == sha256_file(artifact)
    assert evidence["artifact"]["size_bytes"] == len(b"signed-installer")
    assert evidence["signature"]["publisher"] == "SignPath Foundation"
    assert evidence["source"]["tag"] == "v1.3.17"
```

- [ ] **Step 2: Run the focused test and observe the intended failure**

Run: `python -m pytest tests/test_windows_authenticode.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.verify_windows_authenticode'`.

- [ ] **Step 3: Implement the pure validator and evidence builder**

```python
class VerificationError(ValueError):
    """Raised when a Windows release signature cannot be proven valid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_signature_metadata(
    metadata: Mapping[str, object],
    expected_version: str,
    expected_publisher: str = "SignPath Foundation",
    expected_product: str = "CATalyst",
) -> dict[str, str]:
    values = {
        key: str(metadata.get(key) or "").strip()
        for key in (
            "status",
            "signer_subject",
            "signer_thumbprint",
            "timestamp_subject",
            "timestamp_thumbprint",
            "product_name",
            "product_version",
            "file_version",
        )
    }
    if values["status"] != "Valid":
        raise VerificationError(
            f"Authenticode status is {values['status'] or 'missing'}"
        )
    if expected_publisher.casefold() not in values["signer_subject"].casefold():
        raise VerificationError("publisher is not SignPath Foundation")
    if not values["timestamp_subject"] or not values["timestamp_thumbprint"]:
        raise VerificationError("timestamp certificate is missing")
    if values["product_name"] != expected_product:
        raise VerificationError("product name does not match CATalyst")
    if values["product_version"] != expected_version:
        raise VerificationError("product version does not match the release")
    if values["file_version"] != f"{expected_version}.0":
        raise VerificationError("file version does not match the release")
    return values
```

Implement `build_evidence` with the exact JSON structure in the Interfaces block, setting `timestamp_status` to `Valid` only after Task 2's `signtool` gate succeeds.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_windows_authenticode.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/verify_windows_authenticode.py tests/test_windows_authenticode.py
git commit -m "feat: validate Windows Authenticode release evidence"
```

### Task 2: Real Windows Signature Collection and CLI Gate

**Files:**
- Modify: `scripts/verify_windows_authenticode.py`
- Modify: `tests/test_windows_authenticode.py`

**Interfaces:**
- Consumes: `--file`, `--expected-version`, and optional evidence/origin arguments.
- Produces: process exit 0 plus compact verified JSON on stdout; optional evidence file written atomically. Any unproved condition exits non-zero.
- Internal functions: `collect_powershell_metadata(path: Path) -> dict[str, str]`, `find_signtool() -> Path`, `run_signtool(path: Path, signtool: Path) -> None`, and `verify_file(path: Path, expected_version: str) -> dict[str, str]`.

- [ ] **Step 1: Add failing subprocess and CLI tests**

Add tests that import `json` and `subprocess`, import the module as `from scripts import verify_windows_authenticode as module`, mock `subprocess.run`, and prove:

```python
def test_verify_file_requires_powershell_and_signtool(monkeypatch, tmp_path):
    calls = []
    metadata = valid_metadata()

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0].lower().endswith("powershell.exe"):
            return subprocess.CompletedProcess(command, 0, json.dumps(metadata), "")
        return subprocess.CompletedProcess(command, 0, "Successfully verified", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(module, "find_signtool", lambda: Path("signtool.exe"))
    artifact = tmp_path / "Catalyst.exe"
    artifact.write_bytes(b"signed")
    result = module.verify_file(artifact, "1.3.17")
    assert result["status"] == "Valid"
    assert any("Get-AuthenticodeSignature" in part for part in calls[0])
    assert calls[1][1:4] == ["verify", "/pa", "/all"]
```

Also assert malformed PowerShell JSON, a PowerShell non-zero exit, absent `signtool`, and `signtool` non-zero exit raise `VerificationError`.

- [ ] **Step 2: Run the tests and observe missing interfaces**

Run: `python -m pytest tests/test_windows_authenticode.py -q`

Expected: failures report missing `verify_file`, `find_signtool`, and `collect_powershell_metadata`.

- [ ] **Step 3: Implement real collection and command-line parsing**

PowerShell must emit these fields without localized text parsing:

```powershell
$signature = Get-AuthenticodeSignature -LiteralPath $env:CATALYST_SIGNATURE_TARGET
$version = (Get-Item -LiteralPath $env:CATALYST_SIGNATURE_TARGET).VersionInfo
[pscustomobject]@{
  status = [string]$signature.Status
  signer_subject = [string]$signature.SignerCertificate.Subject
  signer_thumbprint = [string]$signature.SignerCertificate.Thumbprint
  timestamp_subject = [string]$signature.TimeStamperCertificate.Subject
  timestamp_thumbprint = [string]$signature.TimeStamperCertificate.Thumbprint
  product_name = [string]$version.ProductName
  product_version = [string]$version.ProductVersion
  file_version = [string]$version.FileVersion
} | ConvertTo-Json -Compress
```

`find_signtool` checks `shutil.which("signtool.exe")`, then chooses the highest versioned `x64\signtool.exe` beneath `C:\Program Files (x86)\Windows Kits\10\bin`. `run_signtool` executes:

```python
[str(signtool), "verify", "/pa", "/all", "/v", str(path)]
```

The CLI writes evidence through a temporary sibling followed by `Path.replace`, so an interrupted run cannot leave apparently valid partial evidence.

- [ ] **Step 4: Run focused tests and CLI help**

Run:

```powershell
python -m pytest tests/test_windows_authenticode.py -q
python scripts/verify_windows_authenticode.py --help
```

Expected: tests pass and help lists all evidence/origin arguments.

- [ ] **Step 5: Commit**

```powershell
git add scripts/verify_windows_authenticode.py tests/test_windows_authenticode.py
git commit -m "feat: add fail-closed Windows signature CLI"
```

### Task 3: Application Signing Stage and Signed ZIP

**Files:**
- Create: `tests/test_windows_release_signing.py`
- Modify: `.github/workflows/build-release.yml`

**Interfaces:**
- Consumes: unsigned `dist/Catalyst/Catalyst.exe` and SignPath configuration.
- Produces: verified signed `dist/Catalyst/Catalyst.exe`, its SignPath request ID, and a Windows ZIP created only after replacement.

- [ ] **Step 1: Write failing workflow-order tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-release.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_application_is_signed_and_verified_before_windows_zip_and_installer():
    workflow = workflow_text()
    upload = workflow.index("Upload unsigned CATalyst application for SignPath")
    sign = workflow.index("Sign CATalyst application with SignPath")
    verify = workflow.index("Verify signed CATalyst application")
    package = workflow.index("Package signed Windows zip")
    installer = workflow.index("Build Windows installer from signed application")
    assert upload < sign < verify < package < installer
    assert "catalyst-windows-application-v1" in workflow
    assert "c92b958760219087e01f8d67a1669ed57afe2627" in workflow
    assert "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow


def test_signpath_configuration_is_mandatory_and_origin_readable():
    workflow = workflow_text()
    assert "actions: read" in workflow
    assert "SIGNPATH_API_TOKEN is required" in workflow
    assert "SIGNPATH_ORGANIZATION_ID is required" in workflow
    assert "CATALYST_RELEASE_CHANNEL_TOKEN is required" in workflow
    assert "wait-for-completion-timeout-in-seconds: 7200" in workflow
```

- [ ] **Step 2: Run tests and observe missing signing stages**

Run: `python -m pytest tests/test_windows_release_signing.py -q`

Expected: failures report that the named SignPath stages are absent.

- [ ] **Step 3: Add credential preflight, application upload, signing, replacement, and verification**

Add `actions: read` to workflow permissions. Set job timeout to 360 minutes. Add a Windows preflight that throws for blank values rather than printing them. Resolve normalized version into step output `steps.release-version.outputs.version`.

Use these action inputs:

```yaml
- name: Upload unsigned CATalyst application for SignPath
  id: upload-unsigned-application
  if: matrix.os == 'windows-latest'
  uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
  with:
    name: catalyst-windows-application-${{ github.run_id }}-${{ github.run_attempt }}
    path: dist/Catalyst/Catalyst.exe
    archive: false

- name: Sign CATalyst application with SignPath
  id: sign-application
  if: matrix.os == 'windows-latest'
  uses: signpath/github-action-submit-signing-request@c92b958760219087e01f8d67a1669ed57afe2627
  with:
    api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
    organization-id: ${{ vars.SIGNPATH_ORGANIZATION_ID }}
    project-slug: catalyst
    signing-policy-slug: release-signing
    artifact-configuration-slug: catalyst-windows-application-v1
    github-artifact-id: ${{ steps.upload-unsigned-application.outputs.artifact-id }}
    wait-for-completion: true
    wait-for-completion-timeout-in-seconds: 7200
    output-artifact-directory: signed/application
    skip-decompress: true
    parameters: |
      version: "${{ steps.release-version.outputs.version }}"
```

Copy `signed/application/Catalyst.exe` over the unsigned bundle file, invoke `verify_windows_authenticode.py --file dist/Catalyst/Catalyst.exe --expected-version`, and move the Windows ZIP step after that verification. Keep all GitHub contexts in action inputs or `env`, not interpolated inside shell scripts.

- [ ] **Step 4: Run signing-order and existing workflow tests**

Run:

```powershell
python -m pytest tests/test_windows_release_signing.py tests/test_cross_platform_release_packaging.py tests/test_ci_security_workflows.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/build-release.yml tests/test_windows_release_signing.py
git commit -m "ci: sign CATalyst before Windows packaging"
```

### Task 4: Installer Signing, Final-Byte Manifest, and Evidence

**Files:**
- Modify: `.github/workflows/build-release.yml`
- Modify: `tests/test_windows_release_signing.py`
- Modify: `tests/test_app_update.py`

**Interfaces:**
- Consumes: installer built from the verified signed application.
- Produces: signed installer, checksum, Ed25519 updater manifests, and `windows-signature-v1.3.17.json` based on the signed bytes.

- [ ] **Step 1: Add failing installer-order and no-fallback tests**

```python
def test_installer_is_signed_before_hash_manifest_smoke_and_upload():
    workflow = workflow_text()
    build = workflow.index("Build Windows installer from signed application")
    upload_unsigned = workflow.index("Upload unsigned Windows installer for SignPath")
    sign = workflow.index("Sign Windows installer with SignPath")
    verify = workflow.index("Verify signed Windows installer and write evidence")
    checksum = workflow.index("Generate signed-installer checksum and update manifest")
    smoke = workflow.index("Smoke test signed Windows installer payload")
    upload_release = workflow.index("Upload signed Windows installer to Release")
    publish_channel = workflow.index("Publish verified public update channel")
    assert build < upload_unsigned < sign < verify < checksum < smoke
    assert smoke < upload_release < publish_channel


def test_release_has_no_unsigned_or_missing_token_fallback():
    workflow = workflow_text()
    assert "skipping public update channel publish" not in workflow.lower()
    assert "catalyst-windows-installer-v1" in workflow
    assert "windows-signature-$($env:RELEASE_REF).json" in workflow
    assert '"windows-signature-$($env:RELEASE_REF).json"' in workflow
```

Update the existing updater test to assert the manifest signing step occurs after `Verify signed Windows installer and write evidence`.

- [ ] **Step 2: Run tests and observe incorrect current order**

Run: `python -m pytest tests/test_windows_release_signing.py tests/test_app_update.py::TestAppUpdateFrontendAndReleaseWorkflow::test_release_workflow_publishes_signed_manifest_channel -q`

Expected: named stages are missing and the current checksum precedes installer signing.

- [ ] **Step 3: Split installer build from final-byte publication and add installer signing**

The build step ends immediately after renaming `Catalyst-Setup-vX.Y.Z.exe`. Upload that file with `archive: false`, submit it using `catalyst-windows-installer-v1`, and copy the returned installer over the unsigned file. Run the verifier with:

```powershell
python scripts/verify_windows_authenticode.py `
  --file "Catalyst-Setup-$($env:RELEASE_REF).exe" `
  --expected-version "$($env:RELEASE_VERSION)" `
  --evidence-output "windows-signature-$($env:RELEASE_REF).json" `
  --source-repository "$($env:GITHUB_REPOSITORY)" `
  --source-tag "$($env:RELEASE_REF)" `
  --source-commit "$($env:GITHUB_SHA)" `
  --workflow-run-url "$($env:GITHUB_SERVER_URL)/$($env:GITHUB_REPOSITORY)/actions/runs/$($env:GITHUB_RUN_ID)" `
  --application-signing-request-id "$($env:APPLICATION_SIGNING_REQUEST_ID)" `
  --installer-signing-request-id "$($env:INSTALLER_SIGNING_REQUEST_ID)"
```

Expose GitHub and SignPath outputs through the step's `env`. Only the next step computes SHA-256 and calls `scripts/sign_update_manifest.py`. Add evidence JSON to both Windows asset arrays and rename steps exactly as the tests expect.

- [ ] **Step 4: Run targeted workflow/update tests**

Run:

```powershell
python -m pytest tests/test_windows_release_signing.py tests/test_app_update.py tests/test_cross_platform_release_packaging.py tests/test_ci_security_workflows.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/build-release.yml tests/test_windows_release_signing.py tests/test_app_update.py
git commit -m "ci: sign and attest Windows installer bytes"
```

### Task 5: Signed Payload, Installed Executable, and Defender Gates

**Files:**
- Modify: `.github/workflows/build-release.yml`
- Modify: `tests/test_windows_release_signing.py`

**Interfaces:**
- Consumes: signed installer and signed bundle application.
- Produces: proof that the installer preserves the signed application and that Defender reports no threat.

- [ ] **Step 1: Add failing smoke-gate assertions**

```python
def test_signed_installer_smoke_verifies_installed_signature_hash_and_defender():
    workflow = workflow_text()
    smoke = workflow.split("Smoke test signed Windows installer payload", 1)[1]
    assert "verify_windows_authenticode.py" in smoke
    assert "installed Catalyst.exe hash does not match signed bundle" in smoke
    assert "MpCmdRun.exe" in smoke
    assert "Defender scan failed" in smoke
```

- [ ] **Step 2: Run the test and observe the missing gates**

Run: `python -m pytest tests/test_windows_release_signing.py::test_signed_installer_smoke_verifies_installed_signature_hash_and_defender -q`

Expected: assertion fails because the current installer smoke checks version and launch but not Authenticode/hash/Defender.

- [ ] **Step 3: Extend the signed installer smoke**

After isolated install, run the verifier on `$installedExe`, compute SHA-256 for both `dist/Catalyst/Catalyst.exe` and `$installedExe`, and throw the exact test marker on mismatch. Locate Defender with:

```powershell
$defender = Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
if (-not (Test-Path -LiteralPath $defender)) {
  throw "Defender scan failed: MpCmdRun.exe is unavailable"
}
& $defender -Scan -ScanType 3 -File $installer
if ($LASTEXITCODE -ne 0) { throw "Defender scan failed for installer with code $LASTEXITCODE" }
& $defender -Scan -ScanType 3 -File $installedExe
if ($LASTEXITCODE -ne 0) { throw "Defender scan failed for installed application with code $LASTEXITCODE" }
```

Keep the existing fresh install, existing-install upgrade, shortcut target, version, and uninstall checks.

- [ ] **Step 4: Run workflow packaging tests**

Run: `python -m pytest tests/test_windows_release_signing.py tests/test_cross_platform_release_packaging.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/build-release.yml tests/test_windows_release_signing.py
git commit -m "test: verify signed Windows installation end to end"
```

### Task 6: Code-Signing Policy, Privacy Disclosure, and Splash Correction

**Files:**
- Create: `docs/CODE_SIGNING_POLICY.md`
- Create: `docs/PRIVACY.md`
- Create: `tests/test_code_signing_policy.py`
- Modify: `README.md`
- Modify: `installer.iss`

**Interfaces:**
- Consumes: SignPath Foundation OSS policy requirements.
- Produces: public policy links required before SignPath enrollment and accurate third-party binary guidance.

- [ ] **Step 1: Write failing documentation-policy tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_signpath_policy_and_privacy_are_publicly_linked():
    policy = (ROOT / "docs" / "CODE_SIGNING_POLICY.md").read_text(encoding="utf-8")
    privacy = (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        "Free code signing provided by SignPath.io, certificate by SignPath Foundation"
        in policy
    )
    assert "Authors and committers" in policy
    assert "Reviewers" in policy
    assert "Approvers" in policy
    assert "Dexie" in privacy and "Sage" in privacy and "GitHub" in privacy
    assert "analytics" in privacy.lower() and "telemetry" in privacy.lower()
    assert "Code signing policy" in readme
    assert "docs/CODE_SIGNING_POLICY.md" in readme


def test_installer_does_not_claim_cat_certificate_for_upstream_splash():
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert (
        "same code-signing cert used for Catalyst.exe and splash.exe" not in installer
    )
    assert "Do not sign upstream splash.exe with the CATalyst certificate" in installer
```

- [ ] **Step 2: Run tests and observe missing documents/stale comment**

Run: `python -m pytest tests/test_code_signing_policy.py -q`

Expected: file-not-found failure for `docs/CODE_SIGNING_POLICY.md`.

- [ ] **Step 3: Add exact public policy content and links**

The code-signing policy must state the required SignPath sentence, link the public repository, define authors/committers as maintainers with write/maintain/admin permission, reviewers as maintainers authorized to approve pull requests, approvers as owners authorized in the SignPath organization, and state that only project-built CATalyst binaries are signed.

The privacy document must state that CATalyst has no CATalyst-operated analytics or telemetry service and describe these data paths accurately:

- Sage JSON-RPC on loopback port 9257 for wallet reads and user-requested signing/spend operations;
- Dexie APIs for offer discovery/publication/cancellation status;
- Splash peer-to-peer offer publication when the user enables it;
- TibetSwap, Spacescan, and Coinset for market/on-chain information;
- GitHub release endpoints for update metadata and downloads; and
- local files in `%APPDATA%\Catalyst` for settings, database, logs, and diagnostics.

Link both documents from a new README `## Code signing policy and privacy` section. Correct lines 10-13 of `installer.iss` to say the final installer and CATalyst-owned executable are signed, while upstream Splash is not signed with CATalyst's entitlement.

- [ ] **Step 4: Run documentation and release tests**

Run: `python -m pytest tests/test_code_signing_policy.py tests/test_cross_platform_release_packaging.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add docs/CODE_SIGNING_POLICY.md docs/PRIVACY.md README.md installer.iss tests/test_code_signing_policy.py
git commit -m "docs: publish CATalyst code-signing policy"
```

### Task 7: Source Repository Verification and Pull Request

**Files:**
- Modify only if verification exposes a defect: files from Tasks 1-6 and their tests.

**Interfaces:**
- Produces: reviewable PR from `codex/signpath-release-signing` to `main` with a green clean-checkout-equivalent test result.

- [ ] **Step 1: Run focused release verification**

```powershell
python -m pytest tests/test_windows_authenticode.py tests/test_windows_release_signing.py tests/test_code_signing_policy.py tests/test_app_update.py tests/test_cross_platform_release_packaging.py tests/test_ci_security_workflows.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the full source suite**

```powershell
Set-Location tests
python -m pytest
```

Expected baseline: 5,335 passed, 23 skipped; any changed count must have an explained new test delta and zero failures.

- [ ] **Step 3: Run static release checks**

```powershell
Set-Location ..
git diff --check
python -m ruff check scripts/verify_windows_authenticode.py tests/test_windows_authenticode.py tests/test_windows_release_signing.py tests/test_code_signing_policy.py
python -m bandit -q scripts/verify_windows_authenticode.py
```

Expected: all commands exit 0.

- [ ] **Step 4: Push and open the protected-main PR**

```powershell
git push -u github codex/signpath-release-signing
gh pr create --repo catalystxch/catalyst-bot --base main --head codex/signpath-release-signing --title "Sign and verify Windows releases with SignPath" --body-file docs/superpowers/specs/2026-08-28-signpath-windows-release-signing-design.md
```

- [ ] **Step 5: Wait for required checks and merge only when green**

Run:

```powershell
$sourcePr = gh pr view codex/signpath-release-signing --repo catalystxch/catalyst-bot --json number --jq .number
if (-not $sourcePr) { throw "source signing PR number was not found" }
gh pr checks $sourcePr --repo catalystxch/catalyst-bot --watch
if ($LASTEXITCODE -ne 0) { throw "source signing PR checks failed" }
gh pr merge $sourcePr --repo catalystxch/catalyst-bot --squash --delete-branch
```

Expected: protected-branch checks pass and `main` contains the signing pipeline and policies. If review or checks fail, amend on the feature branch and repeat Steps 1-5.

### Task 8: SignPath Foundation Enrollment and GitHub Configuration

**Files:**
- No repository file changes unless SignPath's generated artifact configuration requires a reviewed metadata restriction correction.

**Interfaces:**
- Consumes: merged public policy, public repository, protected release workflow, and SignPath Foundation application.
- Produces: active SignPath project, GitHub App, application and installer configurations, API token, organization variable, and manual approver.

- [ ] **Step 1: Assemble the application evidence without submitting it**

Record these values in the action-time confirmation message:

- repository: `https://github.com/catalystxch/catalyst-bot`;
- license: MIT;
- product: CATalyst, a Chia automated market-making desktop application;
- Windows release page: `https://github.com/Lowestofttim/catalyst-releases/releases`;
- code-signing policy: merged `docs/CODE_SIGNING_POLICY.md` URL;
- privacy policy: merged `docs/PRIVACY.md` URL;
- requested publisher: SignPath Foundation; and
- project/policy/configuration slugs from Global Constraints.

- [ ] **Step 2: Ask for action-time confirmation immediately before application submission**

Expected confirmation question: `Submit the SignPath Foundation open-source signing application now using the public CATalyst repository, policy, privacy statement, and release URLs listed above?`

Do not submit, install the GitHub App, create external credentials, or communicate with SignPath until the user confirms this exact action.

- [ ] **Step 3: Submit the application and preserve the confirmation/reference**

Use the user's SignPath account in the visible browser. Do not save passwords or MFA recovery data. Record the submission reference and status in the task commentary, not in the repository.

- [ ] **Step 4: After acceptance, configure the exact project and two artifact configurations**

Application configuration enforces `Catalyst.exe`, product `CATalyst`, original filename `Catalyst.exe`, and the `version` parameter. Installer configuration enforces the `Catalyst-Setup-v*.exe` filename pattern, product/version metadata, and Authenticode signing of only the outer installer PE. Both use `release-signing`, GitHub.com trusted build verification, origin repository restriction, and the SignPath-required manual approver.

- [ ] **Step 5: Install the SignPath GitHub App and store only the required GitHub settings**

Create `SIGNPATH_API_TOKEN` as a repository secret and `SIGNPATH_ORGANIZATION_ID` as a repository variable. Confirm existing `CATALYST_UPDATE_SIGNING_KEY_B64` and `CATALYST_RELEASE_CHANNEL_TOKEN` are present without displaying values:

```powershell
gh secret list --repo catalystxch/catalyst-bot
gh variable list --repo catalystxch/catalyst-bot
```

Expected names are visible; secret values never appear.

### Task 9: v1.3.17 Signed Release and Independent Proof

**Files:**
- No source change unless a verified release-only defect requires a new test/fix and a replacement version greater than v1.3.17.

**Interfaces:**
- Consumes: merged source plan, completed website verification plan, active SignPath setup, and release secrets.
- Produces: signed v1.3.17 artifacts in both release repositories and byte-for-byte independent local proof.

- [ ] **Step 1: Verify tag absence and exact main commit**

```powershell
gh release view v1.3.17 --repo catalystxch/catalyst-bot
gh release view v1.3.17 --repo Lowestofttim/catalyst-releases
git fetch github main --tags
git rev-parse github/main
git status --short
```

Expected: both release lookups report not found and the release checkout is clean. If the tag exists, stop rather than overwrite it.

- [ ] **Step 2: Create and push the release tag**

```powershell
git tag -a v1.3.17 github/main -m "CATalyst v1.3.17"
git push github v1.3.17
```

- [ ] **Step 3: Watch both SignPath requests and approve through the visible SignPath UI**

Run `gh run list --repo catalystxch/catalyst-bot --workflow "Build Release" --limit 1` and watch the returned run. Approve only request IDs originating from the v1.3.17 workflow and verify both artifact names before approval.

- [ ] **Step 4: Verify GitHub release assets and embedded signatures**

Download the source and public-channel installer plus evidence to a new `New-Item -ItemType Directory` temporary directory. Verify SHA-256 equality, updater-manifest signature, evidence fields, and:

```powershell
Get-AuthenticodeSignature -LiteralPath .\Catalyst-Setup-v1.3.17.exe | Format-List Status,StatusMessage,SignerCertificate,TimeStamperCertificate
python scripts/verify_windows_authenticode.py --file .\Catalyst-Setup-v1.3.17.exe --expected-version 1.3.17
```

Expected: `Status: Valid`, SignPath Foundation signer, timestamp certificate present, and verifier exit 0.

- [ ] **Step 5: Complete the website-plan publication check, then download from the website in a fresh browser session**

The website plan must report schema version 2, valid publisher metadata, and an enabled v1.3.17 Windows button. Download from `https://catalystxch.com`, not from a copied signed release-asset URL. Re-run SHA-256, Defender, and Authenticode checks on that browser download.

- [ ] **Step 6: Install and launch the website download**

Install into a temporary current-user directory, verify the installed `Catalyst.exe` signature/version/hash, then launch it. Confirm a CATalyst desktop interface opens and that it does not open a raw `/api/safety/status` JSON page. Do not start a bot, coin prep, offer, or wallet action as part of release installation proof.

- [ ] **Step 7: Record the release acceptance checkpoint**

Report the source commit, workflow run, both SignPath request IDs, both release URLs, website metadata version, installer SHA-256, publisher, Defender result, install/launch result, and any remaining Windows reputation warning. Do not claim that signing guarantees immediate SmartScreen reputation.
