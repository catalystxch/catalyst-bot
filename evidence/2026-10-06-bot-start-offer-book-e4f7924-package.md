# Fresh offer-book bot-start gate and complete startup repost

Draft PR #220 runtime/source candidate: `e4f79246786bda9a2bfb726f65a703097152fa6f`.
The test-only child `1aa23eadf433b63f4bef2b2f212028752da79b08` changes no runtime or UI file.

## Defects and correction

The preceding exact-source review found that `/api/bot/start` and the direct
`BotLoop.start` path could reach worker startup after a cached or failed Sage
offer read. Both paths now require a fresh three-list Sage result and explicit
`fresh=True`, `using_cache=False` sync metadata. The direct start check closes
the interval between API preflight and worker launch. A stale read returns
`WALLET_OFFER_QUERY_NOT_FRESH` from the API and prevents the worker from
starting. Red/green regressions cover each path.

Startup Dexie reposting previously used missing-wallet-offer recovery only if
the database had zero matching rows. If wallet offers A and B were open but
the database contained only A, B was omitted from reposting. The corrected
path appends every fresh wallet-open offer absent from the DB to the slow RPC
path. A red/green regression covers the partially populated DB case.

Affected Windows tests passed 166 tests and four subtests. The complete
Chromium E2E suite passed 226 tests. The first Linux CI unit-test run failed
in nine older start-success test fixtures whose mock offer managers did not
provide a fresh result. The test-only child supplies explicit fresh results in
those fixtures; its focused Windows set passed 95 tests and Ruff check/format.
All 11 PR checks subsequently passed on the test-only child. The complete
serial Windows backend run passed **7,258 tests, 227 skipped, 431 subtests**
in 1,325.24 seconds, with process exit code zero.

## Exact Windows package

Built from a clean detached checkout at the runtime/source commit. Its
generated version-file line-ending change remained in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-start-repost-e4f7924-build\dist\Catalyst\Catalyst.exe` | `FC76F16FC0A0B3EAD6A7D9D3552B3FAFD2E89154907BD901B79D0AE169CC6409` |
| Bundled `bot_gui.html` | `F4930EBFE6F32437E134EFAC5765E01AF4368FD4B61A8B3EF62A554B86C8A710` |
| `CATalyst-e4f7924-primary-acceptance.zip` | `BF806205F159E3D7508FE1CCB82C95ECEBC3F13D3C8FF653039CAAC269EFD7BB` |
| Unsigned `Catalyst-Setup-e4f7924-1.4.0.exe` | `F0FB6692C470D34DD2DB0915D355840DC7352052DA7022DB5220121C5B8BE9A3` |

Packaged API, synthetic Sage RPC, publication recovery, and native
clean/duplicate/persisted/safety smokes passed in isolated profiles. The ZIP
passed CRC for all 192 entries and its embedded EXE hash matched; the extracted
EXE passed the API smoke. A unique-AppId QA installer performed an isolated
clean install. Its installed EXE matched the clean hash, passed API and Sage
smokes, and was removed with its HKCU registration on uninstall. Defender
custom scans of bundle, ZIP, and installer added no detections. Independent
HTTP downloads of both pinned binaries matched local hashes.

Artifact commit `a8961ffb602ed022cd52e6ef131c85554df4e393`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/a8961ffb602ed022cd52e6ef131c85554df4e393/acceptance-artifacts/CATalyst-e4f7924-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/a8961ffb602ed022cd52e6ef131c85554df4e393/acceptance-artifacts/Catalyst-Setup-e4f7924-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/a8961ffb602ed022cd52e6ef131c85554df4e393/acceptance-artifacts/SHA256SUMS-e4f7924.txt)

## Primary original-profile read-only rollover

The preceding `e6d57a0` app was the sole verified process and port 5000 owner,
with bot stopped, no open offers, inactive Bootstrap, synced Sage, safety
allowed, and unchanged TEST 7 balances. Its read-only monitor had 40 clean
samples through `2026-10-06T06:17:55Z`. That monitor was stopped as historical.
The old app closed through its native window and released port 5000.

The exact `e4f7924` EXE launched as sole PID `164500` and sole port 5000
owner; its running path and SHA-256 matched the clean detached package. The
testing Risk Disclosure was acknowledged in the visible app UI. Sage mainnet
TEST 7 fingerprint `736588221` and MZ/XCH CAT wallet ID `2`, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
were selected. Splash was skipped and the stored Spacescan key was retained.
Dashboard, Offers, P&L, Market Intel and Settings were traversed read-only in
the visible app UI; the Settings safety card changed from loading/blocked to
ALLOWED after its live check. No settings were saved. The bot remained stopped.
Sage was synced, balances remained
`138.470301476875` XCH and `780212.284` MZ, pending transactions zero,
wallet/DB open offers zero, Bootstrap inactive, and safety allowed with an
owned lease. The prior campaign was still stopped with zero authoritative fee
spend. No new campaign, fee, Coin Prep, offer, or wallet action occurred.

The exact-PID/hash stopped-profile monitor is
`E:\catalyst-stability-monitor-e4f7924-clean\trace-60s.jsonl`, with monitor
PID `132576`, starting `2026-10-06T06:25:16Z`. Its first 60-second sample
was clean: process alive, safety allowed, owned lease, Sage synced, bot
stopped, zero open offers, and Windows Backup ready. The **24-hour gate is
pending** until at least `2026-10-07T06:25:16Z`, plus a complete trace and
end-state audit. Previous candidate traces cannot satisfy it. Live
active-offer lifecycle/recovery, the live trading window, secondary
original-profile acceptance, and final review also remain open. PR #220
remains draft; public readiness is not claimed.
