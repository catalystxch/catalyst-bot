# Fresh Sage offer evidence for Market Intel and graceful migration

Draft PR #220 exact runtime/source: `b69061b9d08c490fa2702d96173a7bbfddb1b5b7`.

## Defect and correction

Market Intel still read Sage offers and their freshness metadata in separate
calls. Another thread could interleave a fresh read and make a cached offer
book appear authoritative. The live local-offer edge now uses the paired
`sync_from_wallet_with_meta()` result introduced in `82a715d`.

Graceful settings migration could likewise interpret a failed or cached empty
offer book as proof that there were no offers to cancel. Its planning and
completion checks now require a fresh, uncached Sage result. A cycle whose
wallet sync was stale cannot complete migration with empty offer IDs. The
existing cancellation authority remains pending until a fresh read.

The Market Intel and graceful migration regressions failed before the fix and
passed afterward. Focused checks passed 36 dashboard endpoint tests, 45
dashboard and wallet-sync tests, 62 bot-recovery/dashboard/wallet-sync tests,
and five graceful-migration cases. Ruff and format checks passed. The full
serial Windows backend passed **7,267 tests, 227 skipped, 431 subtests** in
1,654.50 seconds. Exact-source Chromium E2E passed **226** tests in 184.70
seconds. All 11 PR checks passed on `b69061b`.

## Exact Windows package

Built cleanly in detached checkout `E:\catalyst-b69061b-build`. The bundled
HTML SHA-256 is `F4930EBFE6F32437E134EFAC5765E01AF4368FD4B61A8B3EF62A554B86C8A710`,
byte-identical to the preceding candidate.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `6175D9BEE731753FF3075BB587CC2025B985CB0DB73250D423FF2DD30E2E1153` |
| `CATalyst-b69061b-primary-acceptance.zip` | `A4B74A2D544D6DEF6CAB30BC493801C81127CEAF1DD328068EE3E3D8E157A226` |
| Unsigned `Catalyst-Setup-b69061b-1.4.0.exe` | `25A75D2000691B44ACD79A8CA272F4BDD29AFD074A90AEF0B08E29DCEDA742D0` |

Packaged API, synthetic Sage RPC, publication recovery, native clean,
duplicate, persisted and safety startup, ZIP CRC and extracted API passed. An
isolated unique-AppId installer clean-installed the exact EXE, passed installed
API and Sage checks, and uninstalled without changing the normal registration.
Defender scans of the bundle, ZIP, and installer added zero detections.
Independent HTTP downloads of the pinned ZIP and installer matched their
hashes. The three files are committed at artifact commit
`f5874a2b47f56e5c5713abfc6ce74c4e2ea34f31`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f5874a2b47f56e5c5713abfc6ce74c4e2ea34f31/acceptance-artifacts/CATalyst-b69061b-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f5874a2b47f56e5c5713abfc6ce74c4e2ea34f31/acceptance-artifacts/Catalyst-Setup-b69061b-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f5874a2b47f56e5c5713abfc6ce74c4e2ea34f31/acceptance-artifacts/SHA256SUMS-b69061b.txt)

## Original TEST 7 profile

The previous `82a715d` stopped app shut down through its visible native
window without selecting offer cancellation. Its stopped-profile trace ended
at process exit after 53 clean samples; that trace is historical.

The exact `b69061b` EXE started through the visible native app as sole PID
`159788` and sole port 5000 owner. The process path and on-disk SHA-256 matched
the clean build. Testing Risk Disclosure was acknowledged, Sage mainnet TEST 7
fingerprint `736588221` was selected, optional Splash was skipped, and the
existing configured Spacescan key continued. The native Dashboard selected
Monkeyzoo Token (`MZ_XCH`). Read-only status showed CAT wallet ID `2`, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
unchanged `138.470301476875` XCH and `780212.284` MZ, bot stopped, no open
wallet or DB offers, Bootstrap inactive, synced Sage, and safety allowed with
an owned lease. The offer diagnostic used a fresh wallet read and reported
wallet/DB agreement with zero open offers. No campaign, offer, or fee approval
was made.

The exact-PID/path/hash 60-second stopped-profile monitor is
`E:\catalyst-stability-monitor-b69061b\monitor.ps1`. Its trace began
`2026-10-06T08:53:07Z` and the first two samples passed with safety allowed,
lease owned, Sage synced, bot stopped, zero open offers, and backup ready.
The complete 24-hour result cannot be assessed before
`2026-10-07T08:53:07Z` plus an end-state review. Secondary original-profile
live acceptance, active-offer lifecycle and recovery, the live-trading
24-hour window, and final review remain open. PR #220 remains draft.
