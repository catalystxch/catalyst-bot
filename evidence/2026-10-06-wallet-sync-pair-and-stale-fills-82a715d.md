# Atomic wallet-offer freshness and stale-cycle fill safety

Draft PR #220 exact runtime/source: `82a715d11eb4dca8ce1a4953705497dd8b737e7f`.

## Defects and correction

Two concurrent wallet-offer synchronizations could interleave between a
caller's `sync_from_wallet()` and separate `get_wallet_sync_meta()`. A caller
could then pair its cached or failed offer result with another thread's fresh
metadata and proceed as though its own result were authoritative. An
`OfferManager` reentrant lock now serializes wallet synchronization and
`sync_from_wallet_with_meta()` returns the offer result with its own metadata
under that lock. Bot start, bot cycles, resume, Dexie repost, and the offer
diagnostic use the paired result. Standalone status metadata reads remain
nonblocking across Sage RPC calls.

The bot cycle also reached fill detection after a stale wallet-offer read.
That could advance fill state using a cached book. It now skips fill detection
for that cycle and keeps the prior baseline until a fresh wallet read.

Both defects had failing regressions before the fixes and passed afterward.
The first fix is commit `9b54f40a5614ed13588a4708a7f9f2105104eeb7`, its
test-fixture-only child is `9528f77898f5062aa5971510f795aaec60672a4d`,
and the stale-fill correction is exact runtime head `82a715d`. The first
focused suite passed 208 tests, the mutation/recovery suite 338, the adapted
fixture slice 152, and the second focused suite 143. Ruff check and format
passed. Exact `82a715d` Chromium E2E passed 226 tests. The full serial
Windows backend and CI on `82a715d` each found one obsolete source-inspection
assertion: it searched for the old direct fill-tracker call inside the cycle,
which now calls the guarded helper. Test-only child
`fa15dad32e1328d3674df60567a3074d303af36e` asserts both the cycle order
and the helper's stale guard. The corrected test passed locally. All 11 PR
checks then passed on that test-only child; its Linux unit suite passed 7,247
tests with 241 skipped. The complete serial Windows rerun passed **7,261
tests, 227 skipped, 431 subtests** in 997.12 seconds.

## Exact Windows package

Built cleanly in detached checkout `E:\catalyst-stale-fill-82a715d-build`.
The bundled HTML is byte-identical to the preceding UI candidate.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `9BF6193C74C1CCDF43B2C98986266973EB7CFB3FFCF347BB227674CE03A85FE3` |
| Bundled `bot_gui.html` | `F4930EBFE6F32437E134EFAC5765E01AF4368FD4B61A8B3EF62A554B86C8A710` |
| `CATalyst-82a715d-primary-acceptance.zip` | `EA2059A80D484A38C28680E4AE36D39A148908F355115BD23AD5051E905810A3` |
| Unsigned `Catalyst-Setup-82a715d-1.4.0.exe` | `685E943617E8C0269CC0F39DD1EF12FD002AA6200BBFAE6AE58653B4062E77AA` |

Packaged API, synthetic Sage RPC, interrupted-publication recovery, native
clean/duplicate/persisted/safety smokes, ZIP CRC and extracted API passed.
An isolated unique-AppId QA installer installed the exact EXE, passed API and
Sage smokes, and uninstalled without affecting the normal registration.
Defender scans of the bundle, ZIP, and installer added zero detections. The
three acceptance files were committed at artifact commit
`673e2aa0b95f834bbd410e4b604e7b0b0a51c5d0`. Independent HTTP downloads
of the pinned ZIP and installer matched the hashes above.

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/673e2aa0b95f834bbd410e4b604e7b0b0a51c5d0/acceptance-artifacts/CATalyst-82a715d-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/673e2aa0b95f834bbd410e4b604e7b0b0a51c5d0/acceptance-artifacts/Catalyst-Setup-82a715d-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/673e2aa0b95f834bbd410e4b604e7b0b0a51c5d0/acceptance-artifacts/SHA256SUMS-82a715d.txt)

## Live status and remaining gates

The predecessor `e4f7924` ran as the sole original-profile PID `164500` with
its expected hash and port 5000 owner, stopped bot, zero open offers and
pending transactions, synced Sage, and safety allowed. Its monitor had 65
clean one-minute samples by the preflight; that trace is historical for this
new candidate. The old process shut down from the visible native window and
released port 5000 without offer cancellation.

The exact `82a715d` EXE started through the visible native app as sole PID
`146124` and sole port 5000 owner. Its actual process path matched the clean
build and its SHA-256 matched the table above. The testing Risk Disclosure
was acknowledged in the native window. Sage mainnet TEST 7 fingerprint
`736588221`, CAT wallet ID `2`, and exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
were selected. Optional Splash was skipped and the existing configured
Spacescan key continued. The native Dashboard, Offers, P&L, Market
Intelligence, Settings, Logs, Data Reset, Help, and About views rendered.
Offers showed zero active buys/sells and three historical fills. Logs
backfilled this session's Sage login, pair selection, and order-book refresh.
Settings showed safety `ALLOWED`, zero unresolved operations/reservations/
publications, and an owned renewing lease. No settings were saved, reset
action clicked, or bot/campaign started. The app was left on Dashboard.

Read-only API and Sage checks after selection showed synced wallet, unchanged
`138.470301476875` XCH and `780212.284` MZ, zero pending transactions, zero
wallet or DB open MZ offers, stopped bot, inactive Bootstrap, and safety
allowed with no reason code. No new campaign, fee approval, wallet transaction,
or offer was made.

The exact-PID/hash 60-second stopped-profile monitor began at
`2026-10-06T07:54:51Z` as monitor PID `136732`, script
`E:\catalyst-stability-monitor-82a715d-clean\monitor.ps1` SHA-256
`B2BFFB480F958980A0D6E937D71E21159B84E09ACF7A776D76299E00ED02DFFA`.
Its first sample passed: process alive, safety allowed, lease owned, Sage
synced, bot stopped, zero offers, backup ready. The full 24-hour gate cannot
complete before `2026-10-07T07:54:51Z` and requires a complete trace plus
end-state audit. Independent secondary exact-candidate acceptance,
active-offer lifecycle and recovery, the live-trading 24-hour window, and
final review remain open. PR #220 remains draft; public readiness is not
claimed.
