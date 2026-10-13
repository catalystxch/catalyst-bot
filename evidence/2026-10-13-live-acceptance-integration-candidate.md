# Dexie-only live acceptance integration candidate (2026-10-13)

This candidate combines the current primary live-recovery evidence/fixes (PR
#261), the bounded CAT Coin Prep and Harvestr pair-confirmation work (PR #264),
the nested Sage Splash offer-view classifier fix (PR #267), and the explicit
Splash bootstrap-peer setting (PR #265). The `bot_gui.html` merge retains the
deliberate same-pair reconfirmation requirement after a stopped campaign. Two
older browser assertions were updated to exercise the current save and pair
contracts.

Independent review then found a recovery dead end: a stopped campaign that
reused prepared coins could still own live offers but had no campaign-bound
Coin Prep approval from which to renew its cancellation fee. The fix freezes a
zero-output, cancellation-only economic recipe for that stopped campaign. Its
fee preview counts the exact durable nonterminal campaign buy/sell offer IDs,
prices their cancellation stages, and rechecks that same ID-to-asset mapping
after pricing. It does not recreate preparation outputs or trading authority.
The reviewer rechecked the fix and found no remaining important authority or
fee-safety issue. The endpoint retry test mocks the cancellation manager, so
it does not itself prove a live wallet cancellation.

## Isolated verification

- Full serial Windows backend: **7,659 passed, 274 skipped, 457 subtests
  passed** (`python -m pytest tests -q --tb=short`).
- Full Chromium browser suite: **273 passed**
  (`python -m pytest tests/e2e -q --e2e --tb=short`).
- Ruff on `src` and `tests`, and `git diff --check`: passed.
- The recovery fix passed **120 related backend tests** and a focused two-test
  red/green regression. The stopped-campaign preview has zero preparation
  transactions, positive cancellation reserve and fee ceiling, and the exact
  approval passes positive-fee cancellation pricing. A stopped campaign with
  no outstanding offers cannot obtain the recovery quote.
- Clean Windows `python build.py` after the recovery fix: passed. Final combined
  `dist/Catalyst/Catalyst.exe` SHA-256:
  `44C1DCB7F9B507024DD261054486F266BB9486CDFF163C61E47F8520BD2C0456`.
- Isolated packaged API, mock Sage RPC, native clean/duplicate/persisted/
  safety first-launch, and interrupted publication recovery smokes passed on
  that final EXE. All
  smokes use temporary data directories and leave both original wallet
  profiles and active test processes untouched.

## Live acceptance boundary

The combined EXE has **not** been run against either original wallet profile.
The primary TEST 7 app remains exact runtime `f03432f5500588588f59de69ef2912a5441f863f`
with its active offer-book monitor. The secondary Harvestr app continues its
bounded six-offer campaign on its prior verified runtime. The Splash offer
texts from primary reached Harvestr byte-for-byte, but the active Harvestr
runtime predates the classifier fix, so live relevant-offer display after the
fix remains unproved. Reverse peer receipt, an independently witnessed offer
take/fill, the final 24-hour active-campaign/end-state gates, and final review
remain open. This candidate and these isolated checks do not establish general
public readiness or authorize replacing the active test processes.

See `evidence/2026-10-13-two-pc-splash-receipt-and-classifier.md` and
`docs/testing/v1.4.0-release-acceptance.md` for the live identity, offer,
monitor, and fee reconciliation detail.
