# CATalyst b78ce49 primary acceptance package

Draft PR #220 exact source/runtime: `b78ce495b17772b4586dc4afefca2229c4bc466f`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `A2EE395EDD88461407B6E5269F7A0B14DA9F1B9B68126A433FDF8DACE7FDB2F8` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-b78ce49-primary-acceptance.zip` | `BFA996AA4BA3793C01DC5B992B5B114922B8ABF18228BCA2DB6D92D29B17B6C6` |
| `Catalyst-Setup-b78ce49-1.4.0.exe` | `A9F7F8AA233C8C4A5E2E8D45D014088EEEB375F8AF620B28175FE4764968F02F` |

Two signing-readiness startup paths previously continued after an unexpected
preflight or fallback key-check exception. Red/green regressions confirm that
both now block before the bot starts. Doctor also treats a signing-check
exception as a failed readiness check. The invalid configured URL scheme is
no longer echoed into startup logs. The full Windows backend run passed
7,185 tests and 431 subtests, with 212 skipped. Ruff check, format, and diff
checks passed. The bundled UI is unchanged from `61a18d6`, whose Chromium
suite passed 211 tests.

The 192-file ZIP passed CRC. The detached EXE passed packaged API, synthetic
Sage RPC and interrupted-publication recovery smokes. A unique-AppId
current-user QA installer passed installation, installed EXE hash and API
smoke, and uninstall. Its QA registration and installed EXE were absent after
uninstall. Defender custom scans of the bundle, ZIP and public installer
reported zero matching detections.

Original-profile read-only restart, independent secondary package acceptance,
live offer lifecycle, full native UI, both 24-hour windows and final review
remain open. PR #220 stays draft.
