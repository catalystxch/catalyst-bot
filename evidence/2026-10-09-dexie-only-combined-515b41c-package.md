# Exact combined Dexie-only beta package — 2026-10-09

## Identity and source

- Runtime and package source:
  `515b41c200fb506594225be498b099b0dbe6c03d`.
- Feature branch: `codex/coin-prep-fee-approval`; PR #220 remains draft into
  `main`.
- Exact source combines a release-level Dexie-only Splash fence, truthful
  asynchronous bot stop state, and paired coin-count preservation on wallet
  snapshot failure. The final one-line correction sets dormant non-beta
  Splash receiving off by default so `.env.example` and the loader agree.
- Artifact branch commit:
  `893001a24076e250a66c597488d99fbc2638637f`.
- The previous runtime/package `acecdb3` is superseded for acceptance; its
  pinned artifacts and red CI env-default result remain historical evidence.

## Exact local and CI verification

- Full serial Windows backend: **7,490 passed, 1 skipped, 455 subtests
  passed**, 20m20s. Full Chromium: **256 passed**, 2m43s.
- Repo-wide Ruff lint/format, `.env.example` default check for 102 keys,
  critical imports, Vulture, and Git whitespace checks passed.
- PR #220's 11 exact-source checks passed, including lint-and-syntax,
  unit-tests, CodeQL, Semgrep, Gitleaks and security-scan.
- The clean detached PyInstaller build and 1.4.0 unsigned installer compiled.
  Package API, synthetic mTLS Sage RPC, publication recovery, and native
  clean/duplicate/persisted/safety smokes passed with isolated profiles.
- The ZIP has 192 files, passed CRC, extracted with the expected EXE hash,
  and passed packaged API smoke from its extracted copy.
- A unique-AppId, unique-name current-user QA installer passed isolated
  install, installed API/Sage smokes and uninstall. The installed EXE hash
  matched; the QA executable and registry key were absent afterward.
  Original product registration and user data were not used.
- Defender custom scans of the ZIP and installer produced no new detection.
  EXE and installer are intentionally unsigned (`NotSigned`).
- Independent HTTP downloads from the immutable artifact commit matched
  the locally built ZIP and installer SHA-256 hashes.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `D8FC061FD883ABB268F03A93CDB4B0B4631906043E95588CAAB0F6902A5A0238` |
| Bundled `bot_gui.html` | `F355EF52EA22F1E5F6FAAD872FD6051AB46BE700522F9795832414B63C25EE88` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/893001a24076e250a66c597488d99fbc2638637f/acceptance-artifacts/CATalyst-515b41c-primary-acceptance.zip) | `B8C6067FFEE736D986A05E0C0EDAD910528FE73746CB452B2D04DCC7CBEE0570` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/893001a24076e250a66c597488d99fbc2638637f/acceptance-artifacts/Catalyst-Setup-515b41c-1.4.0.exe) | `68A683BFDE99B77C112A949431088945DF21C9CF733AAA56F5A59841D2254879` |

## Original-profile and independent gates

The exact `515b41c` executable has **not** run against the primary TEST 7
or secondary Harvestr original live profile. The primary older `0bf0346`
read-only monitor is diagnostic only. Its full trace had two
`PROCESS_COUNT_NOT_ONE` alerts at 03:17:14Z and 03:35:14Z when isolated
native package smokes briefly launched another `Catalyst.exe`; the original
PID retained sole port-5000 ownership, its bot stayed stopped, and DB offers
remained zero. Those alerts are preserved and that trace is not a clean
24-hour acceptance window.

The other PC was sent the exact source and pinned hashes for independent
isolated review. At its latest report C: had about 2.05 GiB free after an
obsolete test run. A narrow test-temp cleanup was rejected by host policy;
it was not retried. Its last Sage key inventory showed Harvestr mainnet
fingerprint `3702373391`; required primary TEST 7 fingerprint `736588221`
was absent. No secondary original-profile wallet acceptance is claimed.

The specific new mainnet 24-hour campaign and network-fee scope remains
unapproved. Live active-offer lifecycle/recovery, original-profile restart
and full native UI, clean primary and independent secondary final-candidate
24-hour windows, secondary original-profile acceptance and final review
remain open. No new campaign or wallet effect, main merge, tag, release, or
website beta publication occurred for this candidate.
