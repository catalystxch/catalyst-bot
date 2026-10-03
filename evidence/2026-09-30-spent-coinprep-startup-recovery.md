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
amount and exact sealed coin identity. All records shared confirmed creation height
9299308; five also had later spent heights. This is wallet-authoritative,
read-only evidence for the already sealed output IDs.

The raw Sage records do not contain `asset_id`, nested asset metadata, or an
`owned` flag. This was true for all 31 XCH outputs and a separate sample of 20
sealed CAT outputs. Passing `authoritative_asset_hints` therefore only copied
the caller's asset expectation into the normalized record; it was not
independent asset proof. The final implementation does not pass those hints.
Asset identity remains bound by the pre-dispatch sealed output and its exact
coin ID; if Sage ever supplies explicit asset metadata, a contradiction still
fails closed. Three known external mainnet example coin IDs returned no rows,
while all sealed wallet outputs returned, which is consistent with this being
a selected-wallet history endpoint rather than a global chain query.

## Fix and safety boundary

Direct-batch recovery still prefers the current-owned view. If any sealed
output is no longer current, it now asks the selected wallet for all exact
historical output records and accepts them only when:

- every sealed output ID is present exactly once;
- every exact coin ID and amount matches the sealed unsigned effect;
- every output has a positive confirmed creation height; and
- any spent height is an integer no earlier than the creation height.

An output missing from the current-owned view must have a valid later
`spent_height`; a historical record that is both absent from current ownership
and unspent remains unresolved. Conversely, a current output may not also be
reported spent. The spent height is included in bounded confirmation evidence,
verified by the capacity verifier, and atomically persisted as `status='spent'`
with no purpose. It is never exposed as free capacity.

If CATalyst already has protected permanent spend history for an output,
recovery accepts it only when the historical observation also proves that
output spent and the existing row has the exact wallet type, amount, and
`spent` status. The row is then left untouched, preserving its trade link and
terminal history. The parametrized full recovery-to-database regression covers
both the newly discovered spent-output case and this protected-history case.

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

Primary review correctly identified that the first implementation resolved the
operation and then inserted all 31 outputs as `free`. Inspection of that first
isolated recovered copy confirmed the five later-spent IDs were temporarily
resurrected as free. That revision was not safe to integrate. The amended
implementation was rerun against a new untouched profile copy:

- desktop startup authorization: allowed; diagnostics status: none;
- operation transition: `SUBMITTED_UNKNOWN` to `CONFIRMED`;
- safety latch transition: `tripped` to `resolved`;
- all 26 current outputs: `free`;
- all five later-spent outputs: `spent`, with null purpose and trade ID;
- later-spent outputs visible as free capacity: zero;
- runtime lease active only during authorization and inactive after cleanup;
- final-source validation copy:
  `acceptance-data/startup-bug-fix-final-20260930-232300`;
- wallet actions and fees: none.

## Final verification

- Focused red/green regression: failed before the production change with
  `TypeError: 'NoneType' object is not subscriptable`; final file run passed
  **38 tests** in 2.77 seconds.
- Relevant recovery, mutation-gate, fee-approval and replacement-capacity
  group after the spent-state and protected-history correction: **330 passed**
  in 118.59 seconds.
- Complete final-source backend suite: **7,082 passed, 179 skipped, 422
  subtests passed** in 1,362.79 seconds with zero failures.
- Complete final-source opt-in real-Chromium suite: **178 passed** in 122.74
  seconds.
- Ruff check, Ruff format check and `git diff --check`: passed.
- Bandit (`-ll`) found no medium/high issues; tracked-secret and Vulture scans
  passed.
- Clean `python build.py`: passed with Python 3.12.14 and PyInstaller 6.22.3.
- Fresh `Catalyst.exe` SHA-256:
  `4E34C6DD8EEFF38138F59AC8090CE1A392660AA672E712F3E95857064C054DD3`.
- Packaged API smoke: nine endpoint checks passed and reported v1.4.0.
- Packaged Sage RPC smoke: synthetic mTLS worker path passed.
- The obsolete read-only diagnostics process from the original screenshot was
  stopped after evidence collection. The live profile and authoritative backup
  were not modified by the fix verification.
