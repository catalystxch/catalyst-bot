# Manual coin maintenance / Start Bot interlock (`8fb4564`)

## Defect and correction

Manual `/api/coins/topup` and `/api/coins/prep` proved that the bot was
stopped before reserving the background worker. Start Bot could pass between
those operations, allowing maintenance and offer work to overlap. A top-up
could also reserve while full Coin Prep was active. Red regressions reproduced
both races.

Production runtime commit `b05a1cd1d8210dd5e247094d38a6be4a54257805`
serializes each route's stopped proof and worker reservation with Start Bot's
final transition under `_bot_cancel_lifecycle_lock`. Start Bot denies a busy
coin manager with `COIN_MAINTENANCE_IN_PROGRESS` before `bot.start()`.
`CoinManager.start_topup()` also refuses active full prep. Stopped-state and
fee-approval response precedence are preserved. Test-only child
`8fb45649e7d6b047ecbf27f3b5e818318c75b079` updates five older fake-bot
fixtures to model the new idle coin manager. Child PR #258 was integrated by a
non-force fast-forward into draft PR #220's feature branch.

## Exact-source verification

- Primary Python 3.12 full serial Windows backend: **7,574 passed, 261
  skipped, 457 subtests passed**, exit 0. Log:
  `E:\catalyst-manual-coin-interlock-full-final.log`, SHA-256
  `44809D8E4C65E91EE05A2487FB11F79E374485545A7711E75069D00294440C49`.
- Independent secondary Python 3.12.10 exact-head full backend: **7,574
  passed, 261 skipped, 457 subtests passed**, exit 0. It also passed 102
  affected fixture tests, 220 focused mutation/lifecycle tests and six
  subtests; no original-profile app or wallet access. Secondary full log:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\acceptance-8fb45649-py312-secondary-20261009\pytest-py312-full.log`,
  SHA-256 `9B8C4BF48E4B9397D2F18860E484D3D393D3BCC6871DF6F685370EE2A31C1AD1`.
  Its only warning is an unrelated existing pytest 10 deprecation.
- Primary isolated Chromium: **260 passed**, exit 0. Log:
  `E:\catalyst-manual-coin-interlock-chromium.log`, SHA-256
  `D041CBCD07774E56D257C5B8937C99D8677C1BE4E30D18365006BD3596BAA4E4`.
- Repository-wide Ruff check/format and Git diff check passed. Independent
  secondary review of production commit `b05a1cd` found no source-visible
  defect. The first primary full run's nine failures were all older fake-bot
  fixture omissions; the affected five files passed 102 tests after correction
  and the final full run passed.

## Clean detached Windows package

Built from exact `8fb4564` in
`C:\catalyst\.superpowers\manual-coin-start-b05-build`. That commit differs
from production commit `b05a1cd` only in test fixtures.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `EF8F0E3AFB5966AF9A372CACD7CCED979D368CD4BB8DDD11D54F508F1CAA3C28` |
| bundled `bot_gui.html` | `125FCB4CE9B68B4363C8E227ED29FDD6604CE6559A0950ABF16783AB03DBCA4B` |
| acceptance ZIP | `26F30F1FB240B82374F8CB037309B77E8E2FEFD7AB8C25DCF261B307F608CF78` |
| unsigned installer | `F4ADEDF9524F4997A33D56C16E1C1AF3025C036A8E0F5E0576E9A2260732D4F8` |

Directory package API, synthetic Sage RPC worker, publication recovery, and
native clean/duplicate/persisted/safety launch smokes passed. The ZIP had 206
unique safe entries, clean CRC, and embedded EXE/UI hashes matching the clean
build; its extracted API smoke passed. A unique-AppId current-user QA installer
installed the byte-identical EXE, passed installed API and synthetic Sage
smokes, then uninstalled with its registration removed. Windows Defender
custom scans of the EXE, ZIP, and release installer found no candidate-tied
detections.

The immutable acceptance ZIP, unsigned installer, and manifest are pinned at
artifact commit `2191266e7d32d20c9c83306a7fa9b4b845711c21`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2191266e7d32d20c9c83306a7fa9b4b845711c21/acceptance-artifacts/CATalyst-8fb4564-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2191266e7d32d20c9c83306a7fa9b4b845711c21/acceptance-artifacts/Catalyst-Setup-8fb4564-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2191266e7d32d20c9c83306a7fa9b4b845711c21/acceptance-artifacts/SHA256SUMS-8fb4564.txt)

Fresh independent HTTP streams of both pinned binaries matched their
expected SHA-256 hashes and byte lengths.

## Remaining gates

The original TEST 7 profile still runs the prior exact `aba6667` executable
in stopped, read-only safety monitoring. No real-wallet effect was made for
this correction. Exact `b05a1cd` original-profile rollout, secondary
original-profile acceptance, live active-offer lifecycle/recovery, real Splash
peer receipt, complete native UI, both final-candidate 24-hour windows, and
final review remain open. PR #220 stays draft; no public beta is deployed.
