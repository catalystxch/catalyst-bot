# TEST 7 same-limit Bootstrap renewal preview

At 2026-10-04 01:09–01:16 UTC the original TEST 7 profile ran the exact
`aa9b09fcca3da9f7dc5b1b2abfee8aa0988ce1ea` packaged EXE, SHA-256
`51D871486C4F207574D01BEC9521FEEFB8AD1C14144468D1E6039D99B3DD69C8`.
Sage was synced on mainnet with fingerprint `736588221`, CAT wallet ID `2`,
and MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
The bot was stopped, runtime safety allowed, and Bootstrap had no active or
attention-required campaign. Spendable balances were 138.470301476875 XCH
and 780212.284 MZ; there were zero active offers.

The database's prior campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
was stopped. Its recorded terms were one day from 2026-09-29T11:27:42Z,
anchor 0.000075 XCH/MZ, fixed corridor 0.0000375–0.00015 XCH/MZ,
0.9 XCH and 12,000 MZ market budgets, 0.001 XCH campaign fee budget, and
zero subsidy. Its authoritative fee spend remained zero mojos. The prior
fee approval belonged to an older, expired campaign and is not reusable.

Those same limits were entered locally in the native Settings view without
saving configuration. The app's **Preview** action returned `REVIEW ONLY —
no wallet action` for the exact 64-character asset, two-sided liquidity,
0.9 XCH / 12,000 MZ effective budgets, the unchanged anchor and corridor,
10% first-stage deployment, and three buy plus three sell offers. The exact
asset confirmation checkbox remained unchecked, so **Start Campaign** stayed
disabled. The authority selector was restored locally to Follow without
clicking Save & Continue.

An unauthenticated direct POST to the preview route was refused with
`unauthorized`; the review-only preview succeeded through the native UI.
Follow-up API reads found the bot stopped, no active campaign or attention,
unchanged balances, zero active offers, and safety allowed. No new campaign,
fee approval, offer, Coin Prep operation, or wallet transaction was created.

Starting a fresh campaign and any network-fee scope still require separate
operator approval and an exact identity/safety preflight at action time.
The preview is not approval and will need refreshing if balances or settings
change. PR #220 remains draft; live wallet lifecycle and 24-hour windows
remain open.
