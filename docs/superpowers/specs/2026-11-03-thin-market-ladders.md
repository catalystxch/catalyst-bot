# Thin-market continuous ladders

## Intent

Run one independent, continuous MZ/XCH Follow ladder on each of the user's two original-profile PCs. Each ladder targets 24 BUY and 24 SELL passive offers, uses the wallet's safely available XCH and MZ across offers, trading reserves and fee coins, replenishes and requotes automatically, and resumes after a restart when the correct wallet is synced. Both PCs must use one verified build. Verify both ladders for 48 hours; they continue trading afterwards.

The current Chia MZ market is thin. CATalyst must be able to add liquidity when a user has chosen to trade in a thin/RED market. A low depth rating alone must not cause an empty ladder or progressive withdrawal.

## Market behavior

- Smart Settings offers an explicit thin/RED-market choice. The choice is bound to the intended wallet and MZ/XCH pair, persists across restarts, and remains in effect until the user changes it. It is a market-policy choice, not wallet-effect authority.
- Pricing uses current reliable external evidence when available. CATalyst excludes its own offers from the reference. If no new reliable price is available, a previously reliable price may seed quotes for at most 24 hours. Strongly conflicting sources, invalid price data, manipulation evidence or an absent/older anchor pause new and replacement offers. Existing offers remain open when the price anchor ages out; unknown wallet effects still follow their existing recovery path.
- Smart Settings derives price range, spread, spacing and offer sizes from the wallet and market. No fixed absolute MZ price band is required for thin-market consent. BUY and SELL prices retain a positive spread that covers expected trading costs. The bot remains passive: it creates its own offers and does not accept others' offers.
- The bot automatically cancels and replaces offers as the market moves, using the existing safe requote lifecycle. It rebuilds toward 24/24 after fills or expiry. Short-lived under-target counts are acceptable; when an asset cannot fund 24 valid offers, post as many valid offers as possible and shrink per-offer size where supported.
- The same thin/RED choice stays effective if confidence remains RED or becomes RED after launch. A RED rating caused solely by weak liquidity or provider count does not trigger repeat prompts or progressive cancellation. Other genuine wallet, transaction, identity, price-integrity and recovery faults retain their guards.

## Fee coins

- Smart Settings obtains a current network fee estimate and sizes a fee-coin batch for about one week of expected Coin Prep, offer maintenance and cancellation activity. Fee-coin principal stays in the user's wallet; actual network fees are accounted separately.
- The existing tier top-up mechanism replenishes fee coins automatically when low and grows the denomination if network fees rise. If a fresh fee estimate is unavailable, the last successful estimate with a safety margin can size fee coins. A stale estimate alone does not authorize a wallet transaction; exact wallet-effect pricing and sufficient spendable XCH still apply.
- No user-selected or cumulative fee-spending cap is part of this operating mode. The prior reference to “1” meant step one of the fee process, not 1 XCH. Remove the old cumulative ceiling as a Follow/Coin Prep stopping point without erasing historical fee records or weakening exact transaction, wallet-identity and pending-effect checks.

## Startup and acceptance

- After a PC or CATalyst restart, resume the same intended ladder automatically only after verifying the correct Sage wallet, mainnet, sync, saved pair, live balances, outstanding offer state, market policy and safety latches. Do not duplicate offers or repeat a pending wallet effect.
- Establish and verify 24 BUY and 24 SELL offers on this PC first. Then transfer the exact verified build to the second PC and establish the independent 24/24 ladder there.
- Record actual Sage, database, GUI and process evidence from both original profiles. Monitor both ladders for 48 hours, including refills, requotes, fills and restart recovery where observed. The ladders remain on after the observation period.

## Boundaries

- Keep Decimal amounts and integer mojos, use the wallet and database adapters, and preserve the mutation lease and exact wallet-effect journal.
- No direct database repair, raw Sage mutation or blind retry of unknown effects.
- Historical fee spending remains visible even though this operating mode has no cumulative spending cap.
- Keep release work on a feature branch and PR into main; verify the built artifact and tests before live use.
