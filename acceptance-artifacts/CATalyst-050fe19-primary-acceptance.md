# CATalyst 050fe19 primary acceptance package

Draft PR #220 exact source: `050fe196d0fd41290724ac6b20a2c177ad3c2188`.
This unsigned package is for acceptance testing. It is not a release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `ADBA206BA661A2E4A50338A078FFBE9AE4BD174C1B74E516E5C4EC0CB6BFCB46` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-050fe19-primary-acceptance.zip` | `E52203F29AC2873DABE09A36E17FEC369B0FC826B5F0CCB95F39C141A85346E3` |
| `Catalyst-Setup-050fe19-1.4.0.exe` | `D112805AF6D4F4A8D76B3677C94427CA66338755605CB9F92F5CBB7083E06360` |

The 206-entry ZIP passed CRC, contained no `.env` or `bot.db`, and extracted an identical EXE that passed the packaged API smoke. The EXE passed packaged API, synthetic Sage RPC, publication recovery, and native clean, duplicate, persisted-profile, and safety smokes. A unique-AppId current-user QA installer passed clean install, installed EXE hash comparison, installed API and synthetic Sage smokes, and uninstall; its EXE and registry entry were absent afterward. Defender custom scans of the bundle, ZIP, and installer introduced no new detections.

The source routes both bot-present and pre-bot `GET /api/price` through a read-only, selected-pair Dexie quote. It rejects rows missing the exact CAT asset ID, even if a ticker matches. A missing-asset-first, exact-second regression failed before the fix and passed afterward; a missing-asset-only response fails closed. Focused tests passed 68 cases and four subtests. All 11 PR checks passed on the exact source. The full local Windows backend suite was still running when this manifest was written.

The exact EXE was started against the original TEST 7 profile for read-only acceptance: sole process PID 140596 and port 5000 owner matched its hash; Sage mainnet fingerprint `736588221`, MZ asset, wallet ID `2`, stopped bot, unchanged balances, zero DB open offers, zero pending Sage transactions, and allowed safety state matched the previous baseline. Six public price reads returned the MZ midpoint `0.0000675156445` without adding a price-history row; its durable `(count, max id)` stayed `(40763, 75944)` before and after. No campaign, fee approval, or wallet transaction was made.

Live wallet lifecycle, both 24-hour windows, independent secondary acceptance, and final review remain open. Keep PR #220 draft.
