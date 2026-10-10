# Complete Sage coin views and startup reconciliation

Runtime/source: `b693a4e16fd6450e8e7568bfd2605afc539134d9`.
This branch is a fast-forward descendant of draft PR #220. It is not a release.

## Defects and corrections

The preceding source returned a partial owned-coin map when a later Sage page
failed or when the 40-page safety cap was reached. Its selectable map and
simple owned list read only the first 500 records. Startup reconciliation
converted an unreadable wallet snapshot into an empty map, which could rewrite
local coin state from an invented authoritative absence. Focused failing tests
for these cases turned green after `9c9aaae01b5061bd949a2352c269763c6504324c`.
The complete serial Windows backend on that commit passed **7,389 tests,
246 skipped, 447 subtests** in 24 minutes 11 seconds.

The follow-up source found two remaining 500-record ceilings in selectable
coin enumeration and CAT/XCH balance totals. `get_selectable_coins_only` now
uses stable coin-ID pagination, then restores descending amount order for its
callers. CAT selectable/owned and XCH owned balance views now require complete
pages. Each view rejects RPC errors, malformed rows, duplicate IDs, changing
reported totals, and an unproven end or page-cap exhaustion. An incomplete
view yields unknown/failure rather than a partial successful balance. Six
additional red/green regressions and 76 focused tests passed. A read-only
query against the locally connected Sage wallet confirmed coin-ID sorting is
accepted and both XCH and CAT selectable/balance functions return success;
the observed views contained 112 XCH and 60 CAT coins. This was no wallet
mutation.

One more 500-record ceiling remained in `get_spendable_coins_rpc`. Its result
feeds the running bot's coin watcher and size-filtered coin selection, so a
partial first page could appear reliable and hide valid later coins. Three
failing regressions reproduced truncation, a later-page RPC error accepted as
success, and a later eligible coin missing from the amount range. Commit
`c7d124c2f0c93f66a214d0f6daf493bddf7b057f` makes this view complete
with the same strict page validation and preserves descending amount order.
The affected Sage, Coin Prep, and startup suites passed **41 tests**.
The `c7d124c` and exact `b693a4e` spendable functions each returned 112 XCH
and 60 CAT records in read-only calls to the connected Sage wallet.
The superseded `f43033f` full run was stopped after this concrete finding.
The first complete `c7d124c` backend run reached 7,398 passing tests with
one failure: a Sage HTTP 401 diagnostic had changed from its structured error
object to `None`. It stayed fail closed, but violated the existing caller
contract. An added later-page regression and the existing 401 regression
failed red. Commit `b693a4e16fd6450e8e7568bfd2605afc539134d9` preserves
the exact structured RPC error at any page for spendable queries while still
rejecting a partial success. The affected suites passed **115 tests and 15
subtests**. The complete serial Windows backend on `b693a4e` passed
**7,399 tests, 246 skipped, 447 subtests** in 24 minutes 33 seconds
(exit code 0).
The isolated Chromium suite on the exact source passed **245 tests**.

## Clean detached Windows package

The clean detached checkout at `b693a4e` produced:

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `529492482AC9D52CD93F51B5FD2537C1B826CF72193DF09C4A9FCC7883557B19` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| `E:\CATalyst-b693a4e-primary-acceptance.zip` | `A67354893F5032336AF4BB4619E8611679BA0D3104A3A36119663FEBF53EE28D` |
| Unsigned `Catalyst-Setup-1.4.0.exe` | `9457386301105F9492F09668530972173407947C9250A258325C188D0351380F` |

The 192-entry ZIP passed CRC and embedded-EXE hash checks. Its safely
extracted EXE matched the bundle hash and passed API and synthetic Sage smokes.
Packaged API, synthetic Sage RPC, and publication-recovery smokes passed.
Defender real-time protection was enabled; custom scans of the bundle, ZIP, and installer produced
no recent detection. A unique-AppId isolated installer clean-installed on E:,
produced the exact EXE hash, passed installed API and synthetic Sage smokes,
then uninstalled with no remaining EXE or QA registry key. This QA install did
not use the original TEST 7 profile or overwrite its installer registration.

The [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cdb1d1100f7571783eeb728fd4fff884cb6b1c1d/acceptance-artifacts/CATalyst-b693a4e-primary-acceptance.zip),
[installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cdb1d1100f7571783eeb728fd4fff884cb6b1c1d/acceptance-artifacts/Catalyst-Setup-b693a4e-1.4.0.exe),
and SHA-256 manifest are pinned at artifact commit
`cdb1d1100f7571783eeb728fd4fff884cb6b1c1d`. Independent HTTP downloads
of both binaries matched the SHA-256 values above. These are acceptance
artifacts, not a release.

## Live and release gates

The original TEST 7 process still runs the older `eadb82a` package in a
stopped, zero-offer state. The new source has not run against that original
profile. The Veeam-overlap stopped-profile 24-hour failure remains unresolved.
Active-offer lifecycle/recovery, original-profile exact-candidate acceptance,
independent secondary exact-candidate acceptance, full native UI, both final
24-hour windows, and final review remain open. The new TEST 7 campaign and
fee approval have not been received. Keep PR #220 draft; do not merge, tag,
release, or claim public readiness.
