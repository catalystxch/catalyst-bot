# Stopped cancellation attention and exact 00767dc package

Draft PR #220 runtime/source commit is
`00767dc7de7a3801f80377707ce54d381f970b7b`. The previous source
`69a7071` exposed a stopped campaign's unresolved offer creation through
`stopped_cancellation`, but its top-level `needs_attention` flag became
false when the campaign was no longer active. A status consumer could miss
the required operator review despite the durable unresolved record.

A regression in `tests/test_bootstrap_api.py` was red on `69a7071`:
`needs_attention` was false after stopping an unknown Sage creation. The
status endpoint now reads the stopped cancellation state once and sets
`needs_attention` when either that state exists or the active campaign is
expired/has unresolved creation. The regression is green. The affected
Bootstrap API and offer-journal slice passed **122 tests**; Ruff, format
and diff checks passed. The complete Chromium suite passed **207 tests**
on `69a7071`, and the bundled `bot_gui.html` is byte-identical in this
candidate. The full local Windows Python suite passed **7,153 tests**,
with **208 skipped** and **427 subtests passed**. All **11** exact-source
PR CI checks passed.

## Exact Windows package

- Clean detached build: `E:\catalyst-007-primary-build`
- EXE SHA-256: `48E2C3394B04EDD39FFB65A8C3D3D7A3BC3A6395095C7A1E2BC297621CEC68B1`
- Bundled `bot_gui.html` SHA-256: `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7`
- 192-file ZIP SHA-256: `96BC603DA0F7406BA50C25A4307645B2BD98FAA7487BEF2915B2F48AA1EEDE84`
- Unsigned installer SHA-256: `D0C578A6443AA2E7C0720D00910222DEB5DEC3EA847D4AB0E1A9B05850EA3264`

The ZIP passed complete CRC read, extraction, embedded EXE/UI hash checks,
and extracted API smoke. The detached EXE passed packaged API, synthetic
Sage RPC, publication recovery, and native clean/duplicate/persisted/safety
smokes. A unique-AppId current-user QA installer passed 69a clean install,
007 upgrade, 69a rollback, 007 restore, restored API/native, and final
uninstall. Every installed EXE hash matched; the QA registration and
directory were absent afterward. Defender custom scans of the bundle,
ZIP and installer completed with zero matching detections. Fresh HTTP
downloads of the ZIP and installer matched their hashes above.

The acceptance ZIP and unsigned installer were published on the separate
artifact branch at `c0194958f78ffe646bad662c694f97d4315f4bed`; the
final result manifest is at `5c8852eb868cc4a97a7e0cbc8e7f4a1a6984ae28`:

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/c0194958f78ffe646bad662c694f97d4315f4bed/acceptance-artifacts/CATalyst-00767dc-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/c0194958f78ffe646bad662c694f97d4315f4bed/acceptance-artifacts/Catalyst-Setup-00767dc-1.4.0.exe)
- [Final manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5c8852eb868cc4a97a7e0cbc8e7f4a1a6984ae28/acceptance-artifacts/CATalyst-00767dc-primary-acceptance.md)

## Open gates

The exact package has not run against the original TEST 7 profile. An
earlier automatic approval review rejected a predecessor command-tool
live launch before execution; the operator was asked to manually start
this exact EXE, personally acknowledge Risk Disclosure and connect Sage.
Before any wallet effect, recheck actual process path/hash, mainnet Sage
fingerprint `736588221`, CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
balances, pending transactions, Sage and database offers, safety, campaign
and fee ledger. The previous campaign is expired; no new campaign or fee
approval has been received. Live lifecycle, restart/recovery, full UI,
both 24-hour windows, independent secondary acceptance and final review
remain open. Keep PR #220 draft; no main merge, tag, release or
public-readiness claim.
