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
