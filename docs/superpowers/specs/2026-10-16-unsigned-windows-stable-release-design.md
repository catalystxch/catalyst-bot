# Unsigned Windows stable release design

## Intent and scope

CATalyst's operator has chosen an unsigned Windows installer for the eventual general public release. No Authenticode certificate or signing service is required. The release must describe its unsigned status accurately and use the existing project-signed update manifest, SHA-256 sidecar, Defender scan, packaged smoke checks, and exact-tag release controls. This design changes the release and website channels; it does not declare the current candidate generally ready or authorize publishing it.

The current opt-in unsigned beta remains available under its existing prerelease channel until a separate final-candidate acceptance review has passed. Dexie remains the offer marketplace. Splash remains an optional offer broadcaster, off by default. Website copy must retain “New Dexie only beta testing” until the general-release decision is actually made.

## Existing behavior to preserve

- `publish-unsigned-windows-beta.yml` builds from an exact source tag on protected main, checks its public prerelease identity, builds the installer, proves it is `NotSigned`, verifies the SHA-256 sidecar, scans with Defender, installs and smoke-tests the packaged app, signs an Ed25519 beta update manifest, and publishes an immutable prerelease in the release-channel repository.
- The stable updater accepts only a `stable` manifest from the pinned GitHub release channel, verifies its Ed25519 signature and the exact installer SHA-256 before installation. It does not require Authenticode.
- The website currently verifies signed stable assets against SignPath Foundation evidence and permits an explicitly verified unsigned **beta**. Invalid signing evidence fails closed. Its protected-main metadata workflow checks and deploys the rendered page.
- `build-release.yml` currently triggers on all version tags and requires SignPath configuration. Its automatic trigger must not cause an expected unsigned stable tag to fail or silently turn a failed signed build into an unsigned artifact.

## Release path

Add a dedicated, manual unsigned Windows **stable** workflow based on the proven unsigned beta workflow. It accepts an exact `vMAJOR.MINOR.PATCH` tag, checks out trusted release tooling from protected main, fetches the tag, proves its commit is on protected main, and requires a matching public source release that is neither draft nor prerelease. It builds only from that tag commit and fails if the checkout changes before manifest generation. The release-channel tag must not already exist.

The workflow builds the Windows app and installer, checks `NotSigned` on the installer and installed `Catalyst.exe`, verifies version and exact SHA-256 sidecar, runs Defender on both, and runs packaged Sage RPC, API, desktop-first-launch, and upgrade-recovery smokes. It signs a **stable** manifest with the existing Ed25519 update key and verifies that the manifest names the final installer bytes and official release URLs. It stages a draft release, uploads the installer, sidecar, manifest and signature, then publishes it as the latest non-prerelease release only after every check succeeds. The signed-release workflow remains available by explicit manual dispatch with its SignPath requirements; it never falls back to unsigned.

No general release is dispatched until the live acceptance ledger covers both original-profile PCs, all requested trading modes and lifecycle paths, reciprocal Splash receipt, final-candidate 24-hour traces with end-state audits, and final review. Those checks are release prerequisites, not assumptions made by this workflow.

## Website and update channel

Extend the website's independent verifier and metadata contract with `unsigned_stable`, distinct from `unsigned_beta` and from verified Authenticode. The verifier must require a non-prerelease latest release in the official release-channel repository; exact installer name and URL; actual downloaded installer bytes matching the SHA-256 sidecar, GitHub asset digest, and Ed25519-signed **stable** manifest; `NotSigned` Authenticode status; and no signing-evidence artifact. Any mismatch disables the Windows download and fails the protected-main metadata check. It must never reinterpret invalid signed-release evidence as an unsigned release.

The website renders “Unsigned Windows release,” the exact SHA-256 digest, an explicit absence of a verified publisher, and concise installation instructions. For the ordinary blue “Windows protected your PC” reputation warning, users first verify the official download source and checksum, then may choose **More info → Run anyway** if Windows offers that option. The instructions must distinguish malware or potentially unwanted-app detections and explain that Smart App Control or organization policy may block execution without a per-app bypass. They must not tell users to disable Windows protections. The existing unsigned beta and signed-release views remain separate and honest.

The app's stable updater continues using its pinned release-channel URL and Ed25519 verification. Acceptance tests must prove it accepts an unsigned stable installer with a valid signed manifest and exact hash, and rejects wrong channel, signature, URL, hash, version, or expired metadata. A project-signed update manifest is not described as an Authenticode signature on the installer.

## Validation and handoff

Bot and website changes use separate feature branches and PRs into their protected main branches. Verify workflow syntax, exact-tag and release-state rejection cases, signed-manifest and sidecar tampering, wrong Authenticode state, Defender and packaged smoke failures, website rendering, protected metadata check, and updater acceptance/rejection. Test a private or staged end-to-end release without making it the public latest release. Recheck the actual public website URL and download bytes after the approved release is published. Keep the present opt-in beta and its URL intact until then.

The implementation plan must identify the bot and website PR order, the release-channel staging test, the manual final publication step, and the evidence needed to mark each gate passed. Publication remains a separate operator handoff after the full live-readiness evidence is reviewed.
