# Secondary-PC combined integration acceptance — 2026-09-27

## Candidate identity

- Repository: `catalystxch/catalyst-bot`
- Branch fetched: `codex/coin-prep-fee-approval`
- Exact production candidate: `9bbf972a9e8b0b6459e67f483080dc487993a7ca`
- The candidate was checked out detached in a new worktree. `git rev-parse HEAD`
  and the fetched remote branch both resolved to the exact SHA above before any
  build or test.
- This checkpoint changes evidence only. It does not change production source,
  merge main, or create a release.

## Independent regression and suite results

- Four focused red-first regressions covering retired sniper inputs and standard
  Coin Prep restart rehydration: **4 passed**.
- Complete affected economics, fee-wallet-snapshot and Coin Prep endpoint group:
  **165 passed in 33.12 seconds**.
- Complete serial backend suite: **7,047 passed, 165 skipped, 422 subtests
  passed**, one pre-existing pytest deprecation warning, in **1,441.15 seconds**.
- Complete real-Chromium E2E suite: **164 passed in 107.57 seconds**.
- `ruff check src tests`: passed.
- `git diff --check 0bd46052fa67f7ad5bbef356cadf289f51c25e97..HEAD`:
  passed.
- Full-suite interpreter provenance: Python 3.12 project venv supplied
  `chia_rs`, Flask, requests, Playwright and pytest; the installed Sage
  site-packages directory was appended after venv initialization to supply the
  pure `chia` package. Module origins were printed and verified before the
  authoritative run.
- Two earlier collection-only attempts were invalid harness attempts and are not
  product failures: the lightweight venv lacked `chia`, while the machine Sage
  Python lacked the project dependencies. A path-order attempt then selected a
  Python 3.14 `chia_rs` binary ahead of the Python 3.12 venv. No tests ran in
  those attempts. The corrected runtime produced the complete green result
  above.
- An affected-group attempt ended after **164 passes and one setup error** with
  `sqlite3.OperationalError: database or disk is full`. The exact errored test
  passed alone, and the complete affected group then passed 165/165. This was a
  transient machine-capacity event, not an assertion failure.

## Windows build and package

- Fresh `build.py --no-clean` PyInstaller build: passed, including bundled HTML
  and certifi CA checks.
- Built executable:
  `dist/Catalyst/Catalyst.exe`
- Secondary executable SHA-256:
  `3210144F8DB7E6D85D13193D2B0CB5B59EF4F5089F581CD602534F20C13C8649`
- Secondary ZIP:
  `acceptance-artifacts/9bbf972/CATalyst-9bbf972-secondary-integration.zip`
- ZIP SHA-256:
  `0DD2CF7D0631C6F4E595314E7F0ABF6E77094B851E32E3A474D705DF4BFFDB4C`
- The ZIP was extracted into a new directory. The extracted executable hash was
  exactly the source build hash above.
- Packaged API smoke: passed for both the build directory and independently
  extracted ZIP.
- Packaged mock Sage RPC worker smoke: passed.
- Packaged interrupted-publication upgrade/recovery smoke: passed.
- Native isolated-profile clean launch: passed, v1.4.0 health endpoint ready.
- Duplicate launch: passed; second PID exited normally with code 0 and did not
  bind a second server or replace the original process.
- Authenticated graceful shutdown: passed; zero `Catalyst` processes remained.
- Persisted-profile relaunch: passed; the immutable completed Coin Prep state
  survived the process boundary.
- The independently built bytes differ from the primary PC's executable hash.
  Both builds are tied to the same exact source SHA; PyInstaller output is not
  treated as reproducible across the two Windows build environments.

## Live Sage read-only recovery

No economic wallet mutation or fee spend was made during this combined-candidate
verification.

- Network: Chia mainnet.
- Sage version: 0.13.0, minimum requirement 0.12.9, supported and healthy.
- Wallet label: `Harvestr test wallet`.
- Fingerprint: `3702373391`.
- CAT wallet ID: 2.
- Pair/ticker: MZ/XCH, `MZ_XCH`.
- Asset: Monkeyzoo Token (MZ).
- Asset ID:
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Refreshed balances: `240.800786441412 XCH` and `3,381,521.720 MZ`.
- Offers: zero buy and zero sell.
- Locks: zero XCH and zero CAT.
- Runtime errors: zero; runtime safety allowed; zero blocking operations,
  reservations, prepared creations, publication claims or submitted cancels.
- Recovered Coin Prep: `complete=true`, `previously_complete=true`, phase
  `complete`, 258/56 XCH coins and 129/6 CAT coins.
- Approval:
  `989a638875baf1a9c6d39e34a063e44ce5173a192f1dd1a55ca1965059b1a121`.
- Approval state: `complete`; `session_completed=true`; zero held, committed and
  spent fee mojos; zero unresolved operations.
- Manual configured fee remained `0.0000130791 XCH`. Read-only fee status also
  returned a fresh Coinset suggestion of `0.000007473753 XCH` for the 120-second
  target; no approval or spend was created from that estimate.
- Persisted relaunch repeated the exact completed-state recovery with zero
  offers, locks, fee holds, unresolved operations or runtime errors.

## Safety and external blockers

- Market confidence remained RED and correctly prohibited creation, exposure
  increase and requote. The loaded snapshot included
  `out_of_range_depth_excluded`, `insufficient_ask_depth`,
  `single_provider_dependency`, `confidence_snapshot_expired` and
  `market_evidence_expired`. No confidence gate was bypassed.
- Live offer create/requote/remake was therefore not repeated on the integrated
  candidate. Earlier authorized live acceptance already exercised Coin Prep,
  bot start/stop and Cancel All; this combined pass was deliberately read-only.
- Windows computer-control initialization failed twice before any UI action with
  `failed to write kernel assets: The system cannot find the path specified.
  (os error 3)`. Browser E2E, packaged API and native process smokes continued.
  This is recorded as an external automation-tool blocker, not a CATalyst
  product failure.

## Verdict

The integrated production candidate at exact SHA `9bbf972a9e8b0b6459e67f483080dc487993a7ca`
passes the independently repeatable backend, Chromium, static, Windows build,
package, duplicate-launch, persisted-restart and live Sage read-only recovery
gates. Remaining live publication work is legitimately blocked by RED market
confidence. No new CATalyst defect was found in this combined verification.

## Lifecycle coverage audit checkpoint

The feature branch was fetched again and verified at exact remote HEAD
`e2a9c8fe03677abcf1d0c3cbee49e4115839ffb3`, with exact parent
`b15cf8d8b26d53e70f6433c66db5b46fc9a5daf6`. The parent-to-head diff changes
only `evidence/2026-09-24-live-test7-acceptance.md`; `git diff --check` passed.
The complete range after production source `9bbf972a9e8b0b6459e67f483080dc487993a7ca`
contains evidence files only.

The smallest focused lifecycle slice expanded to **47 tests**, all passing in
**20.87 seconds** under the complete Python 3.12 acceptance environment. Exact
requirement-to-test coverage was:

- Create and publication acknowledgement:
  `test_offer_manager_prepares_before_effect_and_finalizes_exact_evidence`,
  `test_offer_manager_crash_boundaries_never_resubmit_ambiguous_intent`,
  `test_offer_manager_concurrent_creation_has_exactly_one_effect_winner`,
  `test_success_requires_current_claim_version_and_digest_binds_acknowledgement`,
  `test_actual_transport_binds_request_header_bytes_and_provider_acknowledgement`,
  and `test_crash_after_remote_success_reclaims_stale_claim_with_same_identity`.
- Within-cap requote and remake:
  `test_lineage_recovery_is_safe_at_each_durable_crash_boundary`,
  `test_requote_resumes_visible_lineage_before_tier_and_budget_filtering`,
  `test_replacement_runs_two_visible_child_before_parent_cancel_waves`, and
  `test_amber_never_authorizes_create_child_first_requotes`.
- Protected cancellation:
  `test_coin_prep_cancel_uses_approved_sealed_bundle_and_exact_fee`,
  `test_cancel_reservation_replay_cannot_authorize_second_dispatch`,
  `test_protected_cancel_hold_cannot_release_before_authoritative_outcome`, and
  `test_authoritative_confirmation_charges_hold_and_restart_scan_is_idempotent`.
- Cancel retry and restart:
  `test_retry_failed_cancel_advances_durable_attempt_after_restart`,
  `test_retry_failed_cancel_settles_any_terminal_result_before_next_mutation`,
  `test_retry_failed_cancel_pauses_when_submitted_result_is_not_proven`,
  `test_retry_failed_cancel_race_has_one_new_wallet_effect`,
  `test_startup_recovers_settled_protected_cancellation_fee_outcome`, and
  `test_restart_resumes_unresolved_cancellation_without_replacement_creation`.
- Atomic fee ledger:
  `test_cancellation_can_use_protected_allowance_but_not_exceed_total`,
  `test_concurrent_reservations_cannot_each_spend_same_remainder`,
  `test_reservation_survives_connection_restart`,
  `test_reservation_replay_is_not_a_new_dispatch_permission`, and
  `test_new_approval_cannot_reduce_protected_cancellation_allowance`.
- Bypass resistance:
  `test_offer_creation_continuation_rejects_forgery_without_effect`,
  `test_production_cancellation_callers_route_or_deny_before_adapter`,
  `test_startup_repost_is_blocked_when_market_publication_gate_is_closed`, and
  `test_amber_never_authorizes_create_child_first_requotes`.

No production defect or genuine automated safety-coverage gap was proven. The
remaining boundary is live acceptance only: RED market confidence prevented a
real Sage offer, Dexie acknowledgement/discovery, fee-consuming cancellation,
requote and remake cycle. Mock evidence is not treated as live acceptance. No
wallet mutation or fee was incurred during this audit.

## Integrated-head read-only live refresh

The primary feature branch was fetched at exact HEAD
`464ef56213618b7e525dc4ab811ae1b1b425e8cb`, with exact parent
`e2a9c8fe03677abcf1d0c3cbee49e4115839ffb3`. Its parent diff is exactly the
55-line addition to this evidence file from the lifecycle coverage checkpoint;
`git diff --check` passed.

At approximately 27 September 2026 13:28 BST, the locally built integrated
package was launched in Flask-only mode against the established isolated live
profile for one read-only refresh. Live Sage identity matched the authorized
secondary wallet exactly: mainnet, Sage, label `Harvestr test wallet`,
fingerprint `3702373391`, CAT wallet ID `2`, ticker `MZ_XCH`, and MZ asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Sage RPC was listening and authenticated.

CATalyst remained stopped with zero open buy/sell offers, zero XCH/CAT locks,
zero pending cancellations and zero unresolved operation, reservation,
publication or prepared-creation blockers. Runtime safety was allowed. Market
Intel refreshed Dexie's public book successfully: nine buys, 29 sells, best
bid `0.00004`, best ask `0.00011`, 0.3-second reported book age, one refresh
and zero order-book errors. The visible 100 XCH bid was external, not ours.
Splash remained unavailable/empty and Spacescan had no token context.

The supported read-only Smart Settings calculation returned HTTP 409 with
`market_confidence=RED`, `market_data_valid=false`, stage `INVALID`, provider
redundancy 1 and follow capacity 0. Exact current reason codes were
`out_of_range_depth_excluded`, `insufficient_ask_depth` and
`single_provider_dependency`; Bootstrap was only suggested, with insufficient
ask depth and single-provider dependency still blocking it. Therefore no fee
budget proposal was generated or approved and no wallet effect was attempted.
The exact supervised package process was then stopped; zero CATalyst processes
and no port-5000 listener remained.
