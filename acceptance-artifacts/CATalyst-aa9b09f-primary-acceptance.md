# CATalyst aa9b09f primary acceptance package

Draft PR #220 source commit: `aa9b09fcca3da9f7dc5b1b2abfee8aa0988ce1ea`.
This unsigned package is for acceptance testing, not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `51D871486C4F207574D01BEC9521FEEFB8AD1C14144468D1E6039D99B3DD69C8` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-aa9b09f-primary-acceptance.zip` | `12FC674BFFCCA37A1154C4289E40B69C4002ABEB5306788652F3AFE36FDB5D5C` |
| `Catalyst-Setup-aa9b09f-1.4.0.exe` | `19D5766F57338A683E9546F258B5C1DCB0B95CF7957E100394D0503B0BB664DE` |

The 192-file ZIP passed complete CRC read, extraction, embedded EXE hash
comparison, and extracted API smoke. The detached EXE passed packaged API,
synthetic Sage RPC, and publication recovery smokes. A unique-AppId
current-user QA installer passed clean install, installed EXE hash and API
smoke, then uninstall; its executable and registration were absent afterward.
Defender custom scans of the bundle, ZIP, and unsigned installer reported zero
matching detections. Native duplicate-launch and same-version upgrade smokes
were not repeated for this UI-only source change; the prior `370776e` package
passed them.

The source fixes a live TEST 7 display defect after a zero-offer expired
Bootstrap campaign was stopped: the Coin Prep preview and dashboard continued
to describe an active campaign or Follow authority. A focused Chromium
regression was red before correction and green after. All 209 Chromium E2E
tests, 15 Bootstrap cancellation browser tests, 12 Bootstrap UI contract
tests, Ruff check/format, and all 11 PR checks passed. The backend code is
unchanged from `370776e`, whose full Windows suite passed 7,163 tests with
209 skipped and 427 subtests.

The original TEST 7 profile is still running the verified `370776e` package.
The `aa9b09f` package has not been launched against that profile. The old
campaign is stopped with zero fee spend and no wallet effect. No replacement
campaign or fee approval has been received. Live wallet lifecycle,
restart/recovery, both 24-hour windows, independent secondary acceptance,
and final review remain open. Keep PR #220 draft.
