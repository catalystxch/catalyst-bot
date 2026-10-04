# CATalyst dfc53d9 primary acceptance package

Draft PR #220 exact runtime/source: `dfc53d95942fbd7f73c61ecef38044bda6aace14`.
This unsigned package is for acceptance testing, not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `B38EF8FE8CC232EBD56093A5442D84D8669E416BCE19B3E48F1A9075BD6F812D` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-dfc53d9-primary-acceptance.zip` | `362617A7876751D1C27390D4170DB3EF0711FFD5F8A05F7E3AE846436387761C` |
| `Catalyst-Setup-dfc53d9-1.4.0.exe` | `CA3F0699512F7B724D4123EE2B285597F4F6DAB02E20911CBB86DC8F43B02AAC` |

The prior Start route treated an active campaign bound to another Sage wallet
fingerprint as absent and could return HTTP 200. The trading loop already
blocked Follow mutations whenever an active campaign owned the selected asset.
An isolated red regression observed the misleading successful Start. The
route now returns bounded `BOOTSTRAP_AUTHORITY_MISMATCH` (409) without calling
`bot.start()`. The route file passed 46 tests and 4 subtests. The full local
Windows backend passed 7,195 tests, skipped 212 and passed 431 subtests.
All 11 exact-source PR checks passed.

The detached build passed packaged API, synthetic Sage RPC, interrupted
publication recovery, and native clean/duplicate/persisted/safety smokes.
The 206-member ZIP passed CRC; its embedded EXE matched the build. A unique
AppId QA installer passed clean install, installed EXE hash, installed API
smoke and uninstall. Defender custom scans found zero attributable detections.

The previous exact `244da2e` app remains stopped on the original TEST 7
profile. Exact `dfc53d9` original-profile live acceptance, live offer
lifecycle, both 24-hour windows, secondary exact-candidate acceptance and
final review remain open. PR #220 stays draft.
