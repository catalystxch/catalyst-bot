# Exact-196 unsigned beta release-file preflight

On 2026-10-08, the primary Windows host staged a local copy of the pinned
`196caa890ebf97ed08435ac492edd6edd553f9e9` unsigned installer for the
manual beta workflow's release-file checks. This was a local dry run: no tag,
GitHub release, update channel, or website publication was created.

- Source installer: `E:\catalyst-auth-read-196caa8-build\Output\Catalyst-Setup-1.4.0.exe`.
- Staged installer: `E:\catalyst-196caa8-release-staging\Catalyst-Setup-v1.4.0.exe`.
- Staged sidecar: `E:\catalyst-196caa8-release-staging\Catalyst-Setup-v1.4.0.exe.sha256`.
- Installer size: 38,420,711 bytes; SHA-256:
  `c1e3550885287ef0ba33c85a0ef5752c6d574f0a4b8be3ca97ab5fbf5c07cbff`.
- The sidecar contains the lowercase digest, two spaces, and the exact staged
  installer filename, followed by one newline. The workflow's `TrimEnd` and
  case-sensitive comparison passed against the copied bytes.
- Windows `Get-AuthenticodeSignature` returned `NotSigned`; the installer's
  trimmed `ProductVersion` was `1.4.0`. These match the requirements in
  `.github/workflows/publish-unsigned-windows-beta.yml` for tag `v1.4.0`.

The clean detached package, isolated installer QA, Defender scan, and
independent pinned-download hash checks are recorded separately in the exact
candidate package evidence. This filename/sidecar check does not exercise the
release workflow's protected-main tag, public source release, GitHub release
asset download, signed update manifest, or website synchronization. The
installer must be rechecked if the runtime candidate changes.

The primary PC also ran `scripts/sign_update_manifest.py`'s manifest builder
against the exact staged installer and sidecar, using the workflow's v1.4.0
release-channel URLs. It produced version `1.4.0`, tag `v1.4.0`, the exact
installer name, size and SHA-256 above. An ephemeral Ed25519 test key signed
the canonical manifest, and the corresponding test public key verified the
signature. This proves local input and signing compatibility only; it does not
exercise the production secret, remote release assets, or publication.

## Independent secondary-PC check

The Harvestr secondary PC independently checked the pinned 38,420,711-byte
installer at SHA-256 `C1E3550885287EF0BA33C85A0EF5752C6D574F0A4B8BE3CA97AB5FBF5C07CBFF`.
It staged the required release filename through a same-volume hard link to
preserve disk space and verified the lowercase two-space sidecar, `NotSigned`
Authenticode status, and trimmed `1.4.0` product version. Its focused
`tests/test_unsigned_windows_beta_release.py` run passed **5/5**. No release or
wallet action occurred. The independent report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\monitor-196caa8-original-20261008T0945BST\UNSIGNED-BETA-INSTALLER-AUDIT.md`,
reported SHA-256
`4CC1722338E7813AF5E114976DA19BC22FE71C2DE69CF334BD533CF926930E0C`.
The secondary PC reported exact original-profile monitor sample 22 at
`2026-10-08T09:03:15.3178136Z` with zero alerts, a stopped bot, owned lease,
zero active offers or pending/fillable Sage offers, and unchanged Harvestr
balances. That early sample does not satisfy its 24-hour window.
