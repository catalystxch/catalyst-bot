# Exact e55d912 Settings fresh-start failure gate and Windows acceptance

All times are UTC. This is evidence for draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), not release authorization.

## Source, regression and CI

- Exact runtime/source: `e55d9128fc8d227d7a7730d9e9308f4245a48460` on `codex/coin-prep-fee-approval`. The PR remains draft against `main`.
- The Settings “Start Fresh” route cleared the resumed offer-book authority, reset the pair and opened editable setup even when POST `/api/session/fresh-start` failed. Both the direct Settings reset and the confirmation handler failed red under a rejected durable write. The fix returns failure before changing local resume state and propagates it through the caller. Negative and positive tests for both paths pass: **4 focused browser tests**. The full Chromium suite passed **240 tests**; Ruff check/format and diff check passed.
- All **11** exact-source PR checks passed, including unit tests, lint, CodeQL, Semgrep, Gitleaks and security scan. Backend production files are byte-identical to `293d823c486c792f90c188c4e840ce2a8ddecddf`, whose full serial Windows backend passed **7,315 tests**, with **234 skipped** and **433 subtests passed**.

## Clean detached Windows package

- Detached build checkout: `E:\catalyst-settings-fresh-e55d912-build` at the exact source commit. `python build.py` passed. The build changed only `_version.py` working-tree line endings without semantic content.
- EXE `E:\catalyst-settings-fresh-e55d912-build\dist\Catalyst\Catalyst.exe`: SHA-256 `27F937C8812F68B38B16C028EA0752FEB54F914C5EF67B129D07BCD2AEE7E8C5`.
- Bundled `bot_gui.html`: SHA-256 `D34BC69952DD9B30DCDE12CE60989438A3C2A721A738E6180EA5C0BCA439BD77`, byte-identical to source.
- ZIP `CATalyst-e55d912-primary-acceptance.zip`: SHA-256 `2CBEE8FB3A210E7693F0FF48B06AD3F7B5AF8733B3C065EE0C2C6F8C6B09CD2D`. All 192 entries passed CRC; the extracted EXE matched the clean build and passed packaged API smoke. No `.env`, database/WAL/SHM, `.fresh_start_chosen` or crash log was bundled.
- Unsigned installer `Catalyst-Setup-e55d912-1.4.0.exe`: SHA-256 `2BA6B358D7E85C32C4F395D284B23B294C16622BCC17B0C93030771CB1D0790A`. The production installer was compiled but not installed.
- Packaged API, synthetic Sage mTLS worker, interrupted-publication recovery, native clean/duplicate/persisted/safety launches, extracted ZIP API, and isolated packaged fresh-start marker create/clear checks passed.
- Separate-name QA installer AppId `{5C887D2E-4700-4D1E-9E71-800FE7CBDEF2}` installed to `E:\catalyst-e55d912-qa-install`, matched the EXE hash, passed installed API smoke, and uninstalled with executable and QA registration absent. It did not use the product's normal registration.
- Defender found no threats in the bundle, ZIP or installer. ZIP, unsigned installer and `SHA256SUMS-e55d912.txt` were pinned at artifact commit `cfa1306f4edf56b477a1a24c0c8b6afea097e1af`. Independent HTTP downloads of the ZIP and installer matched their hashes.

## Original TEST 7 rollover and stopped-profile monitoring

- Before rollover, the sole `fda239d` app was PID `31216`, port 5000 owner, with on-disk EXE hash `09ED1F164A5AF7630616BC7BCABC6DD55E4E05486D3816B07B7F7059EE53C5F6`. Bot stopped; safety allowed with an owned lease; Sage synced; zero open offers. Direct Sage/DB preflight found mainnet TEST 7 fingerprint `736588221`, CAT wallet ID `2`, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, XCH `138470301476875` mojos, MZ `780212284` atomic units, zero pending transactions, complete 4,095-offer Sage history with zero open MZ buys/sells, zero DB open offers, no active campaign, and stopped prior campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` with zero authoritative fee spend.
- The prior app shut down through its visible UI with wallet-offer cancellation unchecked. Its PID and port listener exited normally. Its stopped-profile trace ended after detecting the old PID's exit and remains historical.
- Exact `e55d912` launched against the original profile as sole PID `173568` and port 5000 owner. The running path and on-disk hash matched the clean EXE. Testing Risk Disclosure was acknowledged in the UI, Sage TEST 7 fingerprint `736588221` selected, Splash skipped while stopped, existing Spacescan key retained and MZ/XCH selected. No bot/campaign start, settings save or wallet-offer action occurred.
- Post-launch Sage and DB reads confirmed the same identity, balances, zero pending/open offers, no active campaign and stopped prior campaign with zero authoritative fee spend. API safety was allowed with an owned renewing lease; bot stopped, Sage synced, open offer count zero. Read-only Dashboard, Offers, P&L, Market Intelligence, Settings, Logs, Data Reset, Help and About traversal passed without wallet effect; the post-traversal Sage/DB recheck was unchanged.
- Exact-PID/hash stopped-profile monitor `E:\catalyst-stability-monitor-e55d912-clean\monitor.ps1` began `2026-10-07T02:12:12.9798996Z`. Its first sample passed: safety allowed, lease owned, Sage synced, bot stopped, zero open offers. The 24-hour gate cannot pass before `2026-10-08T02:12:12Z` plus complete trace and end-state review.

Active-offer lifecycle/recovery, secondary original-profile exact-source acceptance, both final-candidate 24-hour windows, final review and release authorization remain open. No new TEST 7 campaign or fee scope has been approved. Keep PR #220 draft; no merge, tag, release or public-readiness claim.
