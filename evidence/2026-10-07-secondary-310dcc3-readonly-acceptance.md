# CATalyst exact-310dcc3 secondary read-only acceptance

Date: 2026-10-07 06:41–06:51 BST

Scope: independent source review; parent red reproduction; exact-source green regression, wallet/startup and mutation tests; Ruff; fresh local Windows build; and isolated-profile native read-only smoke. No original profile, wallet selection, wallet action, campaign, offer, fee approval, or live market operation was used.

## Guidance and identity

- Requested source commit: `310dcc3ddb3cb4562b35080498316f1e3b92a636`
- Verified parent: `085efa7c868f55ff0fecc3e38f33c65c350ae576`
- Remote feature head during verification: exact `310dcc3ddb3cb4562b35080498316f1e3b92a636`
- The supplied path `C:\catalyst\AGENTS.md` did not exist on this secondary PC. The checkout's own `AGENTS.md` was read completely and followed.
- Source file SHA-256, `src/catalyst/wallet_sage.py`: `BA3EA3C1CD81080694B0F8D50C007BA2885023294B273E8FD8F18FC23D5C67E6`
- Regression file SHA-256, `tests/test_wallet_sage_startup_readiness.py`: `43AF43F1FB33446191B0A975A5808FA47C5DE54EAC63828008C637659A30F37D`

The change from the parent is restricted to `src/catalyst/wallet_sage.py` and `tests/test_wallet_sage_startup_readiness.py`: 44 insertions and 5 deletions.

## Source review

For Sage's `include_completed=False` reader, terminal rows are filtered before the new identity gate. Each remaining row's present `trade_id` and/or `offer_id` is normalized by the existing lock-ID canonicalizer: string-only, trimmed, lowercased and stripped of an optional `0x` prefix. The gate then requires:

1. at least one wire identity;
2. every present identity to normalize to exactly 64 lowercase hexadecimal characters;
3. all identity fields on one row to agree after normalization; and
4. canonical identities to be unique across the open book.

Any failure sets `get_all_offers._last_error` to `get_offers open offer IDs are missing, malformed, conflicting or duplicated` and returns `None`. Explicit empty books remain valid, matching uppercase/`0x` encodings on the same row remain valid, completed history is unaffected, and unknown-status rows remain conservatively visible but must have an authoritative identity.

No correctness or safety defect was found in this patch.

## Parent red reproduction

The same standalone assertions were run against parent `085efa7` with mocked Sage RPC rows:

- malformed ID `not-an-offer-id`: incorrectly accepted;
- conflicting `trade_id=a…a` and `offer_id=b…b` on one row: incorrectly accepted;
- duplicate canonical ID encoded as uppercase bare hex and lowercase `0x` hex across two rows: incorrectly accepted.

Result: `3` expected failures, process exit `1`.

## Exact-source green reproduction

The identical assertions on exact `310dcc3` rejected all three books with `None` and the explicit fail-closed `_last_error`. A matching uppercase bare `trade_id` plus lowercase `0x` `offer_id` on one row was accepted.

Result: `4/4` assertions passed, process exit `0`.

## Automated verification

Environment:

- Python `3.12.10`
- pytest `9.1.1`
- `chia_rs 0.30.0`
- PyInstaller `6.22.3`

Results:

- `tests/test_wallet_sage_startup_readiness.py` plus `tests/test_plan_02_21_wallet_sage_unit.py`: `98 passed`, `24 subtests passed` in `1.02s`.
- Wallet/recovery/startup selection (`test_wallet_sync_fail_closed`, Chia authoritative offer history, offer-create collection, legacy/stability startup recovery, public-post recovery and bootstrap mutation gate): `69 passed` in `6.89s`.
- Complete `tests/test_mutation_gate.py`: `263 passed` in `99.76s`.
- Ruff check on changed source/tests: passed.
- Ruff format check on changed source/tests: 2 files already formatted.
- Git diff whitespace check: passed.
- One known non-failing pytest collection warning was emitted for `tests/test_offer_create.py::TestResult`, which defines an `__init__` constructor.

Non-overlapping pytest total: `430 passed` plus `24 subtests`; the four standalone green assertions are additional.

## Fresh local Windows build

Command: the Python 3.12 environment above ran `build.py` from the clean exact-source checkout.

Result: build successful. PyInstaller emitted two non-fatal warnings for absent hidden imports `pycparser.lextab` and `pycparser.yacctab`; post-build HTML and certifi CA checks passed.

- Local `Catalyst.exe` SHA-256: `28A91FB0EB49A15EEFBFD70BF317158E08CF06850C8D09333494F3CE74E68F5F`
- Bundled `bot_gui.html` SHA-256: `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`
- EXE metadata: file version `1.4.0.0`, product version `1.4.0`, company `MonkeyZoo`, description `CATalyst - Chia AMM Liquidity Bot`, Authenticode `NotSigned`.

The build temporarily refreshed `_version.py` line endings, but its normalized Git blob was identical to HEAD and the index/worktree were verified clean before evidence commit.

## Isolated native smoke

All launches used only `CMM_DATA_DIR` under `evidence\acceptance-310dcc3-secondary-20261007T0648BST\profile-native`.

First launch:

- PID `2712` was responsive and the sole owner of `127.0.0.1:5000`.
- Running image hash matched the local build hash.
- `/` returned HTTP 200 with 2,215,026 bytes.
- `/api/health`: `status=ok`, version `1.4.0`, bot stopped.
- `/api/status`: fail-closed with `runtime_safety.allowed=false`, reason `WALLET_IDENTITY_BINDING_INVALID`, zero buy/sell/history offers and zero reported errors.
- `/api/sage/startup-status`: idle with empty fingerprint; no wallet was selected.
- Duplicate PID `18080` exited normally with code `0`; original PID remained the sole listener.
- After 20 seconds, health and fail-closed safety remained unchanged.
- Graceful `CloseMainWindow()` shut down PID `2712` and released port 5000.

Persisted-profile relaunch:

- PID `2856` was responsive, used the exact local executable hash and was the sole listener.
- Health remained OK/version 1.4.0; bot remained stopped; identity binding remained fail-closed; offers and errors remained zero.
- Graceful close succeeded and released port 5000.

Final read-only SQLite inspection showed zero rows in `offers`, `fills`, `fee_approvals`, `approved_fee_reservations`, `coin_prep_operations`, `offer_operation_journal`, `publication_outbox`, `reservation_leases`, `bootstrap_campaigns`, `wallet_effect_claims`, and `wallet_effect_dispatches`.

Log scan found zero matches for `ERROR`, `CRITICAL`, `Traceback`, `unhandled`, or `exception`. Windows Application event review found no CATalyst crash/error event during the smoke window. Final state had zero `Catalyst.exe` processes and zero port-5000 listeners.

## Package limitation and verdict

At verification time, `origin/codex/coin-prep-fee-approval-artifacts` still resolved to `1cec479169ee8dbe6392ad097e1cc4428f0221df`, the older f677 package. No immutable ZIP, installer, manifest or required hashes for exact `310dcc3` had been published, so no old artifact was misrepresented as this candidate and no installer was tested.

Verdict for exact-source review, red/green regression, wallet/start/mutation suites, fresh local build and isolated native-smoke scope: **PASS — no defect found**.

Immutable package acceptance remains pending publication of a package built from exact `310dcc3` with pinned hashes.
