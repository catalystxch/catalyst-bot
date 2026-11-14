# Public Dexie beta release-chain audit (2026-10-15)

This audit concerns the **existing opt-in v1.4.1 beta**, not a general
public-readiness approval or a release of draft PR #268.

- `catalystxch.com` was read at the actual public URL. It says **New Dexie
  only beta testing**, names Dexie as the offer marketplace, and describes
  Splash as optional offer broadcasting that starts off. Its beta guide says
  independent Splash peer receipt and real-wallet recovery testing are open.
- Website [PR #89](https://github.com/Lowestofttim/catalystxch/pull/89) is
  merged. Pages reports HTTPS enforced, `main` as its source, status `built`,
  and the last deployment of the current site head `af6c170a9d246af2adec69f8de59ee46d3d2fd8c`
  [succeeded](https://github.com/Lowestofttim/catalystxch/actions/runs/38030414348).
  The current release-metadata sync workflow also succeeded at that head.
- Bot tag `v1.4.1` resolves to
  `1ede594c8268cfb8f554a1b8c643d430dedc809b`. The bot repository has
  the Linux v1.4.1 prerelease assets; the separate
  [public release channel](https://github.com/Lowestofttim/catalyst-releases/releases/tag/v1.4.1)
  has the Windows installer, SHA-256 sidecar, signed `latest.json`, and its
  versioned manifest copy/signature.
- The public website metadata reports v1.4.1 prerelease from that release
  channel. The downloaded `latest.json` has `channel=beta`, the same source
  commit as the bot tag, and expiry `2027-01-08T01:40:53Z`.
  Its Ed25519 signature verified against the public key pinned in
  `src/catalyst/app_update.py` using the app's canonical manifest bytes.
- An independent release download of `Catalyst-Setup-v1.4.1.exe` was
  36,859,947 bytes. Its SHA-256
  `70713d25cfc778f532c6f81c45ada850d0eb22df6eee6cdeb26b42c60d2f1434`
  matched the downloaded sidecar, the signed manifest, and the actual website
  metadata, including the exact official download URL and size. The website
  identifies it as an **unsigned beta**; the manifest signature is not an
  Authenticode signature for the installer.

The website's release-sync workflow invokes the Windows release
verifier before updating metadata. This audit independently checked the
published output as described above. It does **not** validate a future
general-release artifact, current trading runtime PR #268, the final
24-hour gates, or wallet acceptance on either original-profile PC.
