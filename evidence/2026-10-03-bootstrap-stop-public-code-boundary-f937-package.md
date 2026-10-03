# Bootstrap stop public error boundary and exact f937a0c package

Draft PR #220 exact runtime source is
`f937a0c2024d119a44949928edaa69e9d588e723`. It follows the Sage
offer-read correction at `b320dfe` and changes only the Bootstrap stop
exception response and its regression.

CodeQL alert #91 identified a potential exception information flow from
`/api/bootstrap/stop` to its JSON response. Before this correction, a
recognized fee refusal returned the raw exception message. The endpoint
now selects only a fixed public code by allowlist equality and preserves the
established lowercase Bootstrap codes. A mixed-case fee refusal regression
failed before the fix and passed afterward. The affected Bootstrap tests
passed **35**; Ruff, formatting and `git diff --check` passed. CodeQL now
marks alert #91 **fixed**, and all **11 PR #220 checks** passed on exact
`f937a0c`. The full primary Windows backend run on this exact source
passed **7,145 tests, 205 skipped, 425 subtests** in 24m47s.

## Exact Windows package

- Detached clean build: `E:\catalyst-f937-primary-build`
- `Catalyst.exe` SHA-256: `08BEEB94C1D7EA978440AD95E40C71BB89E2066C201D9D88215A8D3971B4F1CF`
- Bundled `bot_gui.html` SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/4a46bfb9f8f737e89328bcb16582a296d529f2bf/acceptance-artifacts/CATalyst-f937a0c-primary-acceptance.zip), SHA-256 `A8248ACB917D14FD68307EA3CDCF6FF0A14FCE8965329BAEDF17395AC56E8355`
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/4a46bfb9f8f737e89328bcb16582a296d529f2bf/acceptance-artifacts/Catalyst-Setup-f937a0c-1.4.0.exe), SHA-256 `81E5EF7A0A25D578D32F28CE1CB93D5639574B630D3DD84A1CB727B3575FF7C8`
- [Artifact manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/4a46bfb9f8f737e89328bcb16582a296d529f2bf/acceptance-artifacts/CATalyst-f937a0c-primary-acceptance.md)

The ZIP has 192 files and passed a full CRC read. The exact EXE passed
packaged API, mock Sage RPC, publication recovery, and native clean,
duplicate, persisted and safety smokes. An isolated unique-AppId installer
clean-installed, matched the package EXE/UI hashes, passed installed API
and Sage smokes, and uninstalled without leftover QA registration. Defender
custom scans of the bundle, ZIP and installer returned zero matching
detections. Independent HTTP downloads of the immutable ZIP and installer
matched the hashes above. The focused Bootstrap cancellation browser suite
passed **11** tests against the exact source. No original profile or wallet
effect occurred.

## Open live gates

At approximately 2026-10-03 04:32 UTC, a separate read-only process used
the exact-source wallet facade and the primary SQLite database in read-only
mode. Sage was reachable, synced to mainnet TEST 7 fingerprint `736588221`,
and held the exact MZ asset in configured CAT wallet ID `2`. XCH confirmed
and spendable were both `138470301476875` mojos; MZ confirmed and spendable
were both `780212284` atomic units. Sage returned a complete 4,095-offer
history with zero open MZ/XCH buys or sells and zero pending transactions.
The primary database had zero open MZ offers. Its latest campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remained stored as `active` despite expiry at
`2026-09-30T11:27:42.748405Z`; it had zero recorded fee spend and zero fee
approvals. This read did not modify wallet or database state.

The exact `f937a0c` EXE has not run against the original TEST 7 profile.
The operator has been asked to launch it manually, personally acknowledge
Risk Disclosure, and connect Sage fingerprint `736588221`; a previous
command-tool live launch was blocked before execution by automatic approval
review and was not retried through another tool. The earlier campaign has
expired; a new 24-hour campaign and fee authority need separate approval
before wallet effects. Exact live offer lifecycle, restart/recovery, both
24-hour windows, full UI acceptance and final review remain open. Keep
PR #220 draft; no main merge, tag, release or public-readiness claim.
