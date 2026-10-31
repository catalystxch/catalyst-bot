# General Windows signing gate (2026-10-16)

This is a read-only release-path audit for general public readiness. It does
not approve draft PR #268, a new release, or any wallet action.

## Current release paths

- `docs/CODE_SIGNING_POLICY.md` requires CATalyst-owned application and
  installer signatures for the signed release. It records that the project's
  SignPath Foundation application was not approved. The opt-in v1.4.1 Windows
  beta is expressly unsigned.
- `.github/workflows/build-release.yml` requires `SIGNPATH_API_TOKEN` and
  `SIGNPATH_ORGANIZATION_ID` before signing. GitHub run
  [38013902521](https://github.com/catalystxch/catalyst-bot/actions/runs/38013902521)
  failed at the configuration gate with `SIGNPATH_API_TOKEN is required`.
  Repository-level secrets and variables showed neither required value on
  2026-10-16. Organization-level configuration was not readable, so it is not
  characterized here; the failed run is the effective evidence.
- The public `v1.4.1` prerelease is an opt-in beta. The release repository's
  `v1.3.21` remains the latest stable release. The app's stable updater pins
  `/releases/latest/download/latest.json`, and its verifier accepts the
  `stable` channel while rejecting the beta channel. The beta manifest has a
  valid Ed25519 signature, but that is not an Authenticode signature on its
  installer. See the separate public beta release-chain audit.

## Viable signing routes requiring an operator decision

1. Reapply to [SignPath Foundation](https://signpath.org/terms.html) after the
   project meets its eligibility and adoption requirements. The existing
   workflow and verification policy are written for this route, but access
   has not been granted. Do not insert placeholder credentials or route around
   the signing gate.
2. Evaluate [Microsoft Artifact Signing Public Trust](https://learn.microsoft.com/en-us/azure/artifact-signing/concept-trust-models)
   as a different Authenticode issuer. Microsoft's
   [quickstart](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
   requires an Azure subscription, identity validation, and a certificate
   profile. It lists the United Kingdom among eligible **organization**
   locations, while Public Trust **individual** developers must be in the
   United States or Canada. Eligibility depends on the intended publisher's
   actual legal identity and location. Microsoft's published
   [Basic tier](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-change-sku)
   is $9.99 per month for 5,000 signatures; no account or billing commitment
   has been made. Using this route would require a separately reviewed
   workflow and equivalent exact-byte signature, timestamp, publisher,
   checksum, update-manifest, Defender, and website gates.

Until a trusted signing identity and an end-to-end signed artifact are
verified, the existing unsigned beta must not be represented as a general
signed Windows release. Live original-profile acceptance, reciprocal Splash
receipt, final-candidate 24-hour audits, and final review remain separate
open gates.
