# Wallet picker accessibility acceptance, 2026-10-05

Draft PR #220 targets `main`. Exact source/runtime commit
`6e4d61d32702330876ce5cfe26d77401f1c873ba` addresses four independently
reproduced UI defects: the toolbar wallet control could not be reached or
activated from the keyboard; focus could leave the wallet picker dialog; a
long unbroken wallet label overflowed its card; and the disabled Start button
had no programmatic link to its reason. The secondary PC recorded the defects
at immutable evidence commit `8131463cac94d19d449a54dac02478bae9447109`.

The focused browser regression was red on the prior source (four failures)
and green after the fix (four passes). The toolbar control is a native button
with actual disabled state when switching is locked. The picker wraps Tab and
Shift+Tab within its visible controls and returns focus to the opener after
Escape. Both fingerprint card render paths wrap long labels within the card.
The Start button references its nearby reason with `aria-describedby`.

## Exact source and package

- `python -m pytest -q tests/e2e --e2e`: **218 passed** in 211.37 seconds.
- Ruff check and format check passed for the new browser regression, and
  `git diff --check` passed. The full local Windows backend suite completed
  immediately before this UI-only source change: **7,197 passed, 215 skipped,
  431 subtests passed**. All 11 PR CI checks, including unit tests, passed
  on exact source commit `6e4d61d`.
- Clean detached Windows PyInstaller build at
  `E:\catalyst-wallet-picker-6e4d61d-build` passed post-build HTML and CA
  checks. Its bundled UI SHA-256 matched the source:
  `FD92FD2F301DD5343C3B0C5E1F96DBB13A2626712CC71508C679D24852DA0871`.
- EXE SHA-256:
  `1BA5FD4F3367CBE61DC2E3AADA0DA3EA5AD848136345C6AAA2504BAF9F5168D7`.
  Packaged synthetic Sage RPC, authenticated API, and native clean, duplicate,
  persisted and safety launch smokes passed using isolated test data.
- Acceptance ZIP SHA-256:
  `EC0C0AF323FA60DA10F8257A2FCC7E000D8935FED48A790D7EF45F9C29688205`.
  All 206 entries passed CRC. The independently downloaded ZIP extracted to
  the same EXE hash and passed packaged API smoke.
- Unsigned installer SHA-256:
  `322AE2E9599B7E95B734D1FB3C6C52937BA2FD2159F46D265DA8AB06685C72F4`.
  A separate-name, unique-AppId current-user QA installer installed into an
  isolated E: directory. Its EXE hash matched the clean build, its installed
  API and synthetic Sage smokes passed, and uninstall removed the EXE and its
  HKCU registration. The pinned installer signature status is `NotSigned`.
- Microsoft Defender custom scans of the bundle, ZIP and installer added zero
  threat detections. Independent HTTP downloads of the pinned ZIP and
  installer matched their local SHA-256 hashes.

The immutable artifacts are pinned at commit
`1fb103cff9af58ccaf6fbfda556be276ff820fa2`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1fb103cff9af58ccaf6fbfda556be276ff820fa2/acceptance-artifacts/CATalyst-6e4d61d-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1fb103cff9af58ccaf6fbfda556be276ff820fa2/acceptance-artifacts/Catalyst-Setup-6e4d61d-1.4.0.exe)

## Live boundary

The original TEST 7 profile is still running the previous exact `b7eab4f`
package as sole PID `20784` under a one-minute read-only stability monitor.
Through sample 1,183 at 2026-10-05 17:07 UTC, every sample had an owned lease,
ALLOWED safety, synced Sage, stopped bot, and zero open offers. This window
began on 2026-10-04 21:06 UTC and cannot complete before 2026-10-05 21:06
UTC. It does not certify `6e4d61d`. Original-profile live acceptance of the
new package, active-offer lifecycle and recovery, both 24-hour windows and
final review remain open. The prior campaign is stopped with zero fee spend;
there is no new campaign or fee approval and no wallet effect from this fix.
