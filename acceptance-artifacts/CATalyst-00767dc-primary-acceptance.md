# CATalyst 00767dc primary acceptance package

Draft PR #220 runtime/source commit:
`00767dc7de7a3801f80377707ce54d381f970b7b`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `48E2C3394B04EDD39FFB65A8C3D3D7A3BC3A6395095C7A1E2BC297621CEC68B1` |
| Bundled `_internal/bot_gui.html` | `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7` |
| `CATalyst-00767dc-primary-acceptance.zip` | `96BC603DA0F7406BA50C25A4307645B2BD98FAA7487BEF2915B2F48AA1EEDE84` |
| `Catalyst-Setup-00767dc-1.4.0.exe` | `D0C578A6443AA2E7C0720D00910222DEB5DEC3EA847D4AB0E1A9B05850EA3264` |

The 192-file ZIP passed complete CRC read, extraction, embedded EXE/UI hash
comparison, and extracted API smoke. The detached EXE passed packaged API,
synthetic Sage RPC, publication recovery, and native clean, duplicate,
persisted-state, and safety launch smokes. A unique-AppId current-user QA
installer passed 69a7071 clean install, upgrade to 00767dc, rollback,
restore, restored API/native, and final uninstall. Installed EXE hashes
matched at every step; QA registration and installation directory were
absent afterward. Defender custom scans of the bundle, ZIP and installer
completed with zero matching detections.

The affected Bootstrap API and offer-journal slice passed 122 tests; its
new stopped-attention regression was red on 69a7071 and green on 00767dc.
The bundled UI is byte-identical to the 69a7071 UI, whose complete Chromium
suite passed 207 tests. The full local Windows Python suite and exact-source
CI unit job were still running when this manifest was drafted.

Original-profile TEST 7 startup, live lifecycle, restart/recovery, full UI,
both 24-hour windows, independent secondary acceptance and final review
remain open. The prior campaign is expired and no new campaign or fee
approval has been received. Keep PR #220 draft.
