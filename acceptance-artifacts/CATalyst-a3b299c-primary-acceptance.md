# CATalyst a3b299c primary acceptance package

Draft PR #220 exact source: `a3b299c5356a8b5e7f678e1eac9d8131165b140c`.
This unsigned package is for acceptance testing. It is not a release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `F9E02BF9111937E292A2FF12E92F4A38448CC3209F678F13806E6965B4F69617` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-a3b299c-primary-acceptance.zip` | `3E646746240C5630B12F6FDA7985EE9F22F48DEB79490D84B2AE49D77998E02A` |
| `Catalyst-Setup-a3b299c-1.4.0.exe` | `80802F514C511F55E28F8BC5A8C22E46E91E225BEED029D131BD161A3560F511` |

The 192-entry ZIP passed CRC, contained no `.env` or `bot.db`, and embedded an identical EXE. Package API, synthetic Sage RPC, publication recovery, and native clean, duplicate, persisted-profile, and safety smokes passed. A unique-AppId current-user QA installer passed clean install, installed EXE hash comparison, installed API and synthetic Sage smokes, and uninstall. Its EXE and registry entry were absent afterward. Defender custom scans introduced no new detections.

The source limits Bootstrap Stop's public `cancel_results` to each requested offer's validated cancellation outcome. A focused regression first reproduced an unexpected manager diagnostic appearing in the HTTP response, then passed after the fix. All 44 Bootstrap API tests and 15 opt-in browser cancellation-recovery tests passed. Ruff check, format and diff checks passed. The full local Windows backend passed 7,177 tests, with 210 skipped and 427 subtests passed. All 11 PR checks passed on the exact source head and on the first evidence-only descendant `9a912b6`.

Exact `a3b299c` replaced the stopped prior app on original TEST 7. Its sole `Catalyst.exe` process and port 5000 owner matched the clean EXE hash. Native Risk Disclosure acknowledgement and TEST 7 fingerprint selection were completed under the operator's testing authorization. Read-only Sage and app checks found a synced wallet, exact mainnet fingerprint `736588221`, CAT wallet ID `2`, MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, unchanged spendable XCH `138.470301476875` and MZ `780212.284`, zero pending and fillable offers, inactive Bootstrap, and ALLOWED safety with zero blockers. The native optional Splash gate remains open because the available Windows control tool did not deliver scroll input in the 1000×700 window. Independent Chromium confirmed the served overlay scrolls normally and reveals Skip. No wallet effect occurred. The secondary host independently checked exact source/package and isolated native startup within its UI limits. Live wallet lifecycle, complete native UI, both 24-hour windows and final review remain open. Keep PR #220 draft.
