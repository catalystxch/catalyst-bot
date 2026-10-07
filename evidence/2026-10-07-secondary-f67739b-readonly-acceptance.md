# CATalyst exact-f677 secondary read-only acceptance

Date: 2026-10-07 05:56–06:04 BST

Scope: independent source review, focused red/green regression verification, broader wallet/start-safety tests, immutable HTTP artifact verification, and isolated-profile native package smoke. No original profile, wallet selection, wallet action, campaign, offer, fee approval, or live market operation was used.

## Identity

- Exact runtime/source commit: `f67739b63aae05c13e6d8c6c9f4d77aa0ef634fc`
- Draft PR #220 feature head: `702a24482b73d32efc2178453050679dcd305c1f`
- Runtime comparison: no differences in `src`, `tests`, `bot_gui.html`, or `desktop_app.py`; feature head adds only historical evidence Markdown relative to exact runtime.
- Immutable artifact commit: `1cec479169ee8dbe6392ad097e1cc4428f0221df`
- ZIP SHA-256: `A3E1424A02FEFDCAD665DC628BE4C829E0BB46043DE3BE7E81CC95EF1A6B6E0C`
- Installer SHA-256: `E006EFB8D48F9B46CD7AA8748D994A1FE16CA5E49FDA357FA70D0252581869E5`
- Extracted `Catalyst.exe` SHA-256: `A0C0BAA7F04792328E20AA87E99AC5034994C0F93E094789420DDD6BC59B635D`
- Extracted `bot_gui.html` SHA-256: `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`
- Manifest SHA-256: `45AB85C434D1611D560918E00EB88E90FA3D5FBCF42B4F88A77D0DBC2EACA52E`
- Executable metadata: file version `1.4.0.0`, product version `1.4.0`, company `MonkeyZoo`, description `CATalyst - Chia AMM Liquidity Bot`, Authenticode `NotSigned`.

## Source review

The change from exact parent `3da11d63608c0ef2093ad578d63c64155db2107d` is limited to 10 production lines in `src/catalyst/wallet_sage.py` and 20 regression-test lines in `tests/test_wallet_sage_startup_readiness.py`.

For `include_completed=False`, terminal Sage rows are filtered first. Every remaining potentially fillable or unknown-status row must then have a non-empty `trade_id`/`offer_id`, and IDs must be unique. Any missing or duplicate identity sets `get_all_offers._last_error` to `get_offers open offer IDs are missing or duplicated` and returns `None`, preserving fail-closed semantics for callers. Explicit empty books still return `[]`; terminal history remains unaffected; unknown statuses remain conservatively included but must be identifiable.

No correctness or safety defect was found in this patch.

## Red/green evidence

The same two assertions were replayed with mocked Sage RPC data:

- Parent `3da11d6`: idless OPEN row accepted; duplicate-ID OPEN rows accepted; `2` expected failures, process exit `1`.
- Exact `f67739b`: both malformed books rejected with `None` and the explicit `_last_error`; `2/2` passed, process exit `0`.

## Automated verification

- `tests/test_wallet_sage_startup_readiness.py`: `22 passed`, `6 subtests passed` in `0.63s`.
- Wallet/recovery selection (`test_wallet_sync_fail_closed`, Chia authoritative offer history, offer-create collection, legacy/stability startup recovery, public-post recovery, bootstrap mutation gate): `69 passed` in `8.42s`.
- Complete `tests/test_mutation_gate.py`: `263 passed` in `100.13s`.
- Ruff check on changed source/tests: passed.
- Ruff format check on changed source/tests: 2 files already formatted.
- Git diff whitespace check: passed.
- One non-failing known collection warning was emitted for `tests/test_offer_create.py::TestResult`, which has an `__init__` constructor.

Green total in non-overlapping pytest selections: `354 tests` plus `6 subtests`; the two standalone green regression assertions are additional.

## Immutable package verification

- Artifact branch resolved to full immutable commit `1cec479169ee8dbe6392ad097e1cc4428f0221df` before download.
- ZIP, installer, executable, and UI hashes matched the pinned manifest exactly.
- Python `zipfile.testzip()` inspected 206 entries and returned no CRC failure.
- The ZIP extracted into a new isolated evidence directory.
- Installer was downloaded and hash-verified but not executed.

### First isolated native launch

- Used only the new `profile-native` directory under the evidence directory via `CMM_DATA_DIR`.
- PID `15828` was responsive and was the sole owner of `127.0.0.1:5000`.
- Running image hash matched the required executable hash.
- `/` returned HTTP 200 with 2,215,026 bytes.
- `/api/health`: `status=ok`, version `1.4.0`, bot stopped.
- `/api/status`: fail-closed with `runtime_safety.allowed=false`, reason `WALLET_IDENTITY_BINDING_INVALID`, zero offers and zero reported errors.
- `/api/sage/startup-status`: idle with empty fingerprint; no wallet selection occurred.
- Duplicate PID `11928` exited normally with code `0`; original PID remained the sole listener.
- Repeated health after 30 seconds remained clean.
- Graceful `CloseMainWindow()` shut down PID `15828` and released port 5000.

### Persisted-profile relaunch

- PID `20416` was responsive, used the exact executable hash, and was the sole listener.
- Health remained OK/version 1.4.0; bot remained stopped; identity binding remained fail-closed; offers and errors remained zero.
- Graceful close succeeded and released port 5000.

### Final durable state

Read-only SQLite inspection showed zero rows in all checked effect/trading tables: `offers`, `fills`, `fee_approvals`, `approved_fee_reservations`, `coin_prep_operations`, `offer_operation_journal`, `publication_outbox`, `reservation_leases`, `bootstrap_campaigns`, `wallet_effect_claims`, and `wallet_effect_dispatches`.

Log scan found zero matches for `ERROR`, `CRITICAL`, `Traceback`, `unhandled`, or `exception`. Windows Application event review found no CATalyst crash/error event during the test window. Final state had zero `Catalyst.exe` processes and zero port-5000 listeners.

## Limitations and verdict

- This was intentionally read-only and isolated. Risk disclosure, wallet selection, original-profile recovery, live Sage economics, offer publication/cancellation, Coin Prep, and fee approval were not exercised.
- Visual GUI automation remains outside this evidence; no stale-coordinate or alternative automation was used.
- The unsigned installer was not executed.

Verdict for the requested exact-source, wallet/start-safety regression, immutable artifact, and isolated native-smoke scope: **PASS — no defect found**.

This is not a full live-wallet release acceptance verdict; the remaining live/operator scopes stay with the primary acceptance plan.
