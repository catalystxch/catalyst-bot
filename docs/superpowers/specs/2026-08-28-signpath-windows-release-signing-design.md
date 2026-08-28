# SignPath-Backed Windows Release Signing Design

**Date:** 2026-08-28

**Status:** Proposed for implementation

**Repositories:** `catalystxch/catalyst-bot`, `Lowestofttim/catalyst-releases`, and `Lowestofttim/catalystxch`

## Problem statement

CATalyst's Windows release pipeline currently publishes an unsigned Inno Setup
installer containing an unsigned `Catalyst.exe`. The v1.3.16 public installer was
downloaded from the website and independently reproduced on a second local PC:
Windows invoked SmartScreen, the installer did not continue, and the installed
application remained v1.3.13. `Get-AuthenticodeSignature` reports `NotSigned`
for both v1.3.15 and v1.3.16. Microsoft Defender did not identify malware in
either file, so this is a missing publisher identity and trust-chain defect in
the CATalyst release process, not evidence of malware.

The website also describes the current Windows download as a "signed public
installer channel" even though the artifact is unsigned. That claim must become
evidence-driven.

## Goals

- Preserve the direct website download and the existing Inno Setup installer.
- Authenticode-sign CATalyst's own Windows executable before it is placed in the
  installer.
- Authenticode-sign the final installer after Inno Setup packages the signed
  application.
- Use SignPath Foundation's free open-source signing service; Windows will show
  `SignPath Foundation` as the verified publisher.
- Fail closed: an unsigned, invalidly signed, incorrectly signed, or unverified
  Windows artifact must never reach either GitHub release channel or the website.
- Generate checksums and update manifests from the final signed installer bytes,
  never from the unsigned precursor.
- Preserve current packaged application, installer payload, upgrade, and updater
  tests.
- Independently download and verify the website artifact after publication.

## Non-goals

- This work does not buy or manage a private commercial certificate.
- It does not promise that every Windows reputation warning disappears
  immediately. Authenticode proves publisher identity and file integrity;
  reputation systems may still apply additional policy.
- It does not bypass SmartScreen, Smart App Control, antivirus, or browser
  security controls.
- It does not sign third-party executables or libraries with the CATalyst
  project's signing entitlement.
- It does not replace Inno Setup with MSI or MSIX in this release.
- It does not change CATalyst trading, wallet, coin-prep, offer, or risk logic.

## Chosen signing service and identity

The project will apply for SignPath Foundation Open Source Code Signing. The
repository is public, MIT-licensed, actively maintained, and already publishes
Windows releases, satisfying the basic project-shape requirements. Acceptance
remains an external SignPath decision.

The SignPath configuration will use these stable identifiers:

| Setting | Value |
|---|---|
| Project slug | `catalyst` |
| Signing policy slug | `release-signing` |
| Application artifact configuration | `catalyst-windows-application-v1` |
| Installer artifact configuration | `catalyst-windows-installer-v1` |
| Allowed repository | `https://github.com/catalystxch/catalyst-bot` |
| Allowed release origin | version tags reachable from protected `main` |
| Certificate publisher | `SignPath Foundation` |

The project will install the SignPath GitHub App for the source repository and
use GitHub.com as the SignPath trusted build system. The GitHub workflow will
submit only GitHub-hosted-runner artifacts so SignPath can verify their origin.
Every release signing request will require the manual approval mandated by the
SignPath Foundation open-source policy.

GitHub configuration will contain:

- repository secret `SIGNPATH_API_TOKEN`;
- repository variable `SIGNPATH_ORGANIZATION_ID`;
- the existing `CATALYST_UPDATE_SIGNING_KEY_B64` secret for the separate Ed25519
  updater-manifest signature; and
- the existing `CATALYST_RELEASE_CHANNEL_TOKEN`, which becomes mandatory for a
  public release rather than silently skipping the Windows public channel.

No Authenticode private key or certificate file will be stored in GitHub, the
repository, a build artifact, or a developer machine.

The workflow grants `actions: read` so the SignPath connector can inspect the
originating GitHub job, retains only the minimum release-write permission, and
keeps `persist-credentials: false` on checkout. The Windows job timeout becomes
360 minutes and each signing action receives a 7,200-second completion timeout,
allowing time for the two required manual approvals without converting a delay
into an unsigned fallback.

## What is signed

### CATalyst-owned application

`dist/Catalyst/Catalyst.exe` is signed first. Its PE metadata must identify the
product as CATalyst and carry the tag-derived version before submission. The
SignPath artifact configuration will enforce the filename, product metadata,
and version parameter.

### Final installer

`Catalyst-Setup-vX.Y.Z.exe` is built from the bundle containing the already
signed `Catalyst.exe`, then submitted as a separate PE artifact and signed. A
second request is required because Inno Setup is not treated as a supported
deep-signable container in this design: changing `Catalyst.exe` after packaging
would not change the copy already embedded in the installer.

### Third-party files

Third-party DLLs and executables remain untouched. In particular, an optional
upstream `splash.exe` must not be signed with the SignPath Foundation certificate
assigned to CATalyst. If present, its provenance, hash, and existing upstream
signature status are recorded and checked separately. The stale installer
comment that says `splash.exe` should receive CATalyst's certificate will be
corrected.

## Release data flow

The Windows matrix job in `.github/workflows/build-release.yml` will execute this
ordered pipeline:

1. Check out the tag, synchronize `_version.py` and Windows version metadata,
   install dependencies, and run `python build.py` on `windows-latest`.
2. Run the current packaged Sage RPC, API runtime, and interrupted-publication
   recovery smoke tests against the unsigned build. These tests validate the
   generated application before consuming signing approvals.
3. Upload only `dist/Catalyst/Catalyst.exe` as the application signing input.
4. Submit application signing request 1 through
   `signpath/github-action-submit-signing-request` v2 pinned to commit
   `c92b958760219087e01f8d67a1669ed57afe2627`. Wait for approval and completion,
   then replace the unsigned file with the returned signed file.
5. Run the Windows signature verifier against the returned `Catalyst.exe`. It
   must prove a valid Authenticode signature, the expected SignPath Foundation
   publisher, the expected product name and version, and successful Windows
   trust-policy verification.
6. Create `Catalyst-windows-vX.Y.Z.zip` from the bundle only after the signed
   application has replaced the unsigned file.
7. Build `Catalyst-Setup-vX.Y.Z.exe` with Inno Setup from that signed bundle.
8. Upload the final unsigned installer as the installer signing input.
9. Submit installer signing request 2 using artifact configuration
   `catalyst-windows-installer-v1`. Wait for approval and completion, then replace
   the unsigned installer with the returned signed installer.
10. Verify the installer signature and extract/install it in an isolated
    directory. Verify the installed `Catalyst.exe` signature again, prove its
    hash matches the signed application placed into the bundle, and run the
    existing installer payload and existing-install upgrade smokes.
11. Run Defender scanning on the signed installer and installed application on
    the GitHub-hosted Windows runner. A detected threat fails the release.
12. Generate the installer SHA-256 sidecar, signed update manifest, and signature
    evidence JSON from the final signed installer bytes.
13. Upload the signed Windows ZIP, installer, checksum, updater manifests, and
    signature evidence to the draft source release and to the public release
    channel.
14. Publish the source release only after the complete Windows and Linux matrix
    succeeds. If either SignPath request is rejected, times out, returns the
    wrong artifact, or fails verification, the source release remains draft and
    no Windows artifact is uploaded to the public channel.

`actions/upload-artifact` v7 will be pinned to commit
`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`. Any required artifact download action
will use `actions/download-artifact` v8 pinned to
`3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`. All other third-party actions remain
pinned to immutable commits.

## Verification implementation

A new script, `scripts/verify_windows_authenticode.py`, will provide a testable
release gate. On Windows it will call both:

- PowerShell `Get-AuthenticodeSignature`, serialized as JSON; and
- Windows SDK `signtool verify /pa /all /v`.

The script will reject:

- missing files;
- `NotSigned`, `UnknownError`, `HashMismatch`, `NotTrusted`, or any status other
  than `Valid`;
- a signer subject that is not `SignPath Foundation`;
- a missing or invalid trusted timestamp;
- a product name other than `CATalyst`;
- a PE product/file version different from the release tag; or
- a `signtool` non-zero result.

The pure validation portion will accept captured JSON/metadata as input so its
success and failure paths can be unit-tested on non-Windows development hosts.
The real Windows CI gate cannot be mocked and must run against the returned
signed files.

The workflow will emit `windows-signature-vX.Y.Z.json` with:

- schema version;
- artifact name and byte length;
- SHA-256;
- Authenticode status;
- signer subject and certificate thumbprint;
- timestamp signer and timestamp status;
- product/file version;
- source repository, source tag, and source commit; and
- GitHub workflow run URL and SignPath signing-request IDs.

This evidence describes a verification result; it is not a substitute for the
Authenticode signature embedded in the PE file.

## Website publication gate

The website repository will stop treating the newest public-channel release as
downloadable merely because an `.exe` and `.sha256` asset exist.

`scripts/sync_release_metadata.py` in `Lowestofttim/catalystxch` will require the
matching signature evidence asset, require its SHA-256 to equal the installer
sidecar and downloaded installer, and invoke `osslsigncode verify` against the
downloaded PE on the Ubuntu website workflow. The expected signer must be
`SignPath Foundation`. The website metadata schema will advance to version 2 so
verification is stored per asset. Only after all checks pass may the generated
Windows installer asset set:

- `download_enabled: true`;
- `verification.authenticode_status: valid`; and
- `verification.publisher: SignPath Foundation`.

If any check fails, the sync workflow leaves the previously verified Windows
release metadata in place and reports the candidate as unavailable; it must not
advertise or link the unverified candidate. Static HTML fallbacks and
JavaScript-rendered content use the same verified metadata.

The false unconditional sentence "Windows uses the signed public installer
channel" will be replaced with evidence-driven language. The download card may
say "Authenticode signed — verified publisher: SignPath Foundation" only when
the verified metadata fields are present. It will not claim that Windows will
never show a reputation warning.

## Code-signing policy and privacy documentation

The source repository and website will expose a `Code signing policy` link. The
policy will include the required statement:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

Roles are defined by repository permissions:

- authors/committers: maintainers with write, maintain, or admin permission on
  `catalystxch/catalyst-bot`;
- reviewers: maintainers authorized to approve pull requests; and
- signing approvers: owners authorized to approve release requests in the
  project's SignPath organization.

The policy will link to a CATalyst privacy statement that accurately lists the
local Sage RPC connection and user-requested network services used by the app,
including Dexie, Splash, TibetSwap, Spacescan, Coinset, and the GitHub release
channel. It will state that CATalyst does not add an analytics or telemetry
service, while avoiding the inaccurate claim that a networked trading app never
transfers data.

## Test-driven implementation

Implementation starts with focused failing regression tests covering:

1. the release workflow contains two ordered SignPath requests;
2. the Windows ZIP is created after application signing;
3. the installer is built after application verification and signed before any
   checksum, manifest, smoke, or upload step;
4. both release uploads consume the signed installer path;
5. missing SignPath/public-channel configuration fails rather than skips;
6. the Authenticode verifier rejects every invalid status, wrong signer, wrong
   version, missing timestamp, and hash mismatch;
7. the signature evidence schema is complete and tied to the exact final bytes;
8. the website rejects absent, stale, hash-mismatched, wrongly signed, or invalid
   evidence; and
9. the website never renders a signed claim without verified metadata.

Each test must be observed failing for the intended reason before the smallest
implementation change is made. Targeted release tests run first, followed by the
full source and website suites and a clean Windows build.

## Release acceptance

A new version may be tagged only after SignPath accepts the project and the
required GitHub App, secret, variable, policy, and artifact configurations are
active. Submitting the SignPath Foundation application is an external
representational action and requires the maintainer's confirmation immediately
before submission.

The release is accepted only when all of the following evidence exists:

- full source tests and website tests pass from clean checkouts;
- the GitHub Windows build and both manual SignPath approvals complete;
- `Get-AuthenticodeSignature` and `signtool` report valid signatures for the
  downloaded installer and its installed `Catalyst.exe`;
- signer identity is `SignPath Foundation` and versions match the tag;
- checksums and updater-manifest signature verify against the downloaded bytes;
- Defender reports no threat;
- silent fresh install, normal launch, in-app upgrade, existing-install upgrade,
  and uninstall smokes pass;
- the published website metadata and visible version match the public release;
- a new browser session on this PC downloads the website asset, not a stale
  signed URL; and
- the downloaded website file is byte-for-byte the signed artifact that passed
  CI and launches the CATalyst interface rather than a raw local API endpoint or
  diagnostics page.

Only then is the release described as fixed and ready for testing on the other
PC.

## Failure and rollback behavior

- A SignPath outage, rejection, timeout, or approval delay pauses publication;
  it does not fall back to unsigned artifacts.
- A signature verification failure preserves all logs and evidence, keeps the
  source release draft, and prevents public-channel upload.
- If the website independently rejects a candidate, it keeps the previous
  verified Windows release visible and labels the candidate unavailable.
- If a published installer is later revoked or found invalid, the public release
  is marked unavailable and removed from the website download selection; the
  source tag remains for audit history.
- Existing installed CATalyst user data under `%APPDATA%\Catalyst` is not
  deleted, reset, or migrated by signing changes.

## External references

- SignPath Foundation terms: <https://signpath.org/terms.html>
- SignPath project configuration: <https://docs.signpath.io/projects>
- SignPath artifact configuration: <https://docs.signpath.io/artifact-configuration/>
- SignPath GitHub trusted build integration:
  <https://docs.signpath.io/trusted-build-systems/github>
- SignPath GitHub action:
  <https://github.com/SignPath/github-action-submit-signing-request>
- Microsoft Smart App Control FAQ:
  <https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions>
