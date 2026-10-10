# Public price GET: pre-bot asset binding

Draft PR #220 remains in acceptance. Current exact corrected source is
`050fe196d0fd41290724ac6b20a2c177ad3c2188`. The earlier `c4eb072`
package and original-profile read-only run below are retained as historical
evidence; they were superseded after a second asset-binding defect was found.

## Finding and correction

The prior `9dc6519` correction stopped `/api/price` from advancing the bot's
trading reference and writing price history when a bot object existed. Before
bot creation, the same endpoint still used `_fetch_price_standalone`, which
accepted the first Dexie ticker row without checking its ticker or CAT asset.
It could display another CAT's price for the selected pair.

A new endpoint regression put a different asset's `OTHER_XCH` row first and
the selected `MZ_XCH` row second. On the prior route it failed red: the
endpoint returned `9` instead of the selected pair's `0.00008` midpoint. The
route now uses the same pair-bound, expiring public quote in both lifecycle
states. The obsolete standalone helper and its API re-export were removed;
they are no longer a path for one-sided or unbound fallback pricing.

Focused `c4eb072` verification passed 88 tests and four subtests across public pricing,
startup pricing, retired TibetSwap dependencies, and status endpoints. Ruff,
format, whitespace, and the CI Vulture command passed locally. The first
source commit `754318b` had a CI Vulture failure because the old re-export
became unused. The `c4eb072` cleanup resolves it. All 11 PR checks passed on
the `c4eb072` source. Its full local run was superseded by the `050fe19`
correction before completion.

## Exact Windows package

The clean detached `c4eb072` build produced `Catalyst.exe` SHA-256
`650BE119C3020585916BE680705C4B4E2D3C088062E95BBD6B93CA28FC18A5AE`.
Bundled `bot_gui.html` SHA-256 is
`11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6`.
The 206-entry acceptance ZIP SHA-256 is
`46E8FB277202875E0E3CACC709284821BA599DB3AC65D12D8938109E487110A0`;
it passed CRC, excluded `.env` and `bot.db`, and yielded an identical extracted
EXE that passed the packaged API smoke. The unsigned installer SHA-256 is
`3E384CD757605452C2A82846491BA84D289158A81247BD9298C10CADC037DC44`.
The EXE passed packaged API, synthetic Sage, publication recovery, and native
clean/duplicate/persisted/safety smokes. A unique-AppId current-user QA
installer installed the same hashed EXE; installed API and synthetic Sage
smokes passed; its EXE and registration were absent after uninstall. Defender
scans of the bundle, ZIP, and installer introduced no new detections.
The pinned acceptance artifact commit is
`d2ea81e3fb9a0f9a4eeb6403827d4ff6bfe5585b`; independent HTTP downloads
of its ZIP and installer matched the two hashes above.

## Original TEST 7 read-only restart

The superseded `754318b` app shut down cleanly through its native UI with
cancel-offers unchecked and zero offers. The exact `c4eb072` app then started
as the sole `Catalyst.exe` process and port 5000 owner, PID 70996 at the
checkpoint, with the EXE hash above. The testing-authorized Risk Disclosure
was acknowledged in the native UI. Sage TEST 7 was selected and connected;
the optional Splash step was skipped, the configured Spacescan key retained,
and MZ selected. The app reported mainnet Sage fingerprint `736588221`, CAT
wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
bot stopped, XCH `138.470301476875`, MZ `780212.284`, zero buy/sell offers,
zero pending Sage transactions, and runtime safety allowed with no blockers.
The campaign remained inactive with no fee approval. Six live `GET /api/price`
calls returned the MZ midpoint `0.0000675156445`; the exact asset's durable
price-history `(count, max id)` stayed `(40763, 75944)` before and after.

No campaign, fee approval, offer, or wallet transaction was created during
this investigation. The earlier `754318b` package passed isolated package
checks and ran read-only on TEST 7, but it is superseded by `c4eb072`.
Both 24-hour windows, independent secondary acceptance, live wallet
lifecycle, and final review remain open. Keep PR #220 draft.

## Strict selected-asset proof (`050fe19`)

Further audit found that `_get_startup_price_cached` still accepted a Dexie
row with matching `MZ_XCH` ticker but no `base_id`. Its ticker alone did not
prove the CAT asset. A new red regression put an unbound ticker row first and
the exact MZ asset row second; the prior code returned the unbound price `9`.
The exact source now requires `base_id` to equal selected asset ID. A
missing-asset-only response returns no quote. Focused tests passed 68 cases
and four subtests. All 11 CI checks passed on `050fe19`. The full local
Windows backend suite then passed 7,171 tests, 210 skipped and 427 subtests
in 2,501.46 seconds. All 11 checks also passed on the docs-only `b35d910`
head.

The clean detached `050fe19` EXE SHA-256 is
`ADBA206BA661A2E4A50338A078FFBE9AE4BD174C1B74E516E5C4EC0CB6BFCB46`;
bundled UI is `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6`.
The 206-entry ZIP is
`E52203F29AC2873DABE09A36E17FEC369B0FC826B5F0CCB95F39C141A85346E3`;
the unsigned installer is
`D112805AF6D4F4A8D76B3677C94427CA66338755605CB9F92F5CBB7083E06360`.
ZIP CRC, exclusion of `.env` and `bot.db`, extracted API, package API,
synthetic Sage, publication recovery, native clean/duplicate/persisted/safety,
isolated unique-AppId installer clean install/API/Sage/uninstall, and Defender
scans passed. The installer left neither QA EXE nor registry entry. The
artifact commit is `f0e25a0` on
`codex/coin-prep-fee-approval-artifacts`; independent pinned HTTP downloads
of its ZIP and installer matched both hashes.

The superseded `c4eb072` app shut down cleanly through its native UI with
cancel-offers unchecked and zero offers. The exact `050fe19` EXE then ran
against original TEST 7 as sole process PID `140596` and port 5000 owner,
with the hash above. Testing-authorized Risk Disclosure was acknowledged in
native UI, Sage TEST 7 selected, optional Splash skipped, existing Spacescan
key retained, and MZ selected. Live status showed mainnet Sage fingerprint
`736588221`, CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
bot stopped, XCH `138.470301476875`, MZ `780212.284`, zero open offers,
zero pending Sage transactions, inactive campaign with no fee approval, and
runtime safety ALLOWED with zero blockers. Six live `GET /api/price` calls
returned the MZ midpoint `0.0000675156445` without changing durable
price-history `(count, max id)` from `(40763, 75944)`.

No new campaign, fee approval, offer or wallet transaction was made. Both
24-hour windows, live wallet lifecycle, independent secondary acceptance and
final review remain open. Keep PR #220 draft.
