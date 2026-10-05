# Secondary-PC Harvestr read-only follow-up

Delegated secondary-PC report for draft PR #220, runtime/source
`b7eab4f263409c0b4c846d6a506b21e16335ee37`. The reporter verified
that PR head `d9c980bebfd30df4138464fdc0c1991f7b8ebd52` changed only
documentation/evidence and matched the pinned source, ZIP, installer, EXE and
UI hashes. The [detailed report and screenshots](https://github.com/catalystxch/catalyst-bot/commit/bbb0d3443bb8bc6d1ed3a14d4cda317669533e52)
are pinned in the secondary PC's isolated evidence branch. The initial UI
screenshot has SHA-256 `3CD84BC8A39E9F967D32E84E5B8A89AB9F3FDB01FCED479BA91D3CC12F315735`;
the hydrated UI screenshot has SHA-256
`5C042E762C546DA94929CECB8F4D6D4982BABE2B4A8F42A718D54892CE42C208`.

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

During evidence publication, the secondary PC's host-default Python 3.14.3
and pytest 8.4.2 failed the isolated
`test_overrun_recovery_requires_stopped_campaign_and_explicit_intent` fixture:
its synthetic unsigned fee preview returned `FEE_UNSIGNED_COST_UNAVAILABLE`.
The same isolated test passed on that PC in a disposable Python 3.12.10,
pytest 9.1.1 environment (`1 passed in 2.20s`), and passed on the primary
Python 3.12 environment. Repository source instructions and release CI target
Python 3.12. This comparison does not isolate which Python/dependency
difference caused the unsupported-host failure; it did not involve the packaged
runtime or a wallet effect. The 3.14 result is retained as a test-environment
limitation, not counted as a supported-candidate test pass.
