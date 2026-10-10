# Combined candidate: live restart readback — 25 September 2026

Observed during the 03:32 UTC heartbeat, with final policy readback at
`2026-09-25T04:35:25.194802+01:00` (03:35 UTC).

## Exact artifact and identity readback

- CATalyst has reopened independently of this heartbeat. PID `43668` runs
  `candidate-088d9d6-combined-20260924/dist/Catalyst/Catalyst.exe` under this
  plan's isolated workspace. Its freshly recomputed SHA-256 is
  `02F090A74B6E7FA16954B3F5AEAEB3849DE63A67B84F0F3CE6B9B684B1F2A845`.
- `/api/fingerprint` returned success and `736588221`. Startup logs record
  login to that fingerprint; runtime identity reports mainnet. Current CAT
  readback is wallet `2`, MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
  These are app readbacks, not a new signing-boundary identity attestation.
- The bot is stopped: zero loops/errors, zero buy/sell offers, zero locked
  XCH/CAT coins and zero runtime blockers. Existing three historical fill
  records remain visible. Saved counts are 3 buy / 3 sell, tiers disabled,
  XCH/CAT reserve settings both `0`; none were changed by this heartbeat.

## Durable fee recovery

- `/api/coin-prep/status` reports complete, two confirmed operations, zero
  held fees and zero unresolved operations. Approval remains
  `cae3170fdf37da6c24627bc93d6b25d0a7d92df2eecde7443d8e4b2a0fe89a50`.
- Spent is `15562944` mojos, total approved `401997224`, remaining
  `386434280`, protected cancellation `90207400`. Dispatch authority is false.
  This matches the prior live TEST 7 receipt: this restart has not reset or
  double-counted the confirmed fees. It is recovery/readback evidence for the
  combined build, not a new prep transaction on that build.
- Reported balances remain 138.472836570155 XCH and 780212.284 MZ, with
  158 XCH coins and 39 CAT coins. Prep reports 8/8 targets and no tier drift.

## Public data versus trading authority

- The existing read-only `/api/market/intel` path refreshed the public Dexie
  book: age 0.2 seconds, two refreshes, zero errors, source
  `dexie_v3_orderbook`, nine buy and 29 sell offers, bid `0.00004` and ask
  `0.00011` XCH/MZ. No own offers are present. Splash health reports healthy.
- The subsequent confidence response still denies creation/requotes and has
  `data_valid=false`. Its RED assessment remains dated
  `2026-09-24T09:59:42.218421Z`, with expired snapshot/evidence flags in addition
  to the historical depth/provider reasons. Fresh public display data is not
  a newly evaluated, attributable market-policy decision.
- Spacescan context was not loaded in this stopped session. No conclusion
  about its key validity or provider availability follows from that alone.
- A temporary browser inspection confirmed synced Sage fingerprint `736588221`,
  stopped state, disabled empty cancellation and zero errors. This new browser
  session requested pair selection; none was made. The temporary tab was closed
  without interacting with the native window or altering its selected pair.

## Remaining gate and action boundary

The runtime-unavailable blocker is superseded. A new live bot cycle has not
run on this candidate; creation/publication/requote/active-cancel/remake remain
unverified. The next live step is an operator-run Start Bot cycle in the
existing CATalyst window, retaining the saved settings and all safety gates.
Starting the bot can create live offers, so this heartbeat did not perform
that final financial action through either UI or API. Any changed plan or new
fee budget still needs the actual displayed approval workflow.

No startup, signing, spending, offer mutation, fee approval, strategy change,
installed-package replacement, main merge or release was performed here. The
goal is not complete; monitoring remains enabled. Existing full-suite/build
evidence is unchanged and was not rerun merely because the app reopened.
