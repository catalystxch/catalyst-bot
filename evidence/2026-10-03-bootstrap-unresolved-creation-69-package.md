# Bootstrap unknown-creation stop gate and exact 69a7071 package

Draft PR #220 runtime/source commit is
`69a7071120c985cc585cdb3860ce394c4dfa4448`. This follows the
`7183853` stop creation fence. The 718 fence closes an in-flight Sage
creation lane before selecting cancellation targets, but a Sage create call
can return an ambiguous result without a trade ID. Its durable offer intent
then remains `creation_unknown`. Before this correction, Bootstrap status
reported zero open offers, stop could return success with zero cancellation
targets, and Start or Renew could persist a new campaign while the prior
wallet outcome was unresolved.

A regression in `tests/test_bootstrap_api.py` was red before correction:
Start returned 200 after a stopped unknown creation. The API now counts
nonterminal campaign intents without a Sage trade ID; status shows that
count and requires attention. Stop first disables campaign creation, waits
for the serialized creation lane, and returns an unresolved 503 without
submitting cancellation when an intent lacks a trade ID. The stopped
outcome remains visible after reload. Both Start and Renew refuse a new
campaign for the exact Sage identity and asset until the old creation is
reconciled. The browser shows an explicit Sage/journal review message and
does not describe the state as zero-offer clearance. Its regression was red
before the copy correction.

The affected Bootstrap API and offer-journal slice passed **122 tests**.
The related browser file passed **14 tests** and the complete Chromium suite
passed **207 tests**. Ruff, format and `git diff --check` passed. The full
Windows Python suite passed **7,153 tests**, with **208 skipped** and **427
subtests passed**. All **11** exact-source PR CI checks passed. These tests did not use the original TEST 7
profile.

## Exact Windows package

- Clean detached build: `E:\catalyst-69a-primary-build`
- EXE SHA-256: `01AC1CAD95FA6FD25979D082070A1C99512FA3D9CFBEFF182D9C85B5F5A2469D`
- Bundled `bot_gui.html` SHA-256: `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7`
- 192-file ZIP SHA-256: `5166D452A0E2B2104941C40A2BFF6765060A0ACD464491A14F95D8B117F9425C`
- Unsigned installer SHA-256: `E621E2EA3D002D1FA88A236D3A75C506DD7A9D14A3EBCD25259963D6B9D80437`

The ZIP passed complete CRC reads, extraction, embedded EXE/UI hash checks,
and extracted API smoke. The detached EXE passed packaged API, synthetic
Sage RPC, publication recovery, and native clean/duplicate/persisted/safety
smokes. A unique-AppId current-user QA installer passed clean install,
installed API/Sage, uninstall, same-version 718-to-69 upgrade, rollback,
restore, restored API/native, and final uninstall. The QA registration and
directory were absent afterward. Defender custom scans of the bundle, ZIP
and installer completed with zero matching detections.

The acceptance ZIP and installer were published on the separate artifact
branch at `da97e85b6c6cdfdf877d84c709534c2225b157f8`, with the final
result manifest at `d852b8c9506a17b24e0611e04709a29f0541a2ff`:

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/da97e85b6c6cdfdf877d84c709534c2225b157f8/acceptance-artifacts/CATalyst-69a7071-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/da97e85b6c6cdfdf877d84c709534c2225b157f8/acceptance-artifacts/Catalyst-Setup-69a7071-1.4.0.exe)
- [Final manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d852b8c9506a17b24e0611e04709a29f0541a2ff/acceptance-artifacts/CATalyst-69a7071-primary-acceptance.md)

Fresh HTTP downloads of the pinned ZIP and installer matched the SHA-256
values above. These artifacts remain acceptance candidates only.

## Open gates

The exact 69a7071 package has not run against the original TEST 7 profile.
The prior approved MZ/XCH campaign expired and no new campaign or fee
approval has been received. An earlier automatic approval review rejected
a predecessor command-tool live launch before execution; the operator has
been asked to manually start this exact EXE, personally acknowledge Risk
Disclosure, and connect Sage. Before any wallet effect, recheck exact
process path/hash, mainnet fingerprint `736588221`, CAT wallet ID `2`, MZ
asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
balances, pending transactions, Sage and database offers, safety, campaign
and fee ledger. Live lifecycle, restart/recovery, full UI, both 24-hour
windows, independent secondary acceptance and final review remain open.
Keep PR #220 draft; no main merge, tag, release or public-readiness claim.
