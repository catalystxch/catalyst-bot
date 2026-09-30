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
