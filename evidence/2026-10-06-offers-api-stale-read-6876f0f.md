# Fail closed on stale Sage offers API reads

Draft PR #220 exact runtime/source: `6876f0f4856b7f6d7984437f9d7e17a02c3ec87b`.

`GET /api/offers` called the unpaired Sage offer-sync method and returned
HTTP 200 with zero current offers when the wallet read failed without a cache.
Its response omitted the failed-read state. A regression reproduced that
response before the fix: expected HTTP 503, received HTTP 200. The endpoint
now consumes the offer book and its freshness metadata under one shared lock,
and returns `wallet_offer_sync_stale` with HTTP 503 unless the result is fresh
and uncached. Fresh offer responses retain the existing shape and durable
publication/discovery authority.

The regression and related endpoint/UI-contract tests passed **83** cases.
Ruff check, Ruff format, and `git diff --check` passed. Exact-source Chromium
passed **226** cases in 165.78 seconds. All **11** PR checks passed on the
source commit. The complete serial local Windows backend passed **7,268**
tests, with 227 skipped and 431 subtests, in 1575.60 seconds; the run exited
zero. Its log is `E:\catalyst-6876f0f-full-windows.log`.

## Exact Windows package

A clean detached checkout at `E:\catalyst-6876f0f-build` produced the
following unsigned acceptance artifacts. The packaged API, synthetic Sage
RPC, upgrade publication recovery, and clean/duplicate/persisted/native
safety launch smokes passed. The 192-entry ZIP passed CRC, contained
`.env.example`, and held an EXE byte-identical to the clean build. A
unique-AppId, separate-name current-user QA installer clean-installed the
same EXE, passed installed API and Sage checks, then uninstalled; its EXE and
QA registry entry were absent afterward. Defender custom scans of the
bundle, ZIP, and installer added zero detections (six historical detections
before and after). Independent HTTP downloads of the pinned ZIP and
installer matched their local SHA-256 hashes; the downloaded ZIP extracted
to the same EXE and passed packaged API smoke.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `8741EA0EA0EB2FA789FC5E2F40029973772BEDC03E8CB1C552448519E54A8E9F` |
| `CATalyst-6876f0f-primary-acceptance.zip` | `2DBEE6D2716B960609B312F800AE2EBD5A5142E5182A5586B89DC2992926514C` |
| Unsigned `Catalyst-Setup-6876f0f-1.4.0.exe` | `2E25C05889E19C4CCD14C32E07C5CAB312D3560E0CE6159C33F83119E48DA545` |

The binaries and manifest are pinned at artifact commit
`5ced42e9a3e7e0e869a7a92fe2bfeef632ab1904` on
`codex/coin-prep-fee-approval-artifacts`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5ced42e9a3e7e0e869a7a92fe2bfeef632ab1904/acceptance-artifacts/CATalyst-6876f0f-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5ced42e9a3e7e0e869a7a92fe2bfeef632ab1904/acceptance-artifacts/Catalyst-Setup-6876f0f-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5ced42e9a3e7e0e869a7a92fe2bfeef632ab1904/acceptance-artifacts/SHA256SUMS-6876f0f.txt)

## Original TEST 7 live read-only rollover

The preceding `b69061b` process was shut down through the native UI with
cancel-offers unchecked. Its exact-PID/hash trace is historical. The clean
`6876f0f` EXE then launched against the original profile as sole PID 117256
and sole port 5000 listener. The on-disk EXE matched the SHA-256 above.
Risk Disclosure was acknowledged in the native UI under the operator's
standing testing authorization. The UI connected Sage mainnet TEST 7
fingerprint 736588221 and selected Monkeyzoo Token MZ/XCH. Read-only API
state identified CAT wallet 2 and asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
The bot was stopped, the wallet synced, Bootstrap inactive, and safety
allowed with an owned renewing lease and no blockers. Balances remained
138.470301476875 XCH and 780212.284 MZ; the app reported zero open
offers. No campaign or wallet action was started.

An exact-PID/path/hash 60-second read-only monitor began at
`2026-10-06T09:38:22Z` in
`E:\catalyst-stability-monitor-6876f0f\trace-60s.jsonl`; its first sample
showed the expected process and hash, stopped bot, synced wallet, zero open
offers, allowed safety, and owned lease. The 24-hour gate cannot pass before
`2026-10-07T09:38:22Z` plus an end-state review. Both final-candidate
24-hour windows, active-offer lifecycle/recovery, secondary original-profile
acceptance, and final review remain open. PR #220 stays draft.
