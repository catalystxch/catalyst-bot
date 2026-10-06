# Fail closed on unclassifiable Sage offers

Draft PR #220 exact runtime/source: `a5f407435f86649ebcb6a6a9275c2f6a8e36d362`.

The Sage offer classifier could treat an unknown status on an MZ/XCH offer as
closed, treat an open offer without a usable pair summary as irrelevant, and
exclude a pending cancellation from the wallet-open book while that offer
remained fillable. A classification or wallet-read exception could also leave
the previous wallet-sync freshness metadata in place.

Regression cases reproduced these unsafe results before the fix. Classification
now refuses unknown selected-pair or summary-free statuses, refuses an open
offer whose pair cannot be identified, and counts `PENDING_CANCEL` (integer or
string) as wallet-open exposure until confirmation or expiry. Wallet-read and
classification errors mark the sync stale and return only cached data with
explicit stale metadata; the bot's existing freshness gates then block use of
that book.

The clean detached checkout at `E:\catalyst-unknown-offers-a5f4074-build`
passed Ruff check and format. Its serial Windows backend passed 7,277 tests,
with 227 skipped and 433 subtests passed in 1300.99 seconds. The exact clean
EXE passed packaged API, synthetic Sage RPC, publication recovery, native
clean/duplicate/persisted/safety launches, ZIP extraction and extracted API,
and a unique-AppId QA installer clean install, installed API/Sage, and
uninstall. ZIP CRC passed; Defender custom scans of the bundle, ZIP and
unsigned installer added zero detections.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `A71C4FBB820C432D9AF8EA0089990FBD73179A3D1649E4CCBD339EDAB4B0F13B` |
| Bundled `bot_gui.html` | `F4930EBFE6F32437E134EFAC5765E01AF4368FD4B61A8B3EF62A554B86C8A710` |
| `CATalyst-a5f4074-primary-acceptance.zip` | `569E5C43A195084268104B5959F13B2D0517E2B927A739498BD3DB3D2009B91A` |
| Unsigned `Catalyst-Setup-1.4.0.exe` | `1A3E66846A0534BD405618464B82BEAB69DD436C6F94A83D790C4E30960B7818` |

The ZIP and installer are pinned at artifact commit
`187b27fa5665c0c056fba50e3b20d4146d43c564`. Independent HTTP downloads
matched both SHA-256 hashes. The downloaded ZIP passed CRC, contained 192
entries, and contained an EXE matching the clean-build hash:

- [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/187b27fa5665c0c056fba50e3b20d4146d43c564/acceptance-artifacts/CATalyst-a5f4074-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/187b27fa5665c0c056fba50e3b20d4146d43c564/acceptance-artifacts/Catalyst-Setup-a5f4074-1.4.0.exe)

The existing original TEST 7 process remains the preceding `24ba013`
candidate. No new wallet effect or campaign was initiated for `a5f4074`.
Exact live rollover, active-offer lifecycle and recovery, secondary
original-profile acceptance, both final-candidate 24-hour windows, and final
review remain open. PR #220 stays draft.
