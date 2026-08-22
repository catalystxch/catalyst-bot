# Stability kernel verification

## Status

Task 16 automated regression and local package verification completed on
2026-08-22 (Europe/London) from branch `codex/stability-kernel`, based on
`8ef30efaf196986ca68944f97cbf75a65aed4740` before the Task 16 commit.

This document records automated, non-live verification only. Task 17's
authorised TEST 7 mainnet acceptance has not been run.

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

## Automated test results

| Gate | Result | Network evidence |
| --- | --- | --- |
| Combined stability-kernel suites | 1,646 passed | 0 external attempts |
| Existing cancellation/lifecycle/wallet/offer/coin-prep/startup/Splash/database slice | 722 passed, 370 subtests passed | 0 external attempts |
| Post-static-cleanup affected slice | 659 passed, 366 subtests passed in 167.56s | 0 external attempts |
| Final order-reproduction and release-fix slice | 159 passed, 15 subtests passed in 9.76s | 0 external attempts |
| Final whole repository, CI file-isolated mode | **5,027 passed, 13 skipped, 413 subtests passed in 335.29s** | 226 guard events; 174 loopback; **0 external**; 18 guard loads; 31 guarded child launches |

The final whole-repository command completed at
`2026-08-22T05:03:17.0919190+01:00`:

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
that global; the 159-test reproduction and final 5,027-test run both pass.

The four final warnings are duplicate xdist reports of two known pytest
collection warnings: helper classes with constructors in `test_coin_prep.py`
and `test_coin_prep_v2.py` are not test classes.

## Quality and security results

- `python -m ruff check .` — passed.
- CI-configured Vulture scan — passed:
  `python -m vulture src/catalyst scripts desktop_app.py build.py scripts/vulture_whitelist.py --min-confidence 90`.
- `python -m bandit -r src --ini .bandit -ll` — passed with zero medium/high
  findings across 129,136 lines of code.
- `git diff --check` — passed.

The verification fixes removed genuine unreachable Chia split and legacy
requote code, removed unused imports, and explicitly consumed retained public
compatibility parameters. Dynamic Flask route imports remain covered by the
repository Vulture whitelist.

## Local package verification

`python build.py` completed as a clean PyInstaller build at
`2026-08-22T04:43:33+01:00`. Post-build checks found the executable and bundled
HTML assets.

- Executable: `dist/Catalyst/Catalyst.exe`
- Size: 10,573,276 bytes (reported as 10.1 MB)
- SHA-256: `FD74CD9C51FF942A715C195BE62E14FC30A855BD6F7F5FA504A7CB53A5F11DA3`

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

## Known limitations

- `python -m ruff format --check .` reports accumulated branch-wide formatting
  debt in 38 files (296 files already conform). Task 16 did not bulk-reformat
  those large prior-task files because that would create a broad mechanical diff
  and require repeating the complete build/test evidence. Ruff lint, Vulture,
  Bandit, and diff checks are green.
- PyInstaller emits one non-fatal warning that hidden import
  `importlib_resources.trees` was not found. The build, bundled-asset check, and
  complete packaged API smoke all pass.
- Live TEST 7 lifecycle, restart, disconnect, long-gap, replacement, genuine
  fill, soak, and final reconciliation evidence remain Task 17 and require the
  user's explicit live authorisation.
