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

This UI source correction is not in the running `370776e` package. Its exact
source commit, full browser result, and rebuilt package must be recorded
before new package acceptance. Live wallet lifecycle, restart/recovery, both
24-hour windows, secondary acceptance, and final review remain open. PR #220
stays draft; there is no main merge, tag, release, or public-readiness claim.
