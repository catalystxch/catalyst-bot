# Live Sage wallet read-only check — 30 September 2026

At approximately 07:50–07:54 UTC, the primary Windows PC's real Sage RPC was
listening on `127.0.0.1:9257` as `sage-tauri.exe` PID 110428. The exact
CATalyst `1db16bd3bed145334fe9463664b7d633426709cb` application was not
running, and port 5000 had no listener. The feature branch was at evidence-only
head `f25cfa2b3c22312979fdaaa60a336efacd88bc94`; its tracked diff from
the exact source commit contained only acceptance documentation and evidence.

A separate Python process imported CATalyst's `wallet` facade from that source
checkout and used only its dedicated read methods. The first generic `rpc`
attempt for `get_cats` was refused by the facade's identity safety gate, so the
check used `get_wallets`, `get_wallet_balance`, and
`get_authoritative_offer_history` instead. It did not connect a CATalyst
browser session, acknowledge Risk Disclosure, dispatch a transaction, create or
cancel an offer, or start the bot.

| Check | Observed result |
| --- | --- |
| Sage identity | `sage`, Chia `mainnet`, fingerprint `736588221` |
| Sage health | reachable and synced |
| Trading CAT | wallet ID `2`, Monkeyzoo Token (`MZ`), exact asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105` |
| Discovery | Sage-backed `get_wallets` returned nine wallets, including the exact MZ wallet |
| XCH balance | confirmed and spendable `138471036900675` atomic units |
| MZ balance | confirmed and spendable `780212284` atomic units |
| Sage offer history | complete local table, 4,040 records: 3,271 cancelled, 231 expired, 538 completed; zero active offers |
| Pair classification | zero open MZ/XCH buys and zero open MZ/XCH sells |
| CATalyst database | zero open rows for the exact MZ asset |

The persisted active Bootstrap campaign was
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`,
bound to that mainnet fingerprint, Sage wallet ID 2, and asset. It was still
stored as active, expires `2026-09-30T11:27:42.748405Z`, and retained its
0.9 XCH / 12,000 MZ market budgets, 0.001 XCH fee budget, and zero subsidy.
The database reported zero authoritative fee spend for this campaign and no
Coin Prep fee approval for it.

Prior fee approval
`c6651480f6044dbbd2833926d3809380c248943f7f507991ff132d7e885e6bdc`
remained bound to expired campaign
`aaf64855aef9e1919d7cdfd4b15c1f589e7acf9321d71787b0b8122df9e16405`:
561,860,690 mojos total, 62,703,765 spent, zero held, 499,156,925 remaining,
eight confirmed operations, and zero unresolved operations. It is not an
approval for the active campaign.

This is live wallet and persisted-state evidence only. The exact packaged
application has not run against the primary profile, and its Coin Prep, offer
creation/publication, restart recovery, live lifecycle, and 24-hour stability
gates remain unverified. PR #220 remains draft; no release-readiness conclusion
follows from this check.

## Separate older-source Coin Prep on the shared wallet

At approximately 08:31 UTC, port 5000 became occupied by a separate Codex
task's `python desktop_app.py --flask` process from `C:\catalyst`, branch
`codex/dashboard-live-balances`, source commit
`15f6aab76327b569bbc100e43b54e09a63c6a77d`. Its `/api/health` identified
version `1.2.64+1.g15f6aab`, a stopped bot, and a synced Sage wallet. Its
missing `/api/bootstrap/status` route also showed that it was not the exact
PR #220 candidate. The other task was warned that the wallet and primary
profile may be shared, and that this older runtime cannot supply PR #220
acceptance evidence.

That task reported it had already started Coin Prep on the live TEST 7 wallet.
Read-only `GET /api/coin-prep/status` at 08:38 UTC showed worker PID 18004 in
CAT consolidation. The older worker targeted 106 XCH and 56 CAT tier coins,
with reported tier pools of 92.02589 XCH and 575,237.146 MZ. Those quantities
are outside the separate active PR #220 Bootstrap campaign's 0.9 XCH and
12,000 MZ market budgets. This older Coin Prep is therefore not evidence that
the bounded campaign was prepared or safe to start. Its log reported CAT
self-send fees of 52,316,400 and 26,158,200 mojos, then a follow-up self-send
fee of 13,079,100 mojos. The other task cancelled Coin Prep through its UI at
09:41 local, before an XCH split or offer creation, and reported that it would
make no further wallet writes from the older runtime.

An independent read-only Sage recheck at approximately 08:43 UTC found the
correct mainnet fingerprint, 219 owned and selectable XCH coins totaling
138,470,945,346,975 mojos, and one owned and selectable MZ coin totaling
780,212,284 atomic units. These sums matched the reported confirmed and
spendable wallet balances. XCH had decreased by exactly 91,553,700 mojos from
the pre-Coin-Prep check, equal to the three logged CAT self-send fees. Sage's
complete 4,040-record offer history still had zero open MZ/XCH buys and sells;
the CATalyst database still had zero open MZ offers. The active PR #220
campaign still reported zero authoritative fee spend and no fee approval.
The prior campaign's approval still reported 62,703,765 mojos spent, zero
held, and zero unresolved operations. Worker PID 18004 was gone.

These were wallet effects from the separate older-source test, not from the
exact PR #220 candidate. Any later candidate preflight must use the fresh
wallet balances and must not attribute or reuse the older test's fees or the
expired campaign's approval.
