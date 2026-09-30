# Spent Coin Prep Startup Recovery

## Candidate and observed failure

- Base commit: `b4a3daf715ff11477329648cb6a37e41e1a18c7d`
- Packaged executable SHA-256: `CF7661D91A56B3A86CFE6535456CAAA06A41419DA6ECC7CA821C6B7C7BBC2137`
- Startup fallback: `COIN_PREP_RECOVERY_REQUIRED`
- Runtime mutation lease: inactive
- Recoverable operations: one `SUBMITTED_UNKNOWN` direct-batch Coin Prep operation
- Wallet actions during diagnosis: none

The unresolved operation had 31 sealed XCH output IDs. Sage's current-owned
view contained only 26 because five outputs had been spent after confirmation.
The existing recovery implementation required every sealed output to remain in
the current-owned view, so a later legitimate spend made startup recovery
permanently impossible.

Sage's exact `get_coins_by_ids` read returned all 31 records with the expected
amount and XCH asset identity. All records shared confirmed creation height
9299308; five also had later spent heights. This is wallet-authoritative,
read-only evidence for the already sealed output IDs.

## Fix and safety boundary

Direct-batch recovery still prefers the current-owned view. If any sealed
output is no longer current, it now asks the selected wallet for all exact
historical output records and accepts them only when:

- every sealed output ID is present exactly once;
- every amount and asset identity matches the sealed unsigned effect;
- every output has a positive confirmed creation height; and
- any spent height is an integer no earlier than the creation height.

Missing, malformed, unconfirmed, mismatched, or unsupported history remains
fail-closed. No wallet mutation or transaction replay is introduced.

## Real-profile copy verification

A consistent SQLite backup of the failing profile was used for recovery; the
live profile was not modified by the verification.

- Backup DB SHA-256: `AA5E766D365AEB87E2F01AFA5CFFA3534AA7A53F1055FF522860FFD1E198AF31`
- Recovery result: `True`
- Operation transition: `SUBMITTED_UNKNOWN` to `CONFIRMED`
- Safety latch transition: `tripped` to `resolved`
- Full desktop startup authorization on a second copy: allowed
- Runtime lease after test cleanup: inactive
- Wallet actions and fees: none

## Final verification

- Focused red/green regression: failed before the production change with
  `TypeError: 'NoneType' object is not subscriptable`; final file run passed
  **38 tests** in 2.77 seconds.
- Relevant recovery, mutation-gate, fee-approval and replacement-capacity
  group: **329 passed** in 123.01 seconds.
- Complete backend suite: **7,081 passed, 179 skipped, 422 subtests passed**
  in 1,398.43 seconds with zero failures.
- Complete opt-in real-Chromium suite: **178 passed** in 115.15 seconds.
- Ruff check, Ruff format check and `git diff --check`: passed.
- Bandit (`-ll`) found no medium/high issues; tracked-secret and Vulture scans
  passed.
- Clean `python build.py`: passed with Python 3.12.14 and PyInstaller 6.22.3.
- Fresh `Catalyst.exe` SHA-256:
  `D50AFE944DA788A6A2DA36919735B129C794DE1D40EC06F7E82D523798077BAD`.
- Packaged API smoke: nine endpoint checks passed and reported v1.4.0.
- Packaged Sage RPC smoke: synthetic mTLS worker path passed.
- The obsolete read-only diagnostics process from the original screenshot was
  stopped after evidence collection. The live profile and authoritative backup
  were not modified by the fix verification.
