# Two-PC GUI truth and offer-card display corrections — 2026-10-13

This is evidence for draft PR #268. It does not replace exact-binary original-profile acceptance or assert general public readiness.

## Observed native state

- On Harvestr, the original-profile CATalyst app completed a read-only native traversal of Dashboard, Offers, P&L, Market/Splash, Settings (Live, Setup and Smart), Logs, Data Reset, Help and About. The running Bootstrap book showed three buys and three sells; Sage, the local offer DB and public Dexie agreed on all six IDs. P&L showed zero verified fills. The Data Reset actions were disabled while the bot ran. No wallet or settings action occurred during this traversal.
- The primary TEST 7 app continued to run a one-buy/one-sell Follow book. Its native WebView remained visually black in capture, despite a populated accessibility tree and healthy backend. A read-only desktop capture showed the black CATalyst rectangle over otherwise visible Chrome and Excel pixels. A primary full visual tab pass remains open.
- Splash peer-to-peer receipt remains open: Harvestr had peers and general received traffic but no attributable peer receipt for the primary offers; the primary had zero peers. A private inbound GlassWire block for the primary Splash executable was observed but not changed.

## Three Harvestr display discrepancies

1. The Dashboard's `Max Offers` line showed Follow configuration `0 buy / 3 sell` while the separately approved active Bootstrap campaign actually had `3 buy / 3 sell` offers. The backend was reading `cfg.MAX_ACTIVE_BUY_OFFERS/SELL_OFFERS`; it was not a trading limit failure. The panel now labels those values `Follow Limits` while Bootstrap is active, and its tooltip points to Active Offers for the live book.
2. The Offers cards rounded a planned decimal CAT size one atomic unit above the exact Sage offer. For example, a buy displayed `101,380.117 MZ` instead of the authoritative `101,380.116`, and a sell displayed `95,486.667` instead of `95,486.666`. A read-only join of the confirmed Sage trade IDs to the immutable `offer_intent_economic_authority` showed requested `101380116` CAT atoms for the buy and offered `95486666` CAT atoms for the sell, with three decimals. The UI authority snapshot now carries economics only when the existing token, prepared-journal and revocation validation accepts it. The card uses those exact atoms for its CAT display. No offer amount or wallet mutation code changed.
3. The Coins summary presented its filtered tracked count as though it included every Sage-owned coin. The DB intentionally excludes validated spent outcomes and protected effect claims. The tooltip now states the tracked usable scope and exclusions; the safety filter is unchanged.

## Verification and remaining gates

- The focused new regression tests failed before the source change and passed after it. The adjacent Python API tests passed: 187 tests and 4 subtests. Chromium smoke passed: 106 tests. Ruff and `git diff --check` passed.
- The full local suite and PR checks for this display commit are pending at the time of this note. The previous PR head `02567b7c4b538f3eabe575128be985ef3c2f22dd` had all 11 checks green.
- Both original-profile live apps still run their earlier pinned binaries. The display fix is source-only until a new exact package is built, verified and deliberately adopted. The pending cross-wallet Sage Take Offer still requires the specific final-click answer. Splash peer receipt, the primary visual pass and final-candidate 24-hour end-state audits remain open.
