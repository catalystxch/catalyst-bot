# Fresh wallet-offer verification before bot start

Draft PR #220 exact runtime/source: `e6d57a057cfe55d1116e53bf74e39683dd041a0e`.
The local integration branch has a different name, but this commit is the
verified head of the remote `codex/coin-prep-fee-approval` branch.

## Defects and verification

The preceding `69543db5e0a29a7e94cd5d3577c5ef4b89a7d172` correction
prevents four backend paths from using a cached Sage offer book as though it
were fresh: Market Intelligence local edges, `/api/check-resume`, Dexie
reposting, and BotLoop startup reposting. Focused red/green regressions passed.
The complete serial Windows backend suite passed **7,254 tests, 225 skipped,
431 subtests** in 1,342.32 seconds. All 11 PR CI checks passed on that commit.

Review then found a separate frontend start-path defect: `checkForResume()`
treated a failed or nonfresh live wallet-offer check as an empty book and could
continue to Start Bot. A Playwright regression first failed for both
`wallet_offer_query_not_fresh` and a network failure. Exact `e6d57a0` returns
an indeterminate result and prevents Start Bot dispatch in either case. The
focused frontend suite passed 44 tests, the complete Chromium E2E suite passed
226 tests, and all 11 PR CI checks passed on the exact runtime commit. The
only runtime difference from `69543db` is the frontend correction; the full
backend suite was not repeated for that UI-only child. This evidence does not
replace the live active-offer lifecycle gate.

## Exact Windows package

Built from a clean detached checkout at the exact source commit. The
generated version-file line ending change remained in that detached checkout.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-wallet-fresh-e6d57a0-build\dist\Catalyst\Catalyst.exe` | `0B6D780E8AD9CD17830AEB9831B77DC5E88C4971D97769CFC86D03D3FE012DBF` |
| Bundled `bot_gui.html` | `F4930EBFE6F32437E134EFAC5765E01AF4368FD4B61A8B3EF62A554B86C8A710` |
| `CATalyst-e6d57a0-primary-acceptance.zip` | `BA0BEE8E7290278CD1132384C5057AEEE896F9B5EC680CB98690D403E12D5C5C` |
| Unsigned `Catalyst-Setup-e6d57a0-1.4.0.exe` | `06B206EC3407EFE38BB8BD46BCF61F75449B018E9EDDC375AAC0F048D484CA7A` |

Packaged API, synthetic Sage RPC, publication recovery, and native
clean/duplicate/persisted/safety smokes passed in isolated profiles. The ZIP
passed CRC for all 192 entries, embedded EXE comparison, and extracted API
smoke. A unique-AppId QA installer performed a clean isolated installation;
the installed EXE hash matched, its API and Sage smokes passed, and uninstall
removed the test binary and HKCU registration. Defender custom scans of the
bundle, ZIP, and installer added no detections. A scan already in progress
prevented the first concurrent installer scan; the sequential retry passed.
Independent HTTP downloads of the pinned ZIP and installer matched the local
hashes.

Artifact commit `f315e5c014c7460816edf611c6e9eff45d510a4e`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f315e5c014c7460816edf611c6e9eff45d510a4e/acceptance-artifacts/CATalyst-e6d57a0-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f315e5c014c7460816edf611c6e9eff45d510a4e/acceptance-artifacts/Catalyst-Setup-e6d57a0-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f315e5c014c7460816edf611c6e9eff45d510a4e/acceptance-artifacts/SHA256SUMS-e6d57a0.txt)

## Primary original-profile read-only rollover

The preceding `e9cf003` process was stopped through the packaged shutdown
path with offer cancellation disabled. It exited and released port 5000. The
exact `e6d57a0` EXE launched as sole PID `154868` and sole port 5000 owner;
the running path and hash matched the clean package. The testing Risk
Disclosure was acknowledged in the visible native UI. Sage mainnet TEST 7
fingerprint `736588221`, CAT wallet ID `2`, and the exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
were selected. Dashboard, Offers, P&L, Market Intelligence, and Settings were
traversed read-only. The wallet was healthy and synced; balances stayed
`138.470301476875` XCH and `780212.284` MZ. The bot remained stopped,
Bootstrap inactive, safety allowed with an owned lease, and wallet and local
open-offer counts zero. No campaign, fee, Coin Prep, offer, or wallet action
occurred.

The authoritative exact-PID/hash stopped-profile monitor is
`E:\catalyst-stability-monitor-e6d57a0-clean\trace-60s.jsonl`, with monitor
PID `19784`, starting `2026-10-06T05:38:20Z`. Its first three 60-second
samples through `05:40:22Z` were clean: process alive, safety allowed, lease
owned and renewing, Sage synced, bot stopped, zero open offers, and Windows
Backup ready. The **24-hour gate is pending** until at least
`2026-10-07T05:38:20Z` plus complete trace and end-state audit. Previous
candidate traces are historical and cannot satisfy it. The secondary exact
candidate original-profile acceptance, active-offer lifecycle/recovery, live
trading window, and final review also remain open. PR #220 stays draft and
public readiness is not claimed.
