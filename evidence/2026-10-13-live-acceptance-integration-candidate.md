# Dexie-only live acceptance integration candidate (2026-10-13)

This candidate combines the current primary live-recovery evidence/fixes (PR
#261), the bounded CAT Coin Prep and Harvestr pair-confirmation work (PR #264),
the nested Sage Splash offer-view classifier fix (PR #267), and the explicit
Splash bootstrap-peer setting (PR #265). The `bot_gui.html` merge retains the
deliberate same-pair reconfirmation requirement after a stopped campaign. Two
older browser assertions were updated to exercise the current save and pair
contracts; no production code was changed to satisfy those assertions.

## Isolated verification

- Full serial Windows backend: **7,659 passed, 274 skipped, 457 subtests
  passed** (`python -m pytest tests -q --tb=short`).
- Full Chromium browser suite: **273 passed**
  (`python -m pytest tests/e2e -q --e2e --tb=short`).
- Ruff on `src` and `tests`, and `git diff --check`: passed.
- Clean Windows `python build.py`: passed. Combined `dist/Catalyst/Catalyst.exe`
  SHA-256:
  `88D36B7B91246FCA75C3ED66EE3FE6E89C10D482915B2160B259DCABF5000C27`.
- Isolated packaged API, mock Sage RPC, native clean/duplicate/persisted/safety
  first launches, and interrupted publication recovery smokes: passed. The
  smokes used temporary data directories and did not replace either original
  test-wallet process.

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
