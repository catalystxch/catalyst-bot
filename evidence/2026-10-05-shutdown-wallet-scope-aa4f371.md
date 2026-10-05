# Shutdown wallet-scope acceptance evidence

Date: 2026-10-05 (Europe/London)

## Identity

- Target branch: `codex/coin-prep-fee-approval`
- Verified target head: `aa4f371c13d4ae8b3b6b74ab0f421cd40db2ce30`
- Fix branch: `codex/shutdown-wallet-scope`
- Fix commit before this evidence commit: `4188725943a6e8d09e6e2393660424df490d06b3`
- Scope: shutdown consent and leave-open status copy only, plus focused backend/Chromium regressions

## Confirmed defect

The shutdown dialog described its optional Cancel All action as cancelling offers "on Dexie" and its leave-open result could state "No open offers were left behind" from CATalyst-tracked rows alone. The backend operation is wallet-wide: it covers all currently active offers in the connected Sage wallet, across assets, including manual or otherwise untracked offers. The old text understated the destructive scope and overstated the authority of the tracked-row summary.

## Fix

- The checkbox, warning, reset state and progress copy now say that Cancel All covers all currently active offers in the connected Sage wallet, including manual/untracked offers.
- Dexie-only wording was removed.
- Leave-open summaries are explicitly limited to CATalyst-tracked visibility and disclose that untracked Sage offers may remain.
- "Currently active" is intentional: Cancel All acts on a complete wallet snapshot and does not promise to catch an external offer created after that snapshot.

## Test-first proof

The two new/changed regressions were run before the production copy change and failed on the prior behavior:

- `test_shutdown_offer_disposition_qualifies_catalyst_tracked_visibility`
- `test_shutdown_cancel_consent_names_wallet_wide_untracked_scope`

After the fix and after rebasing onto `aa4f371c13d4ae8b3b6b74ab0f421cd40db2ce30`:

- Focused backend regression: 1 passed
- Focused Chromium regression (`--e2e`): 1 passed
- Ruff: all checks passed
- Complete backend suite: 7,206 passed, 220 skipped, 431 subtests passed, 4 warnings, 0 failed; 611.95 seconds
- Complete Chromium E2E suite: 219 passed, 0 failed; 143.02 seconds
- `git diff --check`: passed

## Fresh Windows build

Command: `py -3.14 build.py`

- Python: 3.14.3
- PyInstaller: 6.22.3
- Result: BUILD SUCCESSFUL
- Executable: `dist/Catalyst/Catalyst.exe`
- Executable SHA-256: `11D9D174B14FFE1193AE9DDE9801CE986FEFE0094C7DB5D7F3431C3ACD17A6B1`
- Source `bot_gui.html` SHA-256: `467C43263591E252CA3156CF3103C9A0BD92E62FF75132E31A21D5301EB017BC`
- Bundled `_internal/bot_gui.html` SHA-256: `467C43263591E252CA3156CF3103C9A0BD92E62FF75132E31A21D5301EB017BC`

Packaged checks against that executable:

- API smoke: passed
- Mock Sage RPC worker smoke: passed
- Upgrade/publication recovery smoke: passed
- Clean launch, duplicate-launch handoff, persisted relaunch and native safety launch smoke: passed

## Wallet/profile safety

No live wallet action was performed for this UI defect fix. All packaged checks used temporary isolated profiles and mock wallet services. At closeout there were no Catalyst/Sage processes and no listeners on ports 5000, 5001 or 9257.

The original Harvestr profile remained byte-identical to its pre-test baseline:

- `.env`: `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`
- `bot.db`: `D2535E277423552EA187FA03865104B674696DA9045332F2AF8156C0AF1229F3`
- `bot.db-wal`: `FDB10904FE1D38B908B17F9753A887789719C75061D25388919EB920BE4F3DBE`
- `bot.db-shm`: `33A0052345CB793A112AFFA664DF194A4671CCFA126748EA2DD82796861D84B4`

## Result

The focused shutdown-scope defect is fixed and fully validated on top of the primary PC's complete-history Cancel All change. This evidence does not by itself declare the broader CATalyst candidate ready and does not authorize merging; primary-PC review remains required.
