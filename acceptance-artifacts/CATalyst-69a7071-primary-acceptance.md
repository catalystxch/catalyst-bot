# CATalyst 69a7071 primary acceptance package

Draft PR #220 runtime/source commit:
`69a7071120c985cc585cdb3860ce394c4dfa4448`.
This package is for acceptance testing only. It is unsigned and is not a
release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `01AC1CAD95FA6FD25979D082070A1C99512FA3D9CFBEFF182D9C85B5F5A2469D` |
| Bundled `_internal/bot_gui.html` | `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7` |
| `CATalyst-69a7071-primary-acceptance.zip` | `5166D452A0E2B2104941C40A2BFF6765060A0ACD464491A14F95D8B117F9425C` |
| `Catalyst-Setup-69a7071-1.4.0.exe` | `E621E2EA3D002D1FA88A236D3A75C506DD7A9D14A3EBCD25259963D6B9D80437` |

The 192-file ZIP passed a complete CRC read, extraction, embedded EXE/UI
hash comparison, and packaged API smoke. The detached EXE passed packaged
API, synthetic Sage RPC, publication recovery, and native clean, duplicate,
persisted-state, and safety launch smokes. A unique-AppId current-user QA
installer passed clean install, installed API/Sage, uninstall, same-version
7183853-to-69a7071 upgrade, 7183853 rollback, 69a7071 restore, restored
API/native smokes, and final uninstall. The QA registration and installation
directory were absent afterward. Defender custom scans of the bundle, ZIP,
and unsigned installer completed with zero matching detections.

Affected Bootstrap API and offer-journal tests: 122 passed. Complete Chromium
suite: 207 passed. All 11 exact-source PR CI checks passed. The complete local
Windows Python suite was still running when this manifest was drafted. No original TEST 7
profile or wallet effect was used by these package checks.

The prior approved MZ/XCH campaign expired. Exact-package original-profile
startup, Sage identity preflight, mainnet lifecycle, restart/recovery, full
live UI, both 24-hour windows, independent secondary acceptance, and final
review remain open. Keep PR #220 draft.
