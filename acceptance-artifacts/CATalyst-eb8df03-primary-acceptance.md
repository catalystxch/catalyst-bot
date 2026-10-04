# CATalyst eb8df03 primary acceptance package

Draft PR #220 exact source: `eb8df039948d350a77884b65cce8ec39f2b83824`.
This unsigned package is for acceptance testing, not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `4272D43DEC7358890418BB80AC417810B41C5708ED05E264B0A98D90FC5003E5` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-eb8df03-primary-acceptance.zip` | `FEEA5414BB484D89605E3D58FD366E7E922C946238F634F015E24C79F83981F6` |
| `Catalyst-Setup-eb8df03-1.4.0.exe` | `81BC76D4E2FF6455C329B74D3B4838530663CF770F42533681EC7CBDC2BB007B` |

The source removes raw exception text from Doctor checks and configured URL
values from invalid-URL diagnostics. Focused regressions failed before the
fix and passed afterward. The full local Windows backend run passed 7,181
tests, skipped 212, and passed 431 subtests. Ruff check, format, and diff
checks passed. The bundled UI is unchanged from `61a18d6`, whose Chromium
suite passed 211 tests.

The 206-entry ZIP passed CRC. The exact bundle passed packaged API, synthetic
Sage RPC, and interrupted-publication recovery smokes. A unique-AppId
current-user QA installer passed clean installation, installed EXE hash and
API smoke, and uninstall. The QA directory and registry entry were absent
afterward. Defender custom scans of the bundle, ZIP, and unsigned installer
returned no matching detections.

At this package checkpoint, PR CI, independent HTTP download verification,
original TEST 7 profile startup, secondary-PC acceptance, live offer lifecycle,
complete native UI, both 24-hour windows, and final review remain open.
PR #220 remains draft.
