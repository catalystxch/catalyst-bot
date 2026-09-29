# Primary protected cancellation and exact `fd16401` runtime handoff

## Operator cancellation and authoritative outcome

On 2026-09-29 the operator personally confirmed the protected Cancel All
action in the primary CATalyst browser. The bot was stopped. Sage had five
active campaign offers, two buys and three sells; a sixth offer had already
expired in Sage but remained open in the local database. The user-facing
confirmation had been refreshed to show the five active offers before the
operator acted. The agent did not submit the consequential wallet action.

The exact `bf1abe2` live runtime reported its cancellation starting at
`2026-09-29T12:00:25.994045+01:00` and finishing at
`2026-09-29T12:04:52.685208+01:00`. `/api/offers/cancel_all/status` reported
`phase=complete`, five authoritatively terminal offers, two batches, zero
pending, zero failed, and no error. Sage then reported zero open offers.
The database still had only the previously expired inner buy open:
`6fe38e0f59c687d4bfd24857725ba25e55eff0ebffda58622be0ec00c89f297f`.

The unchanged Task 9 reconciliation code was run against that exact trade ID.
Its read-only Sage evidence classified the offer `EXPIRED_PROVEN` with
`AUTHORITATIVE_EXPIRY_PROOF`; `reconcile_offer` applied the guarded terminal
transition. This was a database reconciliation with no wallet transaction.
Subsequent diagnostics showed zero wallet buys/sells, zero database buys/sells,
no `stale_in_db` or `wallet_only` rows, and `local_book_consistent=true`.
All six offers from the final wave had authoritative terminal records: five
`CANCELLED_PROVEN` and one `EXPIRED_PROVEN`.

Fee approval `c6651480f6044dbbd2833926d3809380c248943f7f507991ff132d7e885e6bdc`
remained within its approved scope: total 561,860,690 mojos, cumulative spent
62,703,765 mojos, held zero, remaining 499,156,925 mojos, eight confirmed
operations, and zero unresolved. The two cancellation batches increased
confirmed spending by 2,513,679 mojos from the previous checkpoint. The
safety gate allowed readback with zero blocker counts.

With zero campaign trade IDs remaining, `/api/bootstrap/stop` stopped the
expired campaign with `cancel_targets=0` and no wallet effect. A fresh status
read returned no active campaign; the bot remained stopped and both offer
books remained empty. No replacement campaign was created.

## Exact candidate on the primary profile

The old exact `bf1abe2` EXE was shut down through authenticated
`/api/shutdown` with `cancel_offers=false`. PID 64944 exited and port 5000
closed. With the app stopped, six critical profile files were copied to
`C:\catalyst\.superpowers\primary-profile-pre-fd16401-20260929-1109`.
The source and backup `bot.db` each hashed
`414105951B4AC90126CF2FF627A95C32A8F2F29C4DC4273B1FEC79139BB5C843`.
The original profile was left in place.

The exact detached-build candidate
`C:\catalyst\.superpowers\public-ready-fd16401\dist\Catalyst\Catalyst.exe`
then started against that profile as PID 108660 and owned port 5000. Its
SHA-256 matched the acceptance package:
`4455ABD51C6FE787FD424F2F8D38FF815DDE1A6A2D277A0F649BAD39AAE9C291`.
Read-only status reported version 1.4.0, bot stopped, Sage mode, persisted
mainnet fingerprint 736588221, CAT wallet ID 2, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
zero wallet and DB offers, unchanged fee ledger, and safety allowed with zero
blockers. The new app session's `/api/fingerprint` reported `not_started`:
Sage has not been connected through the new browser session. After browser
reload, the exact candidate showed Risk Disclosure; it was not acknowledged
by the agent. The new frontend showed the corrected expired-campaign guidance
before the old campaign was stopped and later refreshed to no active campaign.

## New campaign preview, no activation

A read-only bootstrap preview for the same MZ/XCH caps succeeded on the new
runtime: 24 hours, anchor 0.000075 XCH/MZ, corridor 0.0000375–0.00015,
market budgets 0.9 XCH and 12,000 MZ, fee budget 0.001 XCH, subsidy zero.
It returned `authorized=true`, `TWO_SIDED`, initial three buys and three
sells, a 0.1 deployment fraction, 0.0002 XCH cancellation fee reserve and
0.0001569492 XCH estimated creation fees. The preview returned
`financial_action_started=false`; no campaign was created. The operator has
been asked separately to approve this exact new campaign and personally
acknowledge the Risk Disclosure before wallet connection. Primary and
secondary exact-candidate live trading and 24-hour windows remain unverified;
draft PR #220 remains unmerged, untagged and unreleased.
