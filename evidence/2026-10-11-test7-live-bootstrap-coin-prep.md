# TEST 7 live Bootstrap Coin Prep — 2026-10-11

## Scope and package

- Private v1.4.1 runtime source: `71faf54d39bf31a552e9b9e1f51cba93ab8590c3`.
- Native process: `C:\Users\t_you\.codex\worktrees\coin-prep-predispatch-quote\catalyst\dist\Catalyst\Catalyst.exe`, PID 173740. Executable SHA-256: `512E7514E5D66522B0F6FDA17849DD3CC972E8FD5C731BBF65A9BF50C55221C9`.
- The same executable launched a `--coin-prep-worker` child. The bot stayed stopped during preparation.

## Action-time preflight

- Sage mainnet, TEST 7 fingerprint `736588221`, CAT wallet ID 2, MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Before preparation: 138470301476875 XCH mojos and 780212284 MZ atomic units spendable/confirmed; zero pending transactions; zero open MZ offers in Sage's complete 4,095-offer history and the app database.
- Safety status was `ALLOWED`, with an owned renewing lease and zero unresolved operations, reservations, or publications.
- The native Bootstrap preview showed a 24-hour, two-sided campaign with anchor 0.000075 XCH/MZ, corridor 0.0000375–0.00015, 10 XCH and 100000 MZ budgets, 0.05 XCH campaign fee budget, 10% first-stage deployment, and three offers per side. The operator's exact-asset checkbox was selected only after the full asset ID appeared in the preview.
- Campaign `37750a860f3d26b005d3d894228e011366ad5dabaf1f04b3acd0b04a43a5a790` was saved at revision 0 without a wallet action. Balanced Smart Settings were applied and saved. The app's wide-spread warning was accepted for this thin-market Bootstrap test.

## Coin Prep result

- Native Coin Prep showed 36 XCH targets including six 0.001 XCH fee coins and 30 MZ targets, within the campaign budgets. The Coinset preview identified two preparation transactions, one exact unsigned CAT cost and projected XCH/cancellation costs. The cumulative preparation fee cap entered in the native UI was 0.01 XCH, including protected cancellation allowance.
- Existing P&L and offer history were kept; no reset option was selected.
- The direct-final-output worker completed two confirmed batches at `2026-10-11T08:28:47.051Z`: 66 target coins reused, zero missing, and 14,100,043 mojos (`0.000014100043` XCH) paid. The native UI reported 36/36 XCH and 30/30 MZ ready.
- After confirmation: XCH spendable/confirmed `138470287376832` mojos, exactly 14,100,043 mojos below the preflight; MZ spendable/confirmed `780212284` atomic units. Pending transactions, Sage open buy/sell offers, and database open offers were all zero. The active campaign remained revision 0 with 14,100,043 mojos authoritative fee spend. Safety remained `ALLOWED` with no blockers.
- Native Offers showed zero live offers; P&L retained three historical confirmed buy fills and zero new fills; Logs showed fee scope closure and successful preparation; Dashboard showed coins ready. Market Intelligence showed RED Follow-mode confidence while the bounded Bootstrap campaign remained active. Optional Splash was running but had zero peers, so peer receipt is unverified.

## Remaining

- The bot has not been started, and no live offers have been created or cancelled under this campaign. Action-time confirmation for the native `Start Bot Now` financial action is pending. The buy-only/sell-only cycles, offer recovery, fills, and full stability windows remain open.
