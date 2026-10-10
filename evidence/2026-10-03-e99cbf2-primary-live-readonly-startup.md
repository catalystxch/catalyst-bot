# Exact e99cbf2 primary live startup: read-only checkpoint

At approximately 2026-10-03 13:54 UTC, the operator had manually started the
detached Windows build against the original TEST 7 profile. The app was past
its disclosure screen and reported Sage connected; the disclosure click itself
was not independently observed. The running `Catalyst.exe` PID 72916 was at
`E:\catalyst-e99cbf2-primary-build\dist\Catalyst\Catalyst.exe`; its SHA-256
was `5AB44677B4EE7B610718527A9B75C328EF451254A88F97BB5512988749645D7E`.
The same PID listened on `127.0.0.1:5000`. This identifies runtime/source
`e99cbf263ae77929b6ccdb7a9874b78be2566dda`, not the evidence-only PR
head `da678c4b5b93019540bc276e571fdf649169fe3a`.

Read-only local GETs of `/api/health`, `/api/sage/startup-status`,
`/api/status`, `/api/bootstrap/status`, `/api/safety/status`, and
`/api/coin-prep/status` showed:

- Sage `0.13.0` supported, startup phase `ready`, healthy wallet, mainnet
  fingerprint `736588221`, CAT wallet ID `2`, and exact MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Bot stopped. Spendable/total balances were 138.470301476875 XCH and
  780212.284 MZ, matching the earlier live baseline. The app's offer
  lifecycle showed zero open buy/sell offers and zero pending cancels.
- Runtime safety was allowed with zero blockers for operations, prepared
  creations, publication claims, reservations, submitted cancels, and
  contradictory history. The process owned the active mutation lease.
- Prior campaign
  `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
  remained stored `active` but expired at
  `2026-09-30T11:27:42.748405Z`. Its offer and unresolved creation counts
  were zero, and its recorded fee spend was zero. The campaign's original
  0.9 XCH / 12,000 MZ market budgets, 0.001 XCH fee budget, zero subsidy,
  0.000075 anchor, and 0.0000375–0.00015 corridor were unchanged.

Independent read-only Sage facade calls returned zero pending transactions and
the complete 4,095-offer history: 3,326 cancelled, 231 expired, and 538
completed; there were zero fillable offers. The original profile database
returned zero open MZ offers. Its read-only fee ledger returned zero
authoritative mojos spent and no Coin Prep fee approval for the expired
campaign. No new campaign or approval was created.

The native CATalyst window showed the selected TEST 7 fingerprint and MZ/XCH
pair, a stopped bot, an explicit expired-campaign banner, and a disabled
Start Campaign control. The Settings view retained the original campaign's
budgets and displayed a Stop Campaign button; it was not pressed. The
historical exact-asset confirmation checkbox was checked while that campaign
remained active. Source review confirmed it is cleared when the active
campaign transitions to no active campaign, and Start Campaign also requires
a fresh preview digest. No UI control that could mutate the wallet or
campaign was pressed.

This checkpoint establishes exact-package startup and read-only live
identity/safety presentation on the original primary profile. It does not
establish a new approved campaign, Coin Prep, offer creation/cancellation,
restart recovery, a full interactive UI pass, 24-hour windows, secondary
acceptance, or public readiness. PR #220 remains draft.
