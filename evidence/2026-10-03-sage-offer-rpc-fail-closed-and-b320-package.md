# Sage offer-read failure and exact b320dfe acceptance package

PR #220 remains draft. Its exact source/runtime candidate is
`b320dfe0335bbe6a1de101a6fbdf79ef455f2d06`, after the action-bound
fee-recovery and durable Bootstrap stop changes from PRs #237 and #239.

## Defect and verification

`wallet_sage.get_all_offers()` returned an empty list when Sage replied
`{"success": false, "offers": []}` without an error string. That let an RPC
failure masquerade as proof of an empty offer book. The new regression failed
before the fix (`[] is not None`). The exact-source change rejects every
explicit `success: false` response. `get_authoritative_offer_history()` now
reports `success: false` and `end_of_history: false` for that response.

The exact-source wallet and endpoint selection passed **231 tests and 25
subtests**. Ruff, formatting, and `git diff --check` passed. All **11 PR #220
checks** passed on `b320dfe`. The immediately preceding `68f99c1` source
passed the full primary Windows backend suite: **7,143 passed, 205 skipped,
424 subtests passed** in 36m 28s. Its affected backend suite passed 257
tests and Chromium passed 204. The only runtime change after that full run is
the single Sage failure guard above.

## Exact Windows package

- Detached build: `E:\catalyst-b320-primary-build` at `b320dfe`
- EXE SHA-256: `C28C740DA900B48543D1BB33C018196D4CDE62017096A8D7DBA528BB6B6D64FD`
- Bundled UI SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/27d2c5637578c7348987abdb02a6b91bcbe8d645/acceptance-artifacts/CATalyst-b320dfe-primary-acceptance.zip), SHA-256 `B4DC216A6F95A6D85ED2C49A32E9D2956424EE927F18339E59370CA6DBBBEFF8`
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/27d2c5637578c7348987abdb02a6b91bcbe8d645/acceptance-artifacts/Catalyst-Setup-b320dfe-1.4.0.exe), SHA-256 `04F41799295A54173E7AC7EEBB2493F88BF4549BF70F6D3F15632495E82C6987`
- [Artifact manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/27d2c5637578c7348987abdb02a6b91bcbe8d645/acceptance-artifacts/CATalyst-b320dfe-primary-acceptance.md)

The ZIP contains 192 files and passed full CRC inspection. Exact packaged
API, mock Sage RPC, publication recovery, and native clean, duplicate,
persisted and safety launch smokes passed using isolated data. A unique-AppId
QA installer clean-installed, matched EXE/UI hashes, passed installed API
and mock Sage smokes, and uninstalled with no QA registration remaining.
Defender custom scans of the bundle, ZIP and installer had zero matching
detections. Independent HTTP downloads of the pinned ZIP and installer
matched the hashes above.

## Live gate

Read-only TEST 7 preflight confirmed Sage mainnet fingerprint `736588221`,
MZ CAT wallet ID `2`, exact asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
zero open MZ/XCH offers in complete Sage history, and no pending wallet
transactions. The exact `b320dfe` EXE has **not** run against the original
live profile. The operator has been asked to launch it manually, personally
acknowledge Risk Disclosure and connect TEST 7; a prior command-tool live
launch of a predecessor was rejected before execution by automatic approval
review. No blocked launch was retried through another tool.

The previous 24-hour campaign expired without exact-candidate wallet effect
or campaign fee approval; its old approval is not reusable. A new campaign
needs separate approval. Exact live offer lifecycle, restart/recovery, the
24-hour windows, full UI and final review remain open. No main merge, tag,
release, or public-readiness claim is authorized.
