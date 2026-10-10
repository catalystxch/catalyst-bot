# Offer diagnostic rejects a cached Sage book

Draft PR #220. Exact runtime/source `e9cf003f5adbdc6b969e1fbd1e4b2cc68e7296a9`.

The `/api/offers/diagnostic` route called `OfferManager.sync_from_wallet()` and
then compared its returned open offers with the database. That manager can
return its cached book when Sage `get_all_offers` fails, marking the sync
metadata `fresh=False`. When both the cached book and DB were empty, the route
reported `local_book_consistent=True` and told the operator that the wallet and
DB agreed, despite having no fresh wallet read.

A red endpoint regression reproduced this false agreement after a simulated
Sage read failure. The route now checks `get_wallet_sync_meta()` after the
manager sync. Any missing or non-fresh metadata sets `wallet_error`, makes the
assessment inconsistent, and explains that a cached offer book cannot prove
agreement. A fresh empty wallet-book regression preserves the positive result.
The affected endpoint and wallet-sync tests passed: **64 tests**. Ruff check,
Ruff format, and `git diff --check` passed. Independent secondary-PC review
and the same focused 64 tests found no blocking issue.
The full serial Windows backend passed **7,247 tests, 225 skipped and 431
subtests** in 1,436.60 seconds, exit zero. All **11 exact-source PR checks**
passed on `e9cf003`.

## Clean Windows package

Built from a clean detached checkout at `E:\catalyst-offer-diagnostic-e9cf003`.
The bundled `bot_gui.html` hash remains
`9FD727C40DA72C56BE948B4BFBBD4205B8B2DE33B772ACAF32C5E5DCB37B1801`;
the change has no frontend bytes.

| Artifact | SHA-256 |
| --- | --- |
| `dist\Catalyst\Catalyst.exe` | `2C9D02FFDD0BEE481A0AECD8363A99D63D53808B11BB5E2A3DD147B306189D15` |
| `CATalyst-e9cf003-primary-acceptance.zip` | `F43CD3E8710B22EE3F123C9C099CBBA98E70CFDE27A574B3166B919D635D52B6` |
| Unsigned `Catalyst-Setup-e9cf003-1.4.0.exe` | `7F375B5903E1526C676A8D8A135966CECB3D3802F16C5E01A0A0101AE8504343` |

Packaged Sage RPC, API, interrupted-publication recovery, and clean/duplicate/
persisted/native safety smokes passed. The ZIP passed CRC for all 206 entries;
its embedded EXE hash matched the clean build, and the extracted EXE passed
the packaged API smoke. A separate-name, unique-AppId QA installer installed
an EXE with the same hash to an isolated E: directory. Installed API and Sage
smokes passed, then silent uninstall removed the test EXE and HKCU
registration. Microsoft Defender custom scans of the bundle, ZIP and installer
added zero detections (6 before and after).

The ZIP, installer and hash manifest are pinned at artifact commit
`cdbd8cb60992e4172be5cdedb048f90a165b5338`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cdbd8cb60992e4172be5cdedb048f90a165b5338/acceptance-artifacts/CATalyst-e9cf003-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cdbd8cb60992e4172be5cdedb048f90a165b5338/acceptance-artifacts/Catalyst-Setup-e9cf003-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cdbd8cb60992e4172be5cdedb048f90a165b5338/acceptance-artifacts/SHA256SUMS-e9cf003.txt)

Independent HTTP downloads of the pinned ZIP and installer matched their
local SHA-256 hashes.

The secondary PC independently downloaded and verified the pinned ZIP,
installer and extracted EXE, then passed packaged API, synthetic Sage,
publication recovery, native first-launch and Defender checks on isolated
profiles. It found no original-wallet effect.

## Primary original-profile read-only rollover

The stopped `61be438` app was verified as the sole original TEST 7 process
and port 5000 owner, with exact EXE hash, Sage mainnet fingerprint `736588221`,
CAT wallet ID `2`, exact MZ asset, unchanged `138.470301476875` XCH and
`780212.284` MZ, zero wallet and DB open offers, inactive Bootstrap, an owned
lease and safety allowed. The clean `/api/shutdown` path was invoked with
`cancel_offers:false`; that process exited and released port 5000. No
wallet-wide cancellation was requested.

The exact `e9cf003` EXE launched against the same original profile as sole
PID `143696` and port 5000 owner; its running path and hash matched the clean
package. Under the operator's standing testing authorization, Risk Disclosure
was acknowledged in the native UI, Sage `TEST 7` fingerprint `736588221` was
selected, Splash was skipped, the existing Spacescan key was retained without
editing it, and the `MZ_XCH` pair was selected. Sage reported healthy and
synced. The bot stayed stopped, Bootstrap had no current campaign, safety was
allowed with an owned lease, both balances were unchanged, and a fresh wallet
offer diagnostic showed zero wallet/DB open offers and no wallet read error.
The native Offers view showed zero active offers and three historical fills.

The earlier `61be438` primary and secondary monitors remain historical. An
initial duplicate monitor startup was discarded before gate timing. The
authoritative clean exact-PID/hash 60-second trace is
`E:\catalyst-stability-monitor-e9cf003-clean\trace-60s.jsonl`, monitor PID
`73112`, beginning `2026-10-06T04:36:03Z`. Its first sample was clean: Sage
synced, bot stopped, zero offers, safety allowed, owned renewing lease and
Windows Backup ready. The stopped-profile 24-hour gate cannot be assessed
before `2026-10-07T04:36:03Z` and a full trace/end-state audit. Neither live
active-offer lifecycle nor the secondary original-profile e9 rollover was
complete at this checkpoint. No wallet action was requested for this
correction. PR #220 remains draft.
