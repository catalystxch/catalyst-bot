# CATalyst 370776e primary acceptance package

Draft PR #220 runtime/source commit:
`370776e53b957c57e3b77ed12b4060f540b22521`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `13BB1838887876FDD8C701F555B54BBF2A4498B2F65B557B3FD80313B94968C0` |
| Bundled `_internal/bot_gui.html` | `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7` |
| `CATalyst-370776e-primary-acceptance.zip` | `2500C8437EE05204CA8FA80383A4B369AD12A31B84C5D94943DAD6BD98EAD58A` |
| `Catalyst-Setup-370776e-1.4.0.exe` | `8F6F93E9C6BAE32A4EFA417765C1379DF794FCB1EC78E9C12035AD8C6D016F28` |

The 192-file ZIP passed complete CRC read, extraction, embedded EXE hash
comparison, and extracted API smoke. The detached EXE passed packaged API,
synthetic Sage RPC, publication recovery, and native clean, duplicate,
persisted-state, and safety launch smokes. A unique-AppId current-user QA
installer passed clean install, `e99cbf2` to `370776e` same-version upgrade,
rollback, restore, installed API/Sage, and final uninstall. Installed EXE
hashes matched at every transition; QA registration and directory were
absent afterward. Defender custom scans of the bundle, ZIP, and installer
returned zero matching detections.

The live `e99cbf2` process failed closed with `HEARTBEAT_FAILED` after a
durable heartbeat stored only 11.035657 seconds of a requested 30-second
lease. The `370776e` source preserves a full duration after delayed durable
writes for normal acquisition, heartbeat, and recovery successor adoption.
Absolute-expiry callers retain their prior semantics. Red/green regressions
and 316 affected mutation/recovery tests passed. The complete local Windows
backend suite passed **7,163 tests**, with **209 skipped** (including 208
opt-in browser tests) and **427 subtests passed** in 32m 29s. The separate
Chromium run passed **208 tests**. Ruff, format, and all **11 PR checks**
passed on this source commit.

Fresh HTTP reads of these pinned artifacts matched their SHA-256 values:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8ae48499f13fac0ce4a3124eb422d20efb956f06/acceptance-artifacts/CATalyst-370776e-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/8ae48499f13fac0ce4a3124eb422d20efb956f06/acceptance-artifacts/Catalyst-Setup-370776e-1.4.0.exe)

The original TEST 7 profile still runs the superseded `e99cbf2` EXE in
read-only safety stop. Exact `370776e` live startup, wallet lifecycle,
restart/recovery, full UI, both 24-hour windows, independent secondary
acceptance, and final review remain open. The prior campaign is expired;
no replacement campaign or fee approval has been received. Keep PR #220
draft.
