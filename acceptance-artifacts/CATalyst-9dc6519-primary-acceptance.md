# CATalyst 9dc6519 primary acceptance package

Draft PR #220 exact source: `9dc65197a95afb23a405e3c569a587cb6aa9a305`.
This unsigned package is for acceptance testing. It is not a release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `1B5A5362D10DA11DB65100DF556ECB59A0B7112795DCA1BEBFCF2E5BE295CD5E` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-9dc6519-primary-acceptance.zip` | `8B8C3F83DED2D47106503EDD54D1181EC0A0BC188B76571F31EB254764132AB2` |
| `Catalyst-Setup-9dc6519-1.4.0.exe` | `37EE99EA54D2C27BD174E0688BED5A50D8E43772E6B71BFD4B7637379818A4A1` |

The 192-file ZIP passed CRC read. The detached EXE passed packaged API, synthetic Sage RPC, publication recovery, and native clean, duplicate, persisted-profile, and safety smokes. A separately named, unique-AppId current-user QA installer passed clean install, installed EXE hash comparison, installed API and synthetic Sage smokes, and uninstall. Its executable and registry entry were absent afterward. Defender custom scans of the bundle, ZIP and installer reported zero matching detections.

The source corrects `GET /api/price` so public reads use an expiring, selected-pair Dexie quote without calling stateful `PriceEngine.get_price()`. Two endpoint tests failed on the previous source and passed on this one. Focused backend tests passed 87 cases and four subtests; Ruff and format passed. Full exact-source Windows tests and PR CI were in progress at package publication.

The original TEST 7 profile still runs the older `6191cf4` EXE in stopped safety state. The exact `9dc6519` package has not been run against that profile. No new campaign or fee approval exists. Live wallet lifecycle, both 24-hour windows, independent secondary acceptance and final review remain open. Keep PR #220 draft.
