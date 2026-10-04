# CATalyst f6596a5 primary acceptance package

Draft PR #220 exact source commit: `f6596a5fdf30e4e0f3686362786800bc165b26ec`.
This unsigned package is for acceptance testing, not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `7D4BE62A53BE9CD064657B7B6D4093B83706EAA8EC21A32B8C31755AF4B035AD` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-f6596a5-primary-acceptance.zip` | `89ED40AD07E97DA399BE094F0481C38787EC77E834CE3AE42031733E013F765E` |
| `Catalyst-Setup-f6596a5-1.4.0.exe` | `656F760E45F013F4FAECFCBCD5753B8B711977274550E0BF173CF491B47392D5` |

The 192-file ZIP passed CRC read. The detached EXE passed packaged API,
synthetic Sage RPC, publication recovery, and native clean, duplicate,
persisted-profile, and safety smokes. A unique-AppId current-user QA installer
passed clean install, installed EXE hash comparison, installed API and Sage
smokes, and uninstall. Its executable and registration were absent afterward.
Defender custom scans of the bundle, ZIP, and installer reported zero matching
detections.

The source fixes two stopped-dashboard defects found on the original TEST 7
profile. The first produced hundreds of adaptive-target reduction log events
from dashboard polling while the bot was stopped (`c31cbc0`). The second
made each dashboard request take about 20.6 seconds by constructing a full bot
state, including optional Splash health checks, merely to test whether the
bot was running (`f6596a5`). The new package returned the same dashboard in
0.221 and 0.201 seconds after a live restart. Effective buy/sell targets
remained 0/0, no reduction events reappeared, and balances and open offers
were unchanged. Red/green regressions, 31 dashboard tests, and 106 related
dashboard/status/Splash tests passed. The prior `c31cbc0` full Windows suite
passed 7,163 tests, 210 skipped, and 427 subtests; full exact `f6596a5`
Windows verification was running when this manifest was written. All 11 PR
checks on `f6596a5` require final confirmation.

No replacement campaign or fee approval has been received. Live wallet
lifecycle, both 24-hour windows, independent secondary package acceptance,
and final review remain open. Keep PR #220 draft.
