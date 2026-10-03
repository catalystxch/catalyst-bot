# CATalyst ef3406 primary acceptance package

Draft PR #220 runtime/source commit:
`ef3406fb066d6d398d480f2a7d35b17b904dce10`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `2762508F8CD16FB1EF6D57E273B670C0519AD2722C2AC9CE5203224A1C81ECB7` |
| Bundled `_internal/bot_gui.html` | `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7` |
| `CATalyst-ef3406-primary-acceptance.zip` | `F63F5B5A01FF2DF79850FF7926BB703AE812D57462DB7CC0709EC908FB816F32` |
| `Catalyst-Setup-ef3406-1.4.0.exe` | `909D35F93E7BC8322BBD3F1C37328BA80B4F93D4C08B5A23A6354EB68128BCE3` |

The 192-file ZIP passed complete CRC read, extraction, embedded EXE hash
comparison and extracted API smoke. The detached EXE passed packaged API,
synthetic Sage RPC, publication recovery and native clean, duplicate,
persisted-state and safety launch smokes. A unique-AppId current-user QA
installer passed clean install, `00767dc` to `ef3406f` same-version upgrade,
rollback, restore, installed API/native/Sage and final uninstall. Installed
EXE hashes matched at every step; QA registration and directory were absent
afterward. Defender custom scans of the bundle, ZIP and installer completed
with zero matching detections.

The Bootstrap API regression was red on the preceding source and green on
`ef3406f`. The affected backend selection passed 211 tests; the full local
Windows backend suite passed **7,154**, with **one skipped** and **427
subtests passed**. The complete Chromium suite passed **208 tests**. Ruff,
format and all 11 exact-source PR checks passed.

Fresh HTTP downloads of the pinned artifacts below matched their SHA-256
values above:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/aea4290482fef0458759e988d8cfe580d6f56f8c/acceptance-artifacts/CATalyst-ef3406-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/aea4290482fef0458759e988d8cfe580d6f56f8c/acceptance-artifacts/Catalyst-Setup-ef3406-1.4.0.exe)

Original-profile TEST 7 startup, live lifecycle, restart/recovery, full UI,
both 24-hour windows, independent secondary acceptance and final review
remain open. The prior campaign is expired and no replacement campaign or fee
approval has been received. Keep PR #220 draft.
