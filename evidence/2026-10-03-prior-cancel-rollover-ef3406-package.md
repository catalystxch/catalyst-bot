# Prior cancellation rollover gate and exact ef3406 package

Draft PR #220 runtime/source commit:
`ef3406fb066d6d398d480f2a7d35b17b904dce10`.

## Defect and correction

A stopped Bootstrap campaign can retain a nonterminal Sage offer intent after
cancellation was submitted but not confirmed. The prior API recorded a
successful stop, then returned `needs_attention=false` and allowed Start or
Renew to create new campaign authority for the same wallet and asset. That
could overlap the new campaign with an older live offer.

The new endpoint regression was red on the preceding source: status returned
`needs_attention=false` after `CANCEL_SUBMITTED_UNCONFIRMED`. Exact source
`ef3406f` continues to surface a stopped cancellation while its trade ID is
nonterminal and rejects Start/Renew with
`bootstrap_prior_cancel_unconfirmed`. Once authoritative reconciliation makes
the prior intent terminal, the status clears and Start is allowed. The
browser regression confirms the pending status keeps Preview and Start
disabled.

The Bootstrap API file passed 38 tests; the affected Bootstrap, fee renewal,
recovery and offer cancellation selection passed 211 tests. Its Chromium
file passed 15 tests, and the complete Chromium suite passed 208 tests.
Ruff, format and `git diff --check` passed. All 11 exact-source PR checks
passed. The full local Windows backend command
`python -m pytest -q tests --ignore=tests/e2e` passed **7,154 tests** with
**one skipped** and **427 subtests passed** in 23m 37s.

## Exact Windows package

- Clean detached build: `E:\catalyst-ef3406-primary-build`.
- `Catalyst.exe` SHA-256:
  `2762508F8CD16FB1EF6D57E273B670C0519AD2722C2AC9CE5203224A1C81ECB7`.
- Bundled `_internal/bot_gui.html` SHA-256:
  `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7`.
- 192-file ZIP SHA-256:
  `F63F5B5A01FF2DF79850FF7926BB703AE812D57462DB7CC0709EC908FB816F32`.
- Unsigned installer SHA-256:
  `909D35F93E7BC8322BBD3F1C37328BA80B4F93D4C08B5A23A6354EB68128BCE3`.

The detached package passed API, synthetic Sage RPC, publication recovery,
native clean/duplicate/persisted/safety, full ZIP CRC and extraction, embedded
EXE hash, and extracted API smoke. A unique-AppId current-user QA installer
passed clean install, prior `00767dc` to `ef3406f` same-version upgrade,
rollback, restore, installed API/native/Sage, and final uninstall. Installed
EXE hashes matched at every step; the QA registration and directory were
absent afterward. Defender custom scans of the bundle, ZIP and installer
completed with zero matching detections. Fresh HTTP downloads of both pinned
artifacts matched their local hashes.

Artifact commit: `aea4290482fef0458759e988d8cfe580d6f56f8c`.

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/aea4290482fef0458759e988d8cfe580d6f56f8c/acceptance-artifacts/CATalyst-ef3406-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/aea4290482fef0458759e988d8cfe580d6f56f8c/acceptance-artifacts/Catalyst-Setup-ef3406-1.4.0.exe)

## Open gates

The exact package has not run against the original TEST 7 live profile. Sage
read-only preflight confirmed mainnet fingerprint `736588221`, CAT wallet ID
`2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
zero pending transactions and zero fillable offers across the full 4,095-offer
history. An earlier automatic approval review rejected command-tool launch
of a predecessor against that profile before execution; do not route around
that rejection. The operator must manually start the exact EXE and personally
acknowledge Risk Disclosure. The prior campaign is expired; no new campaign
or fee approval has been received. Live lifecycle, restart/recovery, full UI,
both 24-hour windows, independent secondary acceptance and final review
remain open. PR #220 stays draft; no main merge, tag, release or public-
readiness claim.
