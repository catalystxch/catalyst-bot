# CATalyst 244da2e primary acceptance package

Draft PR #220 exact runtime/source: `244da2eb49cd89351647b999a8996fd9a6bc07ff`.
This unsigned package is for acceptance testing; it is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `DC9D916C1BC574A32E5B42C63AE713C864C3E6C2151D9078EAA33C7F87F65BB4` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-244da2e-primary-acceptance.zip` | `9D4002CE178C7343FC9B96EBDE548BED46E971E785FCF409E9C5AA45EE1A8280` |
| `Catalyst-Setup-244da2e-1.4.0.exe` | `1B68682B2C3D5DB8FEE6CCE85CCEDD7A04FE7BEAD8BADFA15FE9139CF7B372DC` |

The start route previously treated a failed active-campaign read or two
simultaneously active campaigns as if no campaign existed and could report
`started` after the legacy tier check. Two focused red/green regressions now
require bounded `BOOTSTRAP_AUTHORITY_UNAVAILABLE` or
`BOOTSTRAP_AUTHORITY_AMBIGUOUS` responses and no `bot.start()` call. The
affected route file passed 45 tests and four subtests. Full Windows backend
and PR CI verification is in progress at package publication time.

The detached build passed packaged API, synthetic Sage RPC, interrupted
publication recovery, and native clean/duplicate/persisted/safety smokes.
The 192-file ZIP passed CRC, and its extracted EXE matched the build and
passed packaged API smoke. A unique-AppId QA installer passed clean install,
installed EXE hash, installed API smoke and uninstall without touching the
production registration. Defender scans found zero attributable detections.

The previous exact `1ef4799` app remains stopped on the original TEST 7
profile. Exact `244da2e` original-profile live acceptance, live offer
lifecycle, both 24-hour windows and final review remain open. PR #220 stays
draft.
