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

## Independent secondary check

The secondary PC checked out exact source `6e4d61d` detached, passed the six
focused wallet keyboard tests and all 218 Chromium tests, and built its own
clean Windows package. Its bundled UI SHA-256 matched the primary source and
bundle. A direct bundled-UI probe confirmed real-toolbar Enter activation,
contained Tab/Shift+Tab focus with Escape returning to the opener, no card
overflow at 390 and 1280 pixels with a 176-character unbroken label, and an
accessible disabled-Start description. It recorded zero non-GET requests or
page errors. Its isolated-profile packaged startup showed no Sage connection
or wallet mutation and closed normally; original Harvestr profile hashes were
unchanged. Its Python 3.14.3 EXE hash differs from the primary Python 3.12.6
build, so it does not attest to the primary EXE bytes. The immutable
[secondary evidence](https://github.com/catalystxch/catalyst-bot/commit/0b3b18f27954729e1b9ba6588e8a6312ce9358bd)
records the bounded result.

## Secondary original-profile read-only acceptance

The secondary PC then backed up and hash-checked its original Harvestr
profile (23 files, zero mismatches) and ran its exact-source Python 3.14
package against that profile twice. Direct Sage 0.13.0 RPC before and after
proved Chia mainnet, fingerprint `3702373391`, CAT wallet ID `2`, the exact
MZ asset, unchanged `240.800676512155` XCH and `3,381,521.720` MZ,
zero pending transactions and zero active fillable offers. The first launch
retired an expired owner lease and both launches acquired and released their
own leases cleanly. Runtime safety had zero blockers, the bot remained
stopped, and an expired prior Bootstrap campaign correctly required an
explicit stop before renewal. Its campaign, offer, Coin Prep, reservation,
publication and fee-approval database projections and `.env` were unchanged.
The supported Sage picker showed the single correct Harvestr wallet; the
wallet card was not selected because that would persist configuration. No
wallet or offer effect occurred. CATalyst and Sage were closed afterward.

The secondary profile has historical fee approvals and a nonzero prior
campaign fee spend, distinct from the primary TEST 7 profile. Its public
authoritative fee view reports the maximum of proven evidence and the stored
campaign row; the secondary PC confirmed that this difference was already
present before the test and was not a startup write. The immutable
[original-profile report](https://github.com/catalystxch/catalyst-bot/commit/a9bd85ea77727bf1b35e83b398d2cf60ab97c569)
includes screenshots and backup/ledger comparisons. This passes only the
secondary read-only startup, identity, fail-closed, shutdown and restart
scope. Secondary live trading and fee lifecycle remain open.

## Independent synthetic active-offer recovery

The secondary PC also exercised exact `6e4d61d` in fresh temporary
mock-wallet profiles. Its deterministic full lifecycle passed 3 tests for
offer creation, durable publication/discovery, GREEN-to-RED gating, verified
fill evidence, replacement backoff, cancellation, and DB close/reopen
recovery. A focused backend restart/authority group passed 58 tests, and
three focused Chromium tests passed for explicit resume, wallet-wide Cancel
All consent, and authoritative cancel completion before Coin Prep. Its exact
compiled EXE passed interrupted-publication recovery with two active offer
projections and a stale killed-owner lease: the undispatched claim became
retryable while an ambiguous dispatched claim was suppressed. Native
clean/duplicate/persisted/safety and authenticated synthetic Sage smokes
also passed. Dexie posting and Splash were disabled; no live wallet or
provider effect occurred. The original Harvestr profile hashes remained
unchanged. The immutable
[synthetic recovery report](https://github.com/catalystxch/catalyst-bot/commit/75bf9a6b4ec3bda96808220555cf008ae2c70804)
records the exact scope and results. Real-wallet active-offer lifecycle and
recovery remain unverified.

## Live boundary

The original TEST 7 profile is still running the previous exact `b7eab4f`
package as sole PID `20784` under a one-minute read-only stability monitor.
Through sample 1,183 at 2026-10-05 17:07 UTC, every sample had an owned lease,
ALLOWED safety, synced Sage, stopped bot, and zero open offers. This window
began on 2026-10-04 21:06 UTC and cannot complete before 2026-10-05 21:06
UTC. It does not certify `6e4d61d`. Original-profile live acceptance of the
new package, active-offer lifecycle and recovery, both 24-hour windows and
final review remain open. The primary prior campaign is stopped with zero fee spend;
there is no new campaign or fee approval and no wallet effect from this fix.
