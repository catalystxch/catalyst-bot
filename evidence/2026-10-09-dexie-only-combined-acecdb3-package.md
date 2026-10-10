# Combined Dexie-only beta candidate — 2026-10-09

**Superseded for acceptance:** CI found an `.env.example`/loader default
mismatch. The corrected exact runtime, full rerun and replacement package
are recorded in
[the `515b41c` evidence](2026-10-09-dexie-only-combined-515b41c-package.md).

## Exact identity

- Runtime/package source: `acecdb3de39b619e857c70879b6e8da69a00ced8`.
- Verification head: `bae610af28d76627c2013e7b58d17e310b5e674a`.
  The child changes only `tests/e2e/test_smoke.py` to exercise dormant Splash
  refresh behavior with the beta flag disabled in that test page.
- Feature branch: `codex/coin-prep-fee-approval`; PR #220 remains draft into
  `main`. The verified commits were pushed by normal fast forward.
- Package branch commit: `520c3c2020d450753abd00deca5623ace2739e06`.

## Changes under test

The combined runtime enforces the Dexie-only beta boundary across legacy
persisted Splash settings, direct config/API mutations, Splash node, receive,
queue and publication paths. It removes the Splash startup gate and hides its
operational UI while retaining isolated coverage of the dormant subsystem.
The same candidate reports bot stop as `stopping` until finalization and
preserves the prior paired XCH/CAT coin counts if a wallet snapshot fails.

## Local verification

- Full serial Windows backend on the runtime source: **7,490 passed, 1
  skipped, 455 subtests passed** in 20m33s.
- Full Chromium on the test-only child: **256 passed** in 2m37s. The first
  run had 255 passed and one legacy Splash refresh expectation fail because
  the release gate intentionally stopped its poll. The test now explicitly
  exercises that dormant path with the beta flag off; its focused rerun and
  full suite passed.
- Ruff check, Ruff formatting, and Git whitespace checks passed for the
  combined changed source and the final browser test.
- Clean detached PyInstaller build from the runtime source passed. Its
  packaged API, synthetic Sage RPC, publication recovery, and native clean,
  duplicate, persisted and safety launch smokes passed in isolated profiles.
- The ZIP contained 192 files, passed CRC, extracted to 192 files with the
  expected EXE hash, and passed an extracted packaged API smoke.
- A unique-AppId, unique-name current-user installer passed isolated clean
  installation, installed packaged API and synthetic Sage checks, and
  uninstall. The installed EXE hash matched; the QA uninstall key and EXE
  were absent afterward. Production registration and user data were not used.
- Defender custom scans of the ZIP and unsigned installer found zero new
  detections attributable to this package.
- Independent HTTP downloads of both pinned artifacts matched the local
  SHA-256 hashes below.

## Pinned Windows package

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `81D87772463B645A1CA6E2D9F547E2F736499FFEAEA0F866280E4DFB4DE2873E` |
| Bundled `bot_gui.html` | `F355EF52EA22F1E5F6FAAD872FD6051AB46BE700522F9795832414B63C25EE88` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/520c3c2020d450753abd00deca5623ace2739e06/acceptance-artifacts/CATalyst-acecdb3-primary-acceptance.zip) | `6C45146D5CBC50772942922E01D4E344003CBDF86A28F485C08AB011A5F1DEFB` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/520c3c2020d450753abd00deca5623ace2739e06/acceptance-artifacts/Catalyst-Setup-acecdb3-1.4.0.exe) | `47E5B56D97585EA324832EE87566D17A8A05326802517A6A9CE25DFF0F7AFF4A` |

## Open acceptance gates

This package has not run against the primary or secondary original live
profile. The older `0bf0346` original TEST 7 process and read-only monitor
remain diagnostic: sample 110 at 2026-10-09T03:30:14Z had zero alerts,
stopped bot, zero DB offers, allowed safety and an owned renewing lease. It
cannot count toward a final-candidate 24-hour window.

Independent secondary verification of the pinned source and package is
requested. Its C: drive had 3,015,172,096 bytes (2.81 GiB) free at
2026-10-09T03:26:36Z. Its original Sage profile is Harvestr fingerprint
`3702373391`; TEST 7 fingerprint `736588221` was absent at its last key
inventory. No secondary original-profile live wallet acceptance is claimed.

The combined candidate still requires exact original-profile restart/UI,
active-offer lifecycle and recovery, a clean primary and secondary 24-hour
window, final review, and current-head CI. The specific new mainnet campaign
and fee scope has not been approved. No new campaign, wallet effect, main
merge, tag, release, or website beta publication occurred for this package.
