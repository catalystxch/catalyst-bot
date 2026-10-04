# Active Bootstrap identity start gate

Draft PR #220 remains open against `main`. Source commit
`dfc53d95942fbd7f73c61ecef38044bda6aace14` changes the bot Start route's
handling of an active campaign for the selected asset whose frozen wallet
authority differs from the currently selected wallet.

The prior route treated the mismatched campaign as absent and could return
HTTP 200 from ordinary Follow startup. An isolated route regression first
observed that HTTP 200 with `bot.start()` called for a campaign bound to a
different Sage fingerprint. The trading loop already treated any active
campaign for that asset as blocking Follow mutations, so the successful Start
response contradicted its downstream safety decision.

The route now returns bounded `BOOTSTRAP_AUTHORITY_MISMATCH` (HTTP 409) before
calling `bot.start()`. An empty active campaign set still takes the ordinary
Follow path. An unreadable set remains HTTP 503; multiple active campaigns
remain HTTP 409. The existing mismatch test was updated to require the route
to block before the legacy tier-drift check.

The focused start-gate slice passed 7 tests and 2 subtests. The full route
test file passed 46 tests and 4 subtests. Ruff check, Ruff format and Git diff
check passed. The full local four-worker Windows backend suite passed **7,195
tests, 212 skipped, 431 subtests** in 971.57 seconds. All 11 exact-source PR
checks passed, including unit tests.

## Exact detached Windows package

Built from a clean detached checkout at `dfc53d9`. Build output changed only
the detached checkout's generated `_version.py` metadata.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-bootstrap-mismatch-dfc53d9-build\dist\Catalyst\Catalyst.exe` | `B38EF8FE8CC232EBD56093A5442D84D8669E416BCE19B3E48F1A9075BD6F812D` |
| Bundled `_internal\bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-dfc53d9-primary-acceptance.zip` | `362617A7876751D1C27390D4170DB3EF0711FFD5F8A05F7E3AE846436387761C` |
| Unsigned `Catalyst-Setup-dfc53d9-1.4.0.exe` | `CA3F0699512F7B724D4123EE2B285597F4F6DAB02E20911CBB86DC8F43B02AAC` |

The package passed authenticated API, isolated synthetic Sage RPC worker,
interrupted publication recovery, and native clean/duplicate/persisted/safety
smokes. The ZIP's 206 members passed CRC and its embedded EXE hash matched
the clean build. A unique-AppId QA installer installed into a verified E:
test directory; the installed EXE hash and packaged API smoke matched, then
the QA uninstaller removed its own directory and registration. Defender custom
scans of the bundle, ZIP and unsigned installer found zero attributable
detections. The pinned ZIP and installer were independently downloaded over
HTTP and matched their local hashes.

Artifacts are committed at `codex/coin-prep-fee-approval-artifacts` head
`a004e58fdc324ab32ee7408fa58eb5cd7f79b9aa`:

- ZIP: <https://raw.githubusercontent.com/catalystxch/catalyst-bot/a004e58fdc324ab32ee7408fa58eb5cd7f79b9aa/acceptance-artifacts/CATalyst-dfc53d9-primary-acceptance.zip>
- Installer: <https://raw.githubusercontent.com/catalystxch/catalyst-bot/a004e58fdc324ab32ee7408fa58eb5cd7f79b9aa/acceptance-artifacts/Catalyst-Setup-dfc53d9-1.4.0.exe>

The original TEST 7 profile continues to run the earlier exact `244da2e`
package read-only. This source change has not been launched against that
profile and made no wallet effect. The live wallet lifecycle, active-offer
recovery, both 24-hour windows, secondary acceptance and final review remain
open. PR #220 stays draft; this is not a public-readiness claim.
