# Stability kernel verification

## Status

Task 16 automated regression and local package verification completed on
2026-08-22 (Europe/London) from branch `codex/stability-kernel`, based on
`8ef30efaf196986ca68944f97cbf75a65aed4740` before the Task 16 commit.

Task 17's authorised TEST 7 mainnet acceptance completed on 2026-08-22. The
acceptance used the isolated checkpointed lab and the exact wallet identity
gate described below; it did not use the user's normal CATalyst data directory.

## Safety envelope

Every Python, pytest, build, and packaged-smoke process used a fresh isolated
`CMM_DATA_DIR`. Automated source verification used the synthetic wallet identity
`161616161` / `Task 16 Synthetic Wallet` / `bls` / `mainnet` and pinned Sage to
`https://127.0.0.1:1`. The packaged smoke used its repository-owned synthetic
identity `123456789` / `Packaged Smoke Sage` and a temporary mutual-TLS Sage
server bound only to loopback.

The inherited Task 16 socket guard ran in `loopback_only` fatal mode. Any DNS or
non-loopback socket target terminated the process. All accepted runs recorded
zero external attempts. No live wallet, user database, public API, GitHub, or
manual trading mutation was used.

`tests/test_parallel_offers.py` and the legacy manual
`tests/test_offer_create.py` were explicitly excluded and were never imported,
collected, or run. The repository's existing `conftest.py` exclusions also kept
the other live/manual API scripts out of collection.

## Authorised TEST 7 mainnet acceptance

Every live-effect boundary freshly verified Sage reported `TEST 7`, fingerprint
`736588221`, `mainnet`, BLS keys, and signing enabled. The isolated lab completed
all ten checkpoint stages in order:

| Stage | Durable result |
| --- | --- |
| Inventory | 9 wallets; complete 1,943-record offer history |
| Reconcile | Clean authoritative startup reconciliation |
| Lifecycle | `CANCELLED_PROVEN` |
| Restart | `RESTART_RECOVERED` |
| Stale read | `STALE_READ_FROZEN` before mutation |
| Long gap | `MONOTONIC_GAP_RECOVERED` |
| Replacement | `REPLACEMENT_LINEAGE_PROVEN`, 3 offers over 2 waves |
| Fill | `FILLED_PROVEN`, recovered from the exact confirmed self-take |
| Soak | `SOAK_STABLE`, 3 invariant snapshots |
| Final reconciliation | `FINAL_RECONCILIATION_CLEAN`, 9 lab intents |

The isolated same-wallet fill consumed the exact registered XCH maker input and
the independently verified SBX taker input in one transaction. Sage peers
accepted transaction `dece54534082a2f717273da37c00faa54ff2d75e7d381199d55433fb17d7625f`,
which confirmed at height `9183928`. Sage's normalized transaction row omitted
the transaction ID but supplied deterministic spend identity
`sha256:b751a083fc1c3d8ed64b13cfa42df1f0d066a08c1363b52e451c48b0e1e10e8d`;
the exact selected-input and requested-receipt proof recorded the fill without
weakening offer-absence handling.

Sage 0.12.10 signs every locally owned spend during `take_offer`. Passing the
already signed maker offer back to the same wallet therefore produced a doubled
maker signature and peer `BAD_AGGREGATE_SIGNATURE` rejection. The lab now
preserves the canonical maker coin-spend bytes and compression version while
replacing only the pre-existing aggregate signature with the BLS identity before
the guarded self-take. Exact wire tests cover this transformation. The corrected
transaction received successful mempool acknowledgements and confirmed.

The final wallet snapshot reported all XCH and SBX owned balances as selectable,
no live offer locks, no open local offers, terminal publication state, and zero
blockers in all six safety categories: operations, submitted cancellations,
prepared creations, contradictory history, reservations, and publication
claims. The checkpoint contains bounded redacted evidence only.

## Automated test results

| Gate | Result | Network evidence |
| --- | --- | --- |
| Combined stability-kernel suites | 1,646 passed | 0 external attempts |
| Existing cancellation/lifecycle/wallet/offer/coin-prep/startup/Splash/database slice | 722 passed, 370 subtests passed | 0 external attempts |
| Post-static-cleanup affected slice | 659 passed, 366 subtests passed in 167.56s | 0 external attempts |
| Final order-reproduction and release-fix slice | 159 passed, 15 subtests passed in 9.76s | 0 external attempts |
| Task 16 whole repository, CI file-isolated mode | 5,027 passed, 13 skipped, 413 subtests passed in 335.29s | 226 guard events; 174 loopback; **0 external**; 18 guard loads; 31 guarded child launches |
| Post-acceptance whole repository, CI file-isolated mode | **5,091 passed, 13 skipped, 413 subtests passed in 297.40s** | Repository loopback-only guard remained green |

The post-acceptance whole-repository command completed on 2026-08-22:

```text
python -m pytest tests -q -n 2 --dist=loadfile \
  --ignore=tests/test_parallel_offers.py \
  --ignore=tests/test_offer_create.py
```

The two-worker `loadfile` mode is the repository's CI isolation strategy: each
test file remains within one worker, while module state cannot leak between
unrelated files. An earlier serial run on the final release-fix source reached
`5,026 passed` with one late failure caused by an unisolated
`wallet_sage._CAT_ASSET_ID` test precondition. The test now explicitly isolates
that global; the 159-test reproduction, Task 16's 5,027-test run, and the final
post-acceptance 5,091-test run all pass.

The four final warnings are duplicate xdist reports of two known pytest
collection warnings: helper classes with constructors in `test_coin_prep.py`
and `test_coin_prep_v2.py` are not test classes.

## Quality and security results

- `python -m ruff check .` — passed.
- CI-configured Vulture scan — passed:
  `python -m vulture src/catalyst scripts desktop_app.py build.py scripts/vulture_whitelist.py --min-confidence 90`.
- `python -m bandit -r src --ini .bandit -ll` — passed with zero medium/high
  findings across 130,361 lines of code.
- `git diff --check` — passed.

The verification fixes removed genuine unreachable Chia split and legacy
requote code, removed unused imports, and explicitly consumed retained public
compatibility parameters. Dynamic Flask route imports remain covered by the
repository Vulture whitelist.

## Local package verification

`python build.py` completed as a clean PyInstaller build at
`2026-08-22T09:02:30+01:00`. Post-build checks found the executable and bundled
HTML assets.

- Executable: `dist/Catalyst/Catalyst.exe`
- Size: 10,586,303 bytes (reported as 10.1 MB)
- SHA-256: `F4C5D7AB566B9AE9EE1E3B0C05773DCC892EE13159A4487A3D8E3369491E2F8B`

The isolated packaged API harness then started that public executable in
`--flask` mode and passed all of these surfaces:

- `GET /api/health` (version `1.2.65`)
- `GET /api/wallet/sage-running`
- `POST /api/wallet/begin-startup`
- `GET /api/sage/startup-status`
- `GET /api/config/validate`
- `GET /api/diagnostics/api-stats`
- `GET /api/self-test`
- `GET /api/doctor?force=true`

The packaged run recorded 14 guard events, 12 loopback socket operations, and
zero external attempts. The temporary app and mock Sage processes shut down at
the end of the harness.

The first packaged attempt correctly exposed a release-only configuration
defect: `.env.example` reload replaced the harness's synthetic fingerprint and
expected wallet name, causing startup to enter read-only diagnostics. The
process-environment preservation contract now includes the exact wallet identity
and network fields, the harness supplies them explicitly, and unit plus packaged
tests pass.

## Regression fixes made during Task 16

- Preserved HTTP 405 routing for authorised unsupported methods before the
  mutation gate can reinterpret the request.
- Made cancellation-cohort replay losers return durable read-only state before
  any wallet effect.
- Modernised API tests to use an explicit local mutation permit and safe
  dependency mocks instead of accidental global state.
- Closed order leaks in configuration, reconciliation, publication, Linux
  desktop port selection, dashboard market-data fallbacks, and wallet discovery.
- Prevented Dexie, CoinGecko, Spacescan, and other public fallbacks from being
  reached by ordinary automated fixtures.
- Added exact packaged identity preservation and its regression tests.

No test invariant, production safety gate, or external-network guard was
weakened to obtain a passing result.

## Local Sage full-app acceptance

The final Windows build was exercised end to end on this PC against the
authorised Sage `TEST 7` wallet on 2026-08-22. The run used the isolated
`.superpowers/test7-mainnet-lab` data directory and left the user's normal
CATalyst data directory untouched.

The packaged Flask/API pass checked 76 read and control endpoints with no HTTP
5xx responses or secret findings. Health, self-test, configuration validation,
wallet identity, Sage startup, balances, CAT discovery, market data, offers,
reservations, diagnostics, and all six stability blocker categories returned
valid state. A dry-run cycle completed without an offer or transaction.

The browser UI rendered Dashboard, Offers, P&L, Market Intelligence, both
Settings views, Logs, Data Reset, Help, and About with no console errors. Theme,
keyboard focus, local presets, and Smart Settings form behavior were also
checked and restored. The native PyWebView build completed risk disclosure and
Sage onboarding, displayed fingerprint `736588221` and the exact XCH/SBX
balances, rendered the principal screens, passed its Doctor check with 9 passes
and one non-blocking Spacescan free-tier warning, and completed a clean
close/restart/close cycle.

Two real packaged boundaries exposed regressions that are now covered by tests:

- Sage 0.12.10's successful legacy boolean return from `login` was rejected by
  the guarded wallet facade. The facade now normalizes `True` only for the three
  documented legacy boolean mutation exports (`sage_login`, `sage_initialize`,
  and `delete_offer`); all other malformed mutation results remain blocked.
- Sage returned the selected offer coin with a `0x` prefix while CATalyst held
  the same id without it, producing a false unexpected-coin warning. Locked
  inputs are now compared in canonical lowercase `0x` form.

The bounded live package test created exactly one buy offer for `0.001 XCH` and
stopped the bot before a second cycle. Coin preparation, sniper, Dexie posting,
and Splash remained disabled; the sell side was disabled because the wallet had
no prepared SBX trading coin. The cancellation RPC was conservatively journaled
as ambiguous, the restart correctly entered read-only diagnostics, and the
authoritative reconciliation boundary then found Sage's exact cancelled row and
returned `CANCELLED_PROVEN` with `EXACT_CANCEL_RETURN_PROOF`. The only balance
change was the expected `0.000001 XCH` cancellation fee; SBX was unchanged.

Final reconciliation reported a stopped bot, `DRY_RUN=true`, zero Sage pending
transactions, zero Sage/CATalyst open offers, zero pending cancellations, zero
locks or reservations, and zero blockers in operations, submitted cancels,
prepared creations, contradictory history, reservations, and publication
claims. All XCH and SBX balances were spendable.

Fresh post-fix gates were:

- Wallet identity/login slice: 91 passed.
- Offer manager and creation journal slice: 114 passed.
- Whole repository in CI file-isolated mode: 5,095 passed, 13 skipped, 413
  subtests passed in 307.52s.
- Ruff, Vulture, Bandit (zero medium/high findings), and `git diff --check`:
  passed.
- `python build.py --no-clean`: passed; packaged post-build Sage/Doctor smoke:
  passed.

Final local artifact:

- Executable: `dist/Catalyst/Catalyst.exe`
- Size: 10,586,545 bytes
- SHA-256: `48C28B93B93737ADE776D502FD2F748CA99F99FD1A132884F0EF4CBE7A9EA451`
- Detailed redacted report:
  `.superpowers/local-sage-acceptance/acceptance-report.json`

## Known limitations

- `python -m ruff format --check .` reports accumulated branch-wide formatting
  debt in 38 files (296 files already conform). Task 16 did not bulk-reformat
  those large prior-task files because that would create a broad mechanical diff
  and require repeating the complete build/test evidence. Ruff lint, Vulture,
  Bandit, and diff checks are green.
- PyInstaller emits one non-fatal warning that hidden import
  `importlib_resources.trees` was not found. The build, bundled-asset check, and
  complete packaged API smoke all pass.
- Sage can normalize confirmed transaction rows without a transaction ID and
  can temporarily omit a consumed offer row. Terminal fill proof therefore uses
  a unique deterministic spend identity plus exact registered input and receipt
  flows; absence by itself remains non-terminal.
