# CATalyst f5aa01f primary acceptance package

Draft PR #220 exact source: `f5aa01fff5aedbe4faf95d9b1fcfd0bf584b5df1`.
This unsigned package is for acceptance testing. It is not a release or a public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `0046FDBC6A4C362FF81DA67341C92619B08998F033FC11D61EAA353AF549489C` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-f5aa01f-primary-acceptance.zip` | `BDAC64A51F894AA02146D160F673DE3DDB26F1A610AD11236E436A4ACBBF082C` |
| `Catalyst-Setup-f5aa01f-1.4.0.exe` | `B8A8545728FF4996252E38A3E6787045DB751432261AB7D142D7E3A3C869CB61` |

The 192-entry ZIP passed CRC, contained no `.env` or `bot.db`, and embedded an identical EXE. The EXE passed packaged API, synthetic Sage RPC, publication recovery, and native clean, duplicate, persisted-profile, and safety smokes. A unique-AppId current-user QA installer passed clean install, installed EXE hash comparison, installed API and synthetic Sage smokes, and uninstall. Its EXE and registry entry were absent afterward. Defender custom scans of the bundle, ZIP, and installer introduced no new detections.

The source keeps stopped-session P&L, dashboard, and standard Coin Prep fee previews from invoking the stateful trading price engine. It selects a quote for the configured CAT asset and ignores a stale prior-session midpoint while stopped. Red/green regressions and focused endpoint/fee tests passed; all 11 exact-source PR checks passed.

The full local Windows backend run and original TEST 7 live read-only verification are pending. No campaign, fee approval, or wallet transaction has been made by this package. Live wallet lifecycle, both 24-hour windows, independent secondary acceptance, and final review remain open. Keep PR #220 draft.
