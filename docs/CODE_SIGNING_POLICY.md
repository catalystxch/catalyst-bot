# Code signing policy

CATalyst's optional signed Windows release path uses [SignPath.io](https://about.signpath.io/) with a certificate from [SignPath Foundation](https://signpath.org/). The project's Foundation application was not approved. CATalyst can publish an explicitly verified unsigned Windows release, including on the stable channel, with clear website labelling and a signed update manifest. The current public download remains an unsigned beta until a separate release decision.

This policy applies to Windows releases of [CATalyst](https://github.com/catalystxch/catalyst-bot), an MIT-licensed Chia automated market-making desktop application.

## Signed artifacts

The release workflow may sign only artifacts built from CATalyst source and build scripts in this repository:

- the CATalyst-owned `Catalyst.exe` application; and
- the final `Catalyst-Setup-vX.Y.Z.exe` Windows installer.

The installer can contain unsigned upstream open-source components. CATalyst's certificate must not be applied to those components. In particular, the optional upstream `splash.exe` binary from the Dexie Splash project is not a CATalyst-built binary and is never signed with CATalyst's SignPath entitlement.

The GitHub Actions signed-release workflow uploads each CATalyst-owned artifact to SignPath directly from a GitHub-hosted runner. SignPath verifies its build origin. The workflow verifies the returned Authenticode publisher, timestamp, product, version, and Windows policy before packaging or publication. In that signed-release workflow, checksums and updater manifests are generated only from the final signed installer bytes.

## Unsigned beta artifacts

An unsigned Windows beta may be offered while code signing is unavailable, but it must be clearly distinguished from a signed release:

- the download must use the exact installer URL in the official CATalyst GitHub release repository;
- the website must label it **Unsigned beta**, display its exact SHA-256 digest, and explain the expected blue Windows SmartScreen unrecognized-app warning;
- the website must never show a publisher or signature-verification claim for an unsigned build; and
- users must be told not to continue if Windows reports malware or potentially unwanted software rather than the ordinary unrecognized-app warning.

An unsigned beta does not receive or imitate the CATalyst signing identity. Its availability is an explicit distribution decision, not a fallback inside the signed-release workflow.

## Unsigned stable artifacts

An unsigned stable Windows installer is a separate manual release path. It requires a public, non-prerelease source tag on protected `main`; exact-tag build and install checks; `NotSigned` status for both the installer and installed CATalyst application; matching SHA-256 sidecar; Microsoft Defender scan; packaged Sage, API, desktop and upgrade smoke checks; and an Ed25519-signed `stable` update manifest bound to the source commit and final installer bytes. The staged release is uploaded as a draft, then published as the immutable latest non-prerelease release only after every check passes. It carries no `windows-signature-*.json` asset or verified-publisher claim.

The website enables that Windows link only after independently verifying the public release state, exact downloaded bytes, GitHub digest, sidecar, signed stable manifest and absence of an Authenticode signature. It labels the download **Unsigned Windows release**, states that there is no verified publisher certificate, displays the exact SHA-256 and explains the ordinary SmartScreen warning. Users should check the app name and digest before choosing More info and Run anyway. Smart App Control or an organization policy may provide no continuation option; users should follow those controls and stop on malware or potentially unwanted app warnings. The signed path remains available as an explicit alternative when a signing identity exists.

## Team roles

The current role assignments are:

- **Authors and committers:** [grigb](https://github.com/grigb), [dkackman](https://github.com/dkackman), [BrandtH22](https://github.com/BrandtH22), and [Lowestofttim](https://github.com/Lowestofttim). These are direct repository collaborators with write or administration permission.
- **Reviewers:** [dkackman](https://github.com/dkackman) and [Lowestofttim](https://github.com/Lowestofttim). They are repository administrators authorized to review pull requests and release-workflow changes.
- **Approver:** [Lowestofttim](https://github.com/Lowestofttim). The approver is authorized in the SignPath organization to approve or reject CATalyst release-signing requests.

Role membership is determined by the repository's direct collaborator permissions and the corresponding SignPath organization membership. Changes from people outside the committer group require review by a reviewer. Release signing uses a manual approval for every signing request.

## Release controls

- Release signing is restricted to the public `catalystxch/catalyst-bot` repository and its GitHub-hosted build origin.
- The signing policy is `release-signing`; the workflow specifies versioned application and installer artifact configurations explicitly.
- A wrong or missing signature, publisher, timestamp, product, version, origin, request ID, checksum, or Defender result fails the signed-release workflow. That workflow has no unsigned fallback.
- The website may separately expose an explicitly approved unsigned beta or stable release only when the asset name, official GitHub release URL, actual bytes, lowercase SHA-256 digest, sidecar and signed update manifest match the appropriate channel contract. If signing evidence exists but fails validation, the website must fail closed rather than relabel the artifact as unsigned.
- Signing keys remain in SignPath's managed service and are not stored in the repository or GitHub Actions.
- Every signed Windows installer is accompanied by a SHA-256 sidecar, signed updater manifest, and machine-readable signature evidence tied to the exact installer bytes and workflow run. An unsigned installer is accompanied by its SHA-256 sidecar and signed updater manifest, and carries no signature evidence or verified-publisher claim.

Security issues should be reported using [CATalyst's security policy](../SECURITY.md), not a public issue.

## Privacy

CATalyst's data handling and network services are described in the [privacy policy](PRIVACY.md).
