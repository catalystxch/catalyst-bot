# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

This policy applies to Windows releases of [CATalyst](https://github.com/catalystxch/catalyst-bot), an MIT-licensed Chia automated market-making desktop application.

## Signed artifacts

The release workflow may sign only artifacts built from CATalyst source and build scripts in this repository:

- the CATalyst-owned `Catalyst.exe` application; and
- the final `Catalyst-Setup-vX.Y.Z.exe` Windows installer.

The installer can contain unsigned upstream open-source components. CATalyst's certificate must not be applied to those components. In particular, the optional upstream `splash.exe` binary from the Dexie Splash project is not a CATalyst-built binary and is never signed with CATalyst's SignPath entitlement.

The GitHub Actions release workflow uploads each CATalyst-owned artifact to SignPath directly from a GitHub-hosted runner. SignPath verifies its build origin. The workflow verifies the returned Authenticode publisher, timestamp, product, version, and Windows policy before packaging or publication. Checksums and updater manifests are generated only from the final signed installer bytes.

## Team roles

The current role assignments are:

- **Authors and committers:** [grigb](https://github.com/grigb), [dkackman](https://github.com/dkackman), [BrandtH22](https://github.com/BrandtH22), and [Lowestofttim](https://github.com/Lowestofttim). These are direct repository collaborators with write or administration permission.
- **Reviewers:** [dkackman](https://github.com/dkackman) and [Lowestofttim](https://github.com/Lowestofttim). They are repository administrators authorized to review pull requests and release-workflow changes.
- **Approver:** [Lowestofttim](https://github.com/Lowestofttim). The approver is authorized in the SignPath organization to approve or reject CATalyst release-signing requests.

Role membership is determined by the repository's direct collaborator permissions and the corresponding SignPath organization membership. Changes from people outside the committer group require review by a reviewer. Release signing uses a manual approval for every signing request.

## Release controls

- Release signing is restricted to the public `catalystxch/catalyst-bot` repository and its GitHub-hosted build origin.
- The signing policy is `release-signing`; the workflow specifies versioned application and installer artifact configurations explicitly.
- A wrong or missing signature, publisher, timestamp, product, version, origin, request ID, checksum, or Defender result fails the workflow. There is no unsigned Windows publication fallback.
- Signing keys remain in SignPath's managed service and are not stored in the repository or GitHub Actions.
- Every published Windows installer is accompanied by a SHA-256 sidecar, signed updater manifest, and machine-readable signature evidence tied to the exact installer bytes and workflow run.

Security issues should be reported using [CATalyst's security policy](../SECURITY.md), not a public issue.

## Privacy

CATalyst's data handling and network services are described in the [privacy policy](PRIVACY.md).
