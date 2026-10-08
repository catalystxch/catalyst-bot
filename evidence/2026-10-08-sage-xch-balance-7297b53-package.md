# Sage XCH selectable balance authority: exact source and primary package

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `7297b53e0967d2b79eadb7c32f1606738405fac9`. This is an
intermediate acceptance record, not public-readiness approval.

## Defect and correction

The Sage XCH balance adapter used `int(selectable_balance)`. Boolean,
fractional, negative, and oversized RPC values could therefore become an
apparently successful balance result. Four parametrized tests were red on the
parent. The adapter now requires an exact nonnegative atomic amount and
returns an unsuccessful balance result for malformed values. Exact integer or
string zero remains a valid empty balance.

## Source verification

- Focused Sage wallet tests: **32 passed**.
- Full serial Windows backend: **7,412 passed, 246 skipped, 447 subtests** in
  1,731.64 seconds.
- Ruff check, Ruff format, and Git whitespace check passed.
- The frontend bundle is byte-identical to the preceding `60e2875` package,
  whose complete isolated Chromium suite passed **245 tests**. There was no
  frontend change in `7297b53`.
- PR CI on exact source was still running when this record was written; its
  final result requires a separate check.

## Detached Windows package

Built from clean detached checkout
`E:\catalyst-sage-balance-7297b53-build`. Build-generated version metadata
was the only tracked change in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `170C7FEFD399280A1A696C3A4D042D62F26EF735AA831613542B392BA713DAC9` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `3158341FA1EDB39EAE1F1BC1439D90F40C87B2E33BDD9E7F9D051934D5DA4B3C` |
| Unsigned installer | `2C3541491042EFDB39942CC761DE947A89DB21FC28AA618061462E3B3D7796C2` |

Packaged API, synthetic Sage RPC, interrupted-publication recovery, and native
clean, duplicate, persisted-profile, and safety startup smokes passed. The
192-file ZIP passed CRC and embedded EXE hash checks. An EXE extracted from
the ZIP passed packaged API smoke. A unique-AppId isolated QA installer
clean-installed to E:, produced the expected EXE hash, passed installed API
and synthetic Sage smokes, and uninstalled with its EXE and QA registration
absent. Defender real-time protection was enabled; custom scans of bundle,
ZIP, and installer left six pre-existing detections at six.

The ZIP, unsigned installer, and manifest are pinned at artifact commit
`2549490d17da4bdff9181112b5d0c63f2579a821`. Independent HTTP downloads
matched both binary SHA-256 hashes. The downloaded ZIP passed CRC and
embedded EXE hash checks.

- [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2549490d17da4bdff9181112b5d0c63f2579a821/acceptance-artifacts/CATalyst-7297b53-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2549490d17da4bdff9181112b5d0c63f2579a821/acceptance-artifacts/Catalyst-Setup-7297b53-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/2549490d17da4bdff9181112b5d0c63f2579a821/acceptance-artifacts/SHA256SUMS-7297b53.txt)

## Live and release gates

Exact `7297b53` has not run against the original TEST 7 profile. The older
`eadb82a` app remains in a read-only `HEARTBEAT_FAILED` fence after the
[second Veeam-overlap incident](2026-10-08-veeam-snapshot-heartbeat-eadb82a.md).
Its stopped-profile monitor failed. Exact-candidate original-profile live
lifecycle and recovery, independent secondary exact acceptance, full native
UI, both final-candidate 24-hour windows, and final review remain open. The
prior campaign is stopped; no new campaign or fee approval exists. PR #220
remains draft with no merge, tag, release, or public-readiness claim.
