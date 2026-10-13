# Two-PC Splash receipt and classifier finding, 2026-10-13

This is read-only evidence from the ongoing TEST 7 and Harvestr original-profile live test. It does not establish bidirectional peer delivery, successful MZ classification, or full release readiness.

## TEST 7 publication

The primary process remained the sole port-5000 owner: PID `171260`, exact EXE SHA-256 `378E7F36ED914F2344F04DEE9F502044660AAB9AEBD76ABEB95A57D74A5A55A3`, source `f03432f5500588588f59de69ef2912a5441f863f`. Its prior bounded Bootstrap campaign had expired and stopped. At about `03:25Z`, its still-running ordinary bot lifecycle created one MZ buy (`376406992d61590c83092ec392348d347871c0e37d840ec042d42a2dfd268ecf`) and one MZ sell (`4d9e0b37ba019ba18e5bfb409adf588c2c54fd6477a9ec307b89cfb92836c8c7`). Both local offer rows were open and Dexie-posted.

The durable Dexie and Splash publication outbox rows succeeded. Their offer fingerprints were `fb776e7058db5fe35bacd130d9da1ebf238fbeb8398e16b2094b9bceab0de171` for the buy and `c790a130e8c1731fc1819089baa99ef1274a7ae18f1cdba2bb9db3e2dd034bd0` for the sell. The local Splash daemon reported two broadcasts, zero peers and zero received offers. At `03:31Z`, the app health endpoint reported a running bot and synced Sage wallet; the safety lease was owned and renewing.

At about `03:40Z`, an independent public Dexie API read of `GET /v1/offers/{id}` returned `success: true` and status `0` (active) for both offers. The buy ID `HvcxZHxT52GdGunaq3Pvqt2xLrQri3a1VYFjmR8VgX12` offered `0.25001 XCH` for `3,707.971 MZ`; the sell ID `ES23Vq37KKfNZVHZUYTf8JimPNMyhqfZ2BcHwne32Vhh` offered `3,027.671 MZ` for `0.25001 XCH`. Dexie returned the exact selected MZ asset ID `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105` in the corresponding CAT leg of each offer. This corroborates live marketplace discovery and terms independently of the local publication acknowledgement.

At `03:41Z`, a separate read through the exact runtime's wallet facade identified Sage mainnet `TEST 7`, fingerprint `736588221`. Both exact trade IDs returned a complete authoritative Sage read with status `active`: the buy offered `250010000000` XCH mojos for `3707971` MZ atomic units, and the sell offered `3027671` MZ atomic units for `250010000000` XCH mojos. There were zero pending transactions. Confirmed balances were `138470190098731` XCH mojos and `780212284` MZ atomic units, matching the prior end-state baseline; selectable balances reflected locked offer collateral. Thus the two live terms agree across CATalyst, Sage and Dexie at this observation time. Future fills, expiry, cancellation and recovery still require separate checks.

The primary native window's accessibility tree showed its Offers tab with one buy and one sell, the same terms and trade IDs, and both Dexie links. Windows Graphics Capture returned a black image twice, including after window activation; a state-derived accessibility click failed with an out-of-bounds point and was not retried. This establishes the rendered accessibility content but leaves the current visual primary GUI state unverified. It does not by itself prove an application renderer crash.

## Harvestr receipt and classification

Independent read-only inspection of Harvestr's original-profile `splash_incoming_offers` table found rows `848761` and `848762`, received at `03:25:37Z` and `03:25:38Z`. Each stored offer text recomputed to the corresponding TEST 7 outbox fingerprint above. This proves exact primary-to-Harvestr Splash intake receipt of both offer texts. The inbound rows had `source_ip=127.0.0.1`, the local Splash hook, so they do not identify the network route or prove a direct LAN connection. Publication ACKs were recorded later, at `03:25:44Z` and `03:25:46Z`; these are separate pipeline timestamps.

Neither offer was classified as the selected MZ pair: both were marked `unknown` / `ignored`. Read-only inspection of the Sage response showed valid MZ/XCH maker/taker arrays nested under an `offer` object. The receiver's normalizer considered `offer.summary` but skipped the nested `offer` object itself. A focused tests-first regression fix is being prepared in an isolated worktree, with no live-app change.

Harvestr's six live offer fingerprints were provided for a reverse check, but TEST 7's inbound table still had zero rows at `03:30Z`. Bidirectional receipt and correctly classified market display remain open.

## New observation window

A separate read-only 60-second exact-PID/hash monitor for the ordinary live-offer period began at `2026-10-13T03:31:15.7798232Z`: `E:\catalyst-stability-monitor-f03432f-normal-20261013\trace-60s.jsonl`, monitor PID `124044`. Its first sample recorded PID `171260` alive, bot running, Sage synced, safety allowed and the lease owned. This new window has no 24-hour credit yet and does not replace the missing full-day active Bootstrap campaign test.
