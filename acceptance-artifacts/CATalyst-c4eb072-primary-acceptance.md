# CATalyst c4eb072 primary acceptance package

Draft PR #220 exact source: `c4eb072e32ab0c345aed5ad5d0d453851952cead`.
This unsigned package is for acceptance testing. It is not a release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `650BE119C3020585916BE680705C4B4E2D3C088062E95BBD6B93CA28FC18A5AE` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-c4eb072-primary-acceptance.zip` | `46E8FB277202875E0E3CACC709284821BA599DB3AC65D12D8938109E487110A0` |
| `Catalyst-Setup-c4eb072-1.4.0.exe` | `3E384CD757605452C2A82846491BA84D289158A81247BD9298C10CADC037DC44` |

The 206-entry ZIP passed CRC and contained no `.env` or `bot.db`; its extracted EXE matched the clean build and passed the packaged API smoke. The detached EXE passed packaged API, synthetic Sage RPC, publication recovery, and native clean, duplicate, persisted-profile, and safety smokes. A separately named, unique-AppId current-user QA installer passed clean install, installed EXE hash comparison, installed API and synthetic Sage smokes, and uninstall. Its executable and registry entry were absent afterward. Defender custom scans of the bundle, ZIP, and installer introduced no new detections.

The source makes both bot-present and pre-bot `GET /api/price` use an expiring, selected-pair, read-only Dexie quote. The prior pre-bot path could select the first unrelated ticker row. The wrong-first, exact-second regression failed before the fix and passed afterward. Focused backend tests passed 88 cases and four subtests. All 11 PR CI checks passed on the exact source. The full local exact-source Windows suite was still running when this manifest was written.

The exact EXE was started against the original TEST 7 profile for read-only acceptance: sole process and port owner matched its hash; Sage mainnet fingerprint `736588221`, MZ asset, wallet ID `2`, stopped bot, unchanged balances, zero DB open offers, and allowed safety state matched the previous baseline. Six public price reads returned the MZ quote without adding a price-history row. No campaign, fee approval, or wallet transaction was made.

Live wallet lifecycle, both 24-hour windows, independent secondary acceptance, and final review remain open. Keep PR #220 draft.
