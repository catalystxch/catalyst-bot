# Shutdown wallet-scope acceptance evidence

Date: 2026-10-05 (Europe/London)

## Identity

- Target branch: `codex/coin-prep-fee-approval`
- Verified target head: `2bc7f520f3abbc673dacb378db2744b0479f7311`
- Fix branch: `codex/shutdown-wallet-scope`
- Wallet-scope fix commit: `29bad9f263a2f79f1491445f066fb8605bb49984`
- Backend-neutral copy fix commit: `0c34a2f20d310c9b935288f94ebcbc01508d4fe4`
- Stop/quiescence UI fix commit: `5d7a371110b46a83abb15f468589767cbc97d2ee`
- Stop-completion copy precision commit: `364c2755a872e453e738b0773480262dd1e9edd9`
- Scope: shutdown consent, leave-open status, reported stop-state polling and bounded Cancel All retry, plus backend/Chromium regressions

## Confirmed defect

The shutdown dialog described its optional Cancel All action as cancelling offers "on Dexie" and its leave-open result could state "No open offers were left behind" from CATalyst-tracked rows alone. The backend operation is wallet-wide: it covers all currently active offers in the connected wallet, across assets, including manual or otherwise untracked offers. The old text understated the destructive scope and overstated the authority of the tracked-row summary.

The same flow also treated the immediate `/api/bot/stop` response as completion. `BotLoop.stop(wait=False)` can return while finalizer and mutation-producing threads are still alive, allowing wallet-wide cancellation to race with offer production.

## Fix

- The checkbox, warning, reset state and progress copy now say that Cancel All covers all currently active offers in the connected wallet, including manual/untracked offers, without hardcoding Sage in the generic Sage/Chia flow.
- Dexie-only wording was removed.
- Leave-open summaries are explicitly limited to CATalyst-tracked visibility and disclose that untracked wallet offers may remain.
- "Currently active" is intentional: Cancel All acts on a complete wallet snapshot and does not promise to catch an external offer created after that snapshot.
- After requesting stop, the UI polls `/api/bot/state` until the backend reports a settled non-running `stopped`, `blocked`, or `error` state. The Step 1 copy does not claim the client inspected every background worker: it says the bot reports stop complete and server shutdown separately verifies remaining cleanup. `stopping`, unknown or inconsistent states fail closed.
- Cancel All retries only the exact HTTP 409 `BOT_STOPPING`/`retryable: true` contract with bounded exponential backoff and visible progress. Other errors and timeouts fail closed.

## Test-first proof

The new/changed regressions were run before their production changes and failed on the prior behavior:

- `test_shutdown_offer_disposition_qualifies_catalyst_tracked_visibility`
- `test_shutdown_cancel_consent_names_wallet_wide_untracked_scope`
- `test_shutdown_stop_step_reports_only_observed_bot_state`
- `test_shutdown_waits_for_reported_stopped_state_and_retries_only_bot_stopping`
- `test_shutdown_stop_poll_times_out_fail_closed`
- `test_shutdown_cancel_retry_is_bounded_and_rejects_other_errors`

After rebasing onto `2bc7f520f3abbc673dacb378db2744b0479f7311`:

- Combined shutdown/Cancel All backend group: 63 passed
- Focused Chromium shutdown group (`--e2e`): 5 passed
- Ruff: all checks passed
- Complete Chromium E2E suite: 223 passed, 0 failed; 147.28 seconds
- A complete backend run on the earlier `aa4f371` base passed 7,206 tests plus 431 subtests with zero failures. The final `2bc7f52` integration was revalidated with the affected backend group above; primary-PC backend evidence covers the integrated backend guard separately.
- `git diff --check`: passed

## Fresh Windows build

Command: `py -3.14 build.py`

- Python: 3.14.3
- PyInstaller: 6.22.3
- Result: BUILD SUCCESSFUL
- Executable: `dist/Catalyst/Catalyst.exe`
- Executable SHA-256: `BD516BD00E0114FEAF136C9C2CAAC7DC3F6613E9C6C1439714735DCC1EBCF83E`
- Source `bot_gui.html` SHA-256: `A28C725F807C1A7A6BDD997449A4B548B0CA7272D0BC83B018D1CB4EBD9EC4C0`
- Bundled `_internal/bot_gui.html` SHA-256: `A28C725F807C1A7A6BDD997449A4B548B0CA7272D0BC83B018D1CB4EBD9EC4C0`

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

The shutdown scope and stop-ordering UI defects are fixed and validated on top of the primary PC's complete-history and backend quiescence guards. This evidence does not by itself declare the broader CATalyst candidate ready and does not authorize merging; primary-PC review remains required.
