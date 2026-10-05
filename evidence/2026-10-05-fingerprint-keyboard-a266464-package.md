# Fingerprint keyboard acceptance, 2026-10-05

## Candidate and defect

Draft PR #220 targets `main`. Exact source/runtime commit
`a266464cc1ad544dcf9c11df2c60dccfa26a3e4d` changes only the two wallet
fingerprint pickers and their browser regression. The secondary PC reproduced
that both startup and toolbar fingerprint cards were focusable `div` elements
with click handlers: Enter and Space did not select the wallet. Its isolated
read-only evidence is at artifact commit
`3aff64ca619a3e656cee17ca3d273f6f23231ad8`.

The new browser regression failed twice on the prior source because neither
picker exposed a named button. Both cards are now native buttons with escaped
labels, delegated click handling, and actual disabled state during an in-flight
selection. Enter and Space now activate both pickers in the browser test.

## Source and package checks

- `python -m pytest -q tests/e2e/test_fingerprint_keyboard.py --e2e`: 2 passed
  after the red result of 2 failed on the prior source.
- `python -m pytest -q tests/e2e --e2e`: 214 passed in 136.06 seconds.
- Ruff check and format check passed for the new regression; `git diff --check`
  passed. All 11 PR CI checks, including unit tests, passed on exact source
  head `a266464`.
- Clean detached Windows build from exact `a266464` at
  `E:\catalyst-fingerprint-a266464-build` passed PyInstaller post-build checks.
  The bundled `bot_gui.html` matched the source SHA-256
  `CDCF8EBD83D5EF011AC55B4304C90A82A1EF991E2FEA70B67E4F288EA0D4876B`.
- EXE SHA-256:
  `F2A9475CF9DC3A0346F351C56468791F539772B87C52C9489C7C160ADCC794B1`.
  Isolated packaged API, synthetic Sage, and native clean/duplicate/persisted/
  safety launches passed.
- ZIP SHA-256:
  `3D5C37A4750072BD5EF725B53A1D14F06152F0F66BB9E00C964E924D768EB5B5`.
  All 206 entries passed ZIP CRC.
- Unsigned installer SHA-256:
  `F3D786BA057E8DB54E30E2FA9D6B63727306A9310A3F4EFCA8C4C8EB35680CC4`.
  A unique-AppId QA installer installed to an isolated E: path. Its installed
  EXE matched the clean hash, its API smoke passed, and silent uninstall
  removed that EXE and its HKCU registration.
- Defender custom scans of the bundle, ZIP, and unsigned installer added zero
  detections. Independent HTTP downloads of the pinned ZIP and installer
  matched their local hashes.

The immutable artifacts are pinned to commit
`81108fc26602dcddeb28a0947283f3138f3cfe9f`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/81108fc26602dcddeb28a0947283f3138f3cfe9f/acceptance-artifacts/CATalyst-a266464-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/81108fc26602dcddeb28a0947283f3138f3cfe9f/acceptance-artifacts/Catalyst-Setup-a266464-1.4.0.exe)

## Live boundary

The original TEST 7 profile is still running the previous exact `b7eab4f`
package. Its read-only stability monitor had 1,136 clean one-minute samples
through 2026-10-05 16:19 UTC, with an owned lease, ALLOWED safety, a stopped
bot, and zero open offers. That 24-hour window began at 2026-10-04 21:06 UTC
and cannot complete before 2026-10-05 21:06 UTC. It does not certify the new
`a266464` runtime. Independent secondary-PC verification of the keyboard fix
and original-profile live acceptance of the new package remain open.

The stopped prior campaign has zero authoritative fee spend. No new campaign
or fee approval exists; the older `c665` approval is invalid for a new
campaign. No wallet, offer, or fee mutation was performed for this fix.
