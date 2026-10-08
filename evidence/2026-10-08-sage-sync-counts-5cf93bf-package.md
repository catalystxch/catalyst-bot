# Sage sync-count authority and exact Windows package

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `5cf93bf39ac52ae16b654a5f2977da89ce2130b2`. This is interim
acceptance evidence, not public-readiness approval.

## Defect and correction

When Sage omitted its explicit `synced` flag, CATalyst inferred sync from
`synced_coins >= total_coins` without validating either count. A response of
11 synced coins out of 10 was reported as synced. Malformed explicit flags
could also be ignored in favor of matching counts. Red regressions reproduced
both cases. The adapter now infers sync only from exact nonnegative integer
counts with `synced_coins <= total_coins`; equality is required for synced.
Malformed or inconsistent counts and malformed explicit flags remain unknown
and unready. A direct read-only Sage `get_key` response confirmed TEST 7
fingerprint `736588221`. Its `get_sync_status` response
returned integer counts (`28359` of `28359`) with no explicit flag, and the
updated adapter reported reachable/synced without changing wallet state.

## Verification

- The focused sync test file passed 24 tests and four subtests.
- Adjacent Sage startup, wallet identity, node-failure and startup-flow suites
  passed 159 tests and 13 subtests.
- Ruff check, Ruff format check and Git whitespace check passed.
- The full serial local Windows backend passed 7,415 tests, with 246 skipped
  and 451 subtests passed. All 11 exact-source PR checks passed, including
  unit tests and CodeQL.
- No frontend files changed. The packaged `bot_gui.html` SHA-256 matches the
  preceding exact candidate (`A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609`),
  whose complete isolated Chromium suite passed 245 tests.

## Detached Windows package

Built from detached source checkout `E:\catalyst-sync-count-5cf93bf-build`.
The build-generated version file is the only tracked change there.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `A5AB125B6B7182A05595EFA175AE4ADD9A5E979FEA3F6BA5EF0A4961C0E8F83B` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `ED768AB6A01F8DBEA588E24C52D4D12CDAC47465C45BE5F82B7CC0EBB80590E6` |
| Unsigned installer | `0FDF235B143DEEAC2317FB9FF69F61E6FB92B0324D90D65E32CDDA2A2B3B7B6B` |

The clean build passed asset verification. The ZIP has 192 files and 14
directory entries, passed CRC, and contains the exact EXE hash. Packaged API,
synthetic Sage RPC and interrupted-publication recovery smokes passed from the
build; extracted-ZIP API smoke passed. A unique-AppId QA installer
(`43F84512-BEC7-436F-A744-61F53F6BA5BE`) installed the exact EXE to an
isolated E: directory, passed installed API and synthetic Sage smokes, and
uninstalled with both EXE and QA registration absent. Defender real-time and
antivirus were enabled; custom scans completed for the bundle, ZIP and
installer, with the existing six detection records unchanged.

The binaries and manifest were pinned at artifact commit
`914ebe03a407b0e8dd8379d32634a61b118c2c61`: [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/914ebe03a407b0e8dd8379d32634a61b118c2c61/acceptance-artifacts/CATalyst-5cf93bf-primary-acceptance.zip),
[unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/914ebe03a407b0e8dd8379d32634a61b118c2c61/acceptance-artifacts/Catalyst-Setup-5cf93bf-1.4.0.exe),
and [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/914ebe03a407b0e8dd8379d32634a61b118c2c61/acceptance-artifacts/SHA256SUMS-5cf93bf.txt).
Independent HTTP downloads of the ZIP and installer matched the hashes above.
The downloaded ZIP passed CRC and contained 192 files and the exact EXE hash.
Exact-candidate native desktop launch was not attempted during this package
check because it would foreground a window on the original PC; native UI
acceptance remains open.

## Live and release gates

The original TEST 7 app remains the older `eadb82a` process in a read-only
`HEARTBEAT_FAILED` fence after the [second Veeam-overlap incident](2026-10-08-veeam-snapshot-heartbeat-eadb82a.md).
Exact `5cf93bf` has not run against that original profile. Its live offer
lifecycle/recovery, independent secondary exact-candidate acceptance, full
native UI, both final-candidate 24-hour windows and final review remain open.
The prior campaign is stopped; no new campaign or fee approval exists. PR
#220 remains draft with no merge, tag, release or public-readiness claim.
