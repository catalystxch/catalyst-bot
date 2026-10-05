# Secondary-PC Harvestr read-only follow-up

Delegated secondary-PC report for draft PR #220, runtime/source
`b7eab4f263409c0b4c846d6a506b21e16335ee37`. The reporter verified
that PR head `d9c980bebfd30df4138464fdc0c1991f7b8ebd52` changed only
documentation/evidence and matched the pinned source, ZIP, installer, EXE and
UI hashes. The original detailed report and screenshots are held on the
secondary host at
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\2026-10-05-pr220-b7eab4f-harvestr-readonly.md`.

Sage 0.13.0 was started for read-only checks. It reported Chia mainnet,
Harvestr fingerprint `3702373391`, CAT wallet ID `2`, and the exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Balances were `240.800676512155` XCH and `3,381,521.720` MZ, with owned
equal to selectable. There were zero pending transactions and zero active,
unexpired, fillable Sage offers.

The exact package ran only against a lean copy of the Harvestr CATalyst
profile; hashes of the original profile remained unchanged. The copied
profile acquired and released its own lease cleanly. CATalyst reported zero
open offers, locks, current blockers, reservations and unresolved claims. The
bot remained stopped. After UI hydration, Sage was connected, the exact MZ
pair was selected, and the UI prominently warned that the prior Bootstrap
campaign was expired and must be stopped before restart or renewal. Start was
blocked. Market confidence was RED for expired, unavailable or single-provider
evidence. The old `0.1` XCH approval was visible but had
`dispatch_authorized=false`, `held_fee=0`, no pending operation and zero
unresolved operations. It was not reused. No UI/API console error or wallet
effect was observed. CATalyst and Sage closed gracefully after the check.

The secondary native computer-use attachment remained unavailable with
kernel-assets `os error 3`, so the reporter used live local Chromium read-only
UI inspection. This check advances independent identity, recovery-screen and
fail-closed startup evidence; it does not pass secondary original-profile live
trading, active-offer recovery, a 24-hour stability window, or the full native
UI gate. No reproducible CATalyst defect was reported.
