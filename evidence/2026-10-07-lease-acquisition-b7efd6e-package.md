# Exact b7efd6e lease acquisition and primary package acceptance

All times below are UTC. This is draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) evidence, not release authorization.

## Source and defect

- Exact runtime/source: `b7efd6e3e292ffa62e32973347982eaf03c18a7a` on `codex/coin-prep-fee-approval`. The PR remained draft against `main`, and all 11 CI checks passed on this commit.
- The previous lease acquisition and recovery successor adoption could report success after their durable transaction had outlived the lease expiry. The correction rechecks the durable expiry before returning success. Red/green regressions and 470 affected tests passed.
- Full serial Windows backend: **7,312 passed, 232 skipped, 433 subtests passed** (29m19s). Chromium: **231 passed**. Ruff check/format and diff whitespace checks passed.

## Detached Windows package

- Clean build executable: `E:\catalyst-lease-acquire-b7efd6e-build\dist\Catalyst\Catalyst.exe`; SHA-256 `49CFEC41B7BAB868D19820B18FE8EBA8A07EC38EB8FAABFA3FF2B1DFA4D0DC73`.
- Bundled `bot_gui.html` SHA-256 `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574`, byte-identical to the prior UI.
- Acceptance ZIP SHA-256 `3F7E6F7D99CFA7A1F00585F91CA967F82697634873959C0F0A6222567F50CD63`. All 192 entries passed CRC; the extracted executable matched the clean build and its API smoke passed. No `.env`, database, WAL, SHM, or crash log was included.
- Unsigned installer SHA-256 `F20DB29121D3E266C5278DFD42041BC9D0F09D65863B0052BE4F35E2A1E83C44`.
- Packaged API, synthetic Sage RPC, interrupted-publication recovery, and native clean, duplicate, persisted, and safety smokes passed. A unique-AppId QA install, installed API/Sage smoke, and uninstall passed. A QA same-version upgrade from `0d1096e` to `b7efd6e` matched both exact binary hashes and uninstalled cleanly. Defender baseline remained six detections with no new detection for bundle, ZIP, or installer. The installer is intentionally unsigned while draft.
- Pinned artifact commit: `23dacd15b3cb0213715c95f7db09402a80954a8c`. Independent HTTP downloads of the [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/23dacd15b3cb0213715c95f7db09402a80954a8c/acceptance-artifacts/CATalyst-b7efd6e-primary-acceptance.zip) and [installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/23dacd15b3cb0213715c95f7db09402a80954a8c/acceptance-artifacts/Catalyst-Setup-b7efd6e-1.4.0.exe) matched the hashes above.

## Original TEST 7 read-only rollover

- The prior `0d1096e` app was stopped with zero offers. Its native shutdown was completed with **Cancel all currently active wallet offers unchecked**. The old PID and port 5000 owner exited normally. Its stability trace is historical.
- The exact `b7efd6e` executable was opened in the native UI and ran as the sole observed PID `171848`, with the path and SHA-256 above. The testing Risk Disclosure was acknowledged, Sage mainnet `TEST 7` fingerprint `736588221` selected, the existing Spacescan key retained, and `Monkeyzoo Token (MZ_XCH)` selected. Read-only status identified CAT wallet ID `2` and exact asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Sage independently returned the current key as TEST 7/mainnet/`736588221`, zero pending transactions, and 4,095 completed-history offers classified as 3,326 cancelled, 231 expired, and 538 completed. No fillable status was present. The app reported XCH `138.470301476875`, MZ `780212.284`, zero open offers, synced wallet, stopped bot, inactive Bootstrap, and safety `ALLOWED` with an owned renewing lease and zero blockers. The original database's prior campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` remained stopped with zero authoritative fee spend.
- Native Dashboard, Offers, P&L, Market, Settings Setup and Live, Logs, Data Reset, Help, and About were traversed without settings save, data reset, campaign, bot, Coin Prep, or wallet effect. Offers showed zero buys and sells, zero pending cancels. Follow-mode market confidence was RED with no tradable range; no live ladder was attempted.
- The new exact-PID/hash stopped-profile monitor is `E:\catalyst-stability-monitor-b7efd6e-clean\monitor.ps1` with `trace-60s-clean.jsonl`. It began `2026-10-06T23:57:27Z`; its initial sample had safety allowed, owned lease, synced Sage, stopped bot, and zero offers. A complete 24-hour gate and end-state review cannot occur before `2026-10-07T23:57:27Z`.

## Open gates

Active-offer lifecycle and recovery, secondary original-profile exact-source acceptance, both final-candidate 24-hour windows, final review, and release authorization remain open. No new TEST 7 campaign or fee approval exists; the older `c6651480` approval belongs to another expired campaign. Keep PR #220 draft; no merge, tag, release, or public-readiness claim.
