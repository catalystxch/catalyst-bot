# Primary TEST 7 live stop and Bootstrap UI state

At 2026-10-03 20:03–20:20 UTC, the original TEST 7 profile ran the clean
`370776e53b957c57e3b77ed12b4060f540b22521` Windows EXE at
`E:\catalyst-lease-6298872-build\dist\Catalyst\Catalyst.exe` (SHA-256
`13BB1838887876FDD8C701F555B54BBF2A4498B2F65B557B3FD80313B94968C0`).
PID 14672 owned the `127.0.0.1:5000` listener. The operator explicitly
authorized the Risk Disclosure acknowledgement for testing; it was accepted
in the native UI before connecting Sage fingerprint 736588221 and MZ/XCH.

Read-only preflight showed Sage mainnet, CAT wallet ID 2, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, stopped bot, zero pending transactions, zero open MZ offers,
and no unresolved mutation blockers. Spendable balances were
138470301476875 XCH mojos and 780212284 MZ atomic units. The expired
campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
had zero campaign-owned open offers, zero authoritative fee spend, and no
campaign fee approval. Two live reads of the durable lease found exactly
30.0 seconds between heartbeat and expiry; runtime safety stayed ALLOWED.

The expired campaign was stopped through Settings after the native confirmation
explicitly stated that there were no campaign-owned offers to cancel. The app
reported a successful stop. `/api/bootstrap/status` then returned
`active=false`, `campaign=null`, and no stopped-cancellation attention. The
database recorded the campaign as stopped at
`2026-10-03T20:13:54.757259Z`. Follow-up reads found zero open MZ offers,
zero pending Sage transactions, unchanged spendable XCH/MZ balances, zero
authoritative fee spend, no fee approval, and a 30.0-second lease. There was
no wallet transaction or fee effect. No replacement campaign was started.

The live UI exposed a state bug after the stop: Settings still displayed
“Bootstrap campaign active” in Coin Prep Summary and retained campaign-bound
amounts, while the campaign status correctly said no active campaign. The top
banner also said “Follow mode” while the Settings authority selector remained
Bootstrap. A focused Chromium regression reproduced the stale summary before
correction. The source fix clears the Coin Prep amounts, shows that Bootstrap
has no active campaign, and refreshes the preview when active status becomes
inactive. The previously passing active-campaign behavior is retained.
The focused stop regression failed before each correction and passed after;
all 209 Chromium E2E tests passed on the corrected source. The 15 focused
Bootstrap cancellation/recovery browser tests, 12 Bootstrap UI contract
tests, Ruff check/format, and `git diff --check` also passed.

The correction was committed as `aa9b09fcca3da9f7dc5b1b2abfee8aa0988ce1ea`.
All 11 PR checks passed. A clean detached EXE at
`E:\catalyst-bootstrap-ui-aa9b09f-build\dist\Catalyst\Catalyst.exe` has
SHA-256 `51D871486C4F207574D01BEC9521FEEFB8AD1C14144468D1E6039D99B3DD69C8`;
its bundled UI hash `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6`
matches the exact source HTML. The ZIP hash is
`12FC674BFFCCA37A1154C4289E40B69C4002ABEB5306788652F3AFE36FDB5D5C`,
and the unsigned installer hash is
`19D5766F57338A683E9546F258B5C1DCB0B95CF7957E100394D0503B0BB664DE`.
Packaged API, synthetic Sage RPC, publication recovery, ZIP CRC/extracted API,
unique-AppId isolated installer clean install/installed API/uninstall, and
Defender custom scans passed. The installed EXE matched the clean build; the
isolated QA executable and registration were absent after uninstall. Fresh
HTTP downloads of the pinned binaries matched their hashes:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/365089930065a04b4cf82e3e059bff0d66a0a770/acceptance-artifacts/CATalyst-aa9b09f-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/365089930065a04b4cf82e3e059bff0d66a0a770/acceptance-artifacts/Catalyst-Setup-aa9b09f-1.4.0.exe)

This UI correction is not in the running `370776e` package. Live acceptance
of the new exact package, wallet lifecycle, restart/recovery, both 24-hour
windows, secondary acceptance, and final review remain open. PR #220 stays
draft; there is no main merge, tag, release, or public-readiness claim.
