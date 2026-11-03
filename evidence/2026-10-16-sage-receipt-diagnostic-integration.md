# Sage receipt diagnostic integration checkpoint (2026-10-16)

This checkpoint is for draft bot PR #268. It does not approve general release or
authorize an original-profile CATalyst launch.

## Exact integration source and checks

- Head: `60024dfa4536a39d408cab4be46e8e5e595fa878`.
- This head incorporates the five-line null-flow guard and regressions from
  draft PR #269. Malformed Sage transaction flows remain in transaction
  evidence, but cannot supply coin or asset hints. They remain insufficient to
  prove a fill.
- `tests/test_offer_reconciliation.py`: 354 passed locally. Ruff and staged
  diff checks passed.
- All 11 GitHub PR checks passed at this exact head. The CI unit job reported
  7,771 passed, 326 skipped, and four warnings.
- A clean Windows `python build.py` completed. The resulting
  `dist/Catalyst/Catalyst.exe` SHA-256 is
  `99D8F86CBF6D5085FC2F7B81470A16F7E21359A0515D2DB2A654C22126FE97CB`.
  Defender custom scan of the packaged directory completed; no recent or
  package-matching detection was reported.

## Harvestr proof boundary

The independent Harvestr tester's read-only Sage check found the confirmed
filled root `b97ee4ef2ca6adcf893ee1a082b9434989bcb93c5d9d0dde6224aa43364c662f`
still unprovable from the live wallet. At height 9424451, Sage's raw
transaction exposes the CAT receipt as an external, assetless coin. Its
`get_coins_by_ids` response includes the spent input but omits the receipt;
Sage's local receipt row lacks MZ classification, ownership linkage, and CAT
lineage. CATalyst correctly keeps the root `UNKNOWN / COIN_RECORDS_INCOMPLETE`.
The PR #269 guard corrects a misleading `source_limit_exceeded` diagnosis from
the null created flow; it does not supply missing wallet proof or clear the
`REGISTRY_BLOCKED` latch.

On a disposable database copy, five other Harvestr roots terminalized as
expired using fresh Sage evidence. The filled root terminalized only when
retained complete watch-only evidence was replayed at its recorded historical
time. That copy result is not fresh original-profile authority. The original
Harvestr database and wallet were unchanged. Coin-only Sage Resync on the
original profile still requires the pending direct action-time confirmation,
followed by fresh identity, balance, offer, receipt, and lineage verification.

## Live and release limits

The new integration executable has not been launched. Primary TEST 7 still
runs an older stopped CATalyst executable. The request for isolated startup
smoke of the exact new package is pending. Neither original-profile recovery,
reciprocal Splash receipt, nor a final-candidate full 24-hour trace/end-state
audit is established by this checkpoint. Signed general Windows release still
lacks the required SignPath configuration; the published v1.4.1 download is a
separate opt-in unsigned beta.
