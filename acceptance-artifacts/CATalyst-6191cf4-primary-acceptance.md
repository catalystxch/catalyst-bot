# CATalyst 6191cf4 primary acceptance package

Draft PR #220 exact source commit: `6191cf48522a42234877a3d9fd73d339083c98b1`.
This unsigned package is for acceptance testing, not a release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `429440452B05050E80EE204BA16030E6CC850FD14213CC2006CA1DF145622DA6` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-6191cf4-primary-acceptance.zip` | `E092516652FCF1777A83D2C1426AEF54D1A12E962B1FDF25D6C3D2D246D59547` |
| `Catalyst-Setup-6191cf4-1.4.0.exe` | `BCF02FB8F39DCFA8115D6B7E5495F936E614A7D19E35BA9D06DE76DCA1CD901B` |

The 192-file ZIP passed CRC read. The detached EXE passed packaged API,
synthetic Sage RPC, publication recovery, and native clean, duplicate,
persisted-profile, and safety smokes. A unique-AppId current-user QA installer
passed clean install, installed EXE hash comparison, installed API and Sage
smokes, and uninstall. Its executable and registration were absent afterward.
Defender custom scans of the bundle, ZIP, and installer reported zero matching
detections.

The source addresses three read-only polling defects observed on the original
TEST 7 profile: adaptive-target writes while stopped (`c31cbc0`), a slow
dashboard running-state check (`f6596a5`), and a stopped optional Splash node
making each status request wait for an HTTP timeout (`6191cf4`). On the exact
`6191cf4` live package, `/api/status` completed in 1.257 and 1.149 seconds,
compared with roughly 4.5 seconds before the Splash fix. `/api/dashboard`
completed in 0.266 and 0.239 seconds. The bot remained stopped, TEST 7
balances were unchanged, and there were zero open offers. Focused Splash,
dashboard, status, and package tests passed. Full exact-source Windows suite
and PR CI status should be checked before treating these as complete gates.

No replacement campaign or fee approval has been received. Live wallet
lifecycle, both 24-hour windows, independent secondary package acceptance,
and final review remain open. Keep PR #220 draft.
