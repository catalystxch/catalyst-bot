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

At 2026-10-04 19:00–19:13 UTC, the original TEST 7 profile's prior `244da2e`
app was shut down through its native UI with offer cancellation unchecked;
its process and port listener exited. The exact `dfc53d9` clean EXE was
launched through the native desktop, and testing Risk Disclosure was
acknowledged under the operator's standing authorization. Sage TEST 7
fingerprint `736588221` and MZ/XCH were selected. PID `144124` was the sole
CATalyst process and owned the `127.0.0.1:5000` listener. Its executable
path and SHA-256 matched the clean build above.

Read-only live checks showed mainnet Sage, CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, stopped bot, 138.470301476875 spendable XCH and 780212.284
spendable MZ, zero open buy/sell offers, and zero Sage pending transactions.
Runtime safety was ALLOWED with no mutation blockers and a renewing 30-second
lease. Bootstrap status had no active campaign or attention. The previous
campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remained stopped with zero authoritative fee spend. The native dashboard
showed TEST 7, MZ/XCH, bot stopped and RED market confidence; no trading or
campaign action occurred. These are initial live restart observations, not
the live wallet lifecycle or a 24-hour stability pass.

The live wallet lifecycle, active-offer recovery, both 24-hour windows,
secondary acceptance and final review remain open. A new campaign and fee
scope are awaiting separate operator approval. PR #220 stays draft; this is
not a public-readiness claim.

At 19:16–19:18 UTC, the exact packaged native window was traversed without
mutation across Dashboard, Offers, P&L, Market Intel, Settings, Logs, Data
Reset, Help, and About. Offers showed zero active buy/sell rows and three
historical confirmed buys. P&L showed those three verified fills and zero
pending verification. Market Intel correctly showed RED confidence with no
attributable tradable depth; Settings showed the selected fingerprint and
runtime safety ALLOWED. Logs backfilled the current Sage startup, TEST 7
selection, MZ pair switch, and later order-book refresh. Reset controls were
only observed, not activated. A follow-up check still found a stopped bot,
no active campaign, zero open offers, zero Sage pending transactions,
unchanged balances, and safety ALLOWED. This covers read-only tab rendering
and live log backfill; interactive wallet/offer flows remain open.

At 19:25–19:32 UTC, an isolated same-version installer upgrade was exercised
on E: using the unchanged `installer.iss` and a dedicated QA AppId
`6D7D5CB2-A8A9-4E57-8564-24B67C9243DD`. The QA install directory and
uninstall registration were absent before the run. The prior `aa9b09f`
payload installed with EXE SHA-256
`51D871486C4F207574D01BEC9521FEEFB8AD1C14144468D1E6039D99B3DD69C8`.
An in-place upgrade to the exact `dfc53d9` payload exited zero and replaced
the EXE with SHA-256
`B38EF8FE8CC232EBD56093A5442D84D8669E416BCE19B3E48F1A9075BD6F812D`.
Rollback to `aa9b09f` and restore to `dfc53d9` each exited zero and yielded
the corresponding exact EXE hash. After restore, all 192 installed payload
files matched the detached source bundle by relative path and SHA-256; there
were zero missing, changed, or extra payload files. The QA uninstaller exited
zero and removed the verified E: install directory and its own HKCU registry
entry. The original TEST 7 `dfc53d9` process remained the sole CATalyst
process, with stopped bot, unchanged balances, zero open offers, and runtime
safety ALLOWED. This validates the isolated installer upgrade/rollback path;
it does not validate an in-app update on the original live profile.
