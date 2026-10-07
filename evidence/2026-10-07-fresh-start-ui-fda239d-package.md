# Exact fda239d fresh-start UI failure gate and Windows package

All times are UTC. This records acceptance evidence for draft PR #220, not release authorization.

## Source and regression

- Exact runtime/source: `fda239da5ba609e66bdf77482ef14f541ff00757`. It adds a fail-closed UI result for failed POST `/api/session/fresh-start`: the recovery dialog remains open, the pair reset is not run, and no success toast appears. The post-load Skip path also keeps the dialog open until the request succeeds.
- The parametrized initial/post-load failure regression failed before the fix: the modal closed, reset ran, and success was shown. It passed after the fix. A positive success case passed. The focused browser suite passed 5 tests; full Chromium passed 236 tests. Ruff check/format and diff check passed.
- Backend production files are byte-identical to exact `293d823c486c792f90c188c4e840ce2a8ddecddf`, whose full serial Windows backend passed 7,315 tests, with 234 skipped and 433 subtests passed. All 11 exact `fda239d` PR checks completed successfully, including unit tests, lint, CodeQL, Semgrep, Gitleaks, and security scan.

## Clean detached package

- Detached build checkout: `E:\catalyst-fresh-fail-fda239d-build` at exact source. `python build.py` succeeded. The build changed only `_version.py` working-tree line endings, without semantic content.
- EXE `E:\catalyst-fresh-fail-fda239d-build\dist\Catalyst\Catalyst.exe`: SHA-256 `09ED1F164A5AF7630616BC7BCABC6DD55E4E05486D3816B07B7F7059EE53C5F6`.
- Bundled `bot_gui.html`: SHA-256 `8F42CD6AF672803BBB3404656785A0EE865B28B88D5C66B0337EA63BA70DD37C`, byte-identical to source.
- ZIP `CATalyst-fda239d-primary-acceptance.zip`: SHA-256 `275D40A74C1C6B73C5E02CDDCA6A990B7DBE0070EBD42D0A9C0BAFED0EF63ABF`; 192 entries passed CRC, and the extracted EXE matched the clean build and passed packaged API smoke. No `.env`, database/WAL/SHM, `.fresh_start_chosen`, or crash log was included.
- Unsigned installer `Catalyst-Setup-fda239d-1.4.0.exe`: SHA-256 `187DE4E3D66451101528E1939BA27E365EB82EB6B736DB53FD644B094A7C0F17`. The production installer was compiled but not installed.
- Packaged API, synthetic Sage mTLS RPC, interrupted-publication recovery, native clean/duplicate/persisted/safety launches, and isolated packaged fresh-start marker create/clear checks passed. An isolated QA installer with AppId `{7F788613-6EEC-4A07-92B2-03C48D0F7288}` installed to `E:\catalyst-fda239d-qa-install`, matched the EXE hash, passed installed API smoke, and uninstalled with the QA executable and registration absent. It did not use the product's normal registration.
- Defender found no threats in the bundle, ZIP, or installer. The ZIP and installer were pinned at artifact commit `2705213966382782f3d1a1bd2bc6960280257ab3` with `SHA256SUMS-fda239d.txt`; independent HTTP downloads of both files matched their expected hashes.

## Original TEST 7 rollover

- Before rollover, the sole `293d823` app was PID `142960`, port 5000 owner, with on-disk EXE hash `A2E3FB2A9FF7434F1CA56DC9197D6DAD9B82943360B7138B37C541E089D2CF0A`. Safety was allowed with an owned lease; bot stopped, Sage synced, no open offers. Direct Sage and DB preflight found mainnet TEST 7 fingerprint `736588221`, CAT wallet ID `2`, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, XCH `138470301476875` mojos, MZ `780212284` atomic units, no pending transactions, complete 4,095-offer Sage history with zero open MZ buys/sells, zero DB open offers, no active campaign, and prior stopped campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` with zero authoritative fee spend.
- The old app was shut down via its visible UI with **Cancel all currently active wallet offers before shutdown** unchecked. PID and port listener exited normally. Its prior stopped-profile trace remains historical.
- Exact `fda239d` launched against the original profile as sole PID `31216` and port 5000 owner; the running path and EXE hash matched the clean build. Testing Risk Disclosure was acknowledged in the visible UI, Sage mainnet TEST 7 fingerprint `736588221` selected, Splash skipped while stopped, existing Spacescan key retained, and MZ/XCH selected. No bot start, campaign start, settings save, or wallet offer action occurred.
- Post-launch direct Sage and DB reads confirmed the same identity, balances, zero pending and open offers, stopped prior campaign with zero authoritative fee spend, and no active campaign. API safety was allowed with an owned renewing lease; bot stopped, Sage synced, port owner `31216`, and open offer count zero.
- Exact-PID/hash stopped-profile monitor `E:\catalyst-stability-monitor-fda239d-clean\monitor.ps1` began at `2026-10-07T01:51:06.3103475Z`. Its first sample passed with safety allowed, owned lease, Sage synced, bot stopped and zero open offers. A 24-hour gate cannot pass before `2026-10-08T01:51:06Z` plus complete trace and end-state review.
- In a fresh Chrome tab against that sole process, the read-only Dashboard, Offers, P&L, Market Intelligence, Settings, Logs, Data Reset, Help, and About views opened without a settings save or wallet effect. MZ/XCH was selected in that tab, the bot and Start button remained stopped/disabled, and market confidence was RED with no tradable range. A post-traversal direct Sage and DB recheck found unchanged balances, zero pending transactions, zero Sage/DB open MZ offers, no active campaign, and zero authoritative fee spend on the stopped prior campaign. Safety remained allowed with an owned lease. Four exact-PID/hash monitor samples had passed by `2026-10-07T01:54:09Z`, with no bad samples.

Active-offer lifecycle/recovery, secondary original-profile exact-source acceptance, both final-candidate 24-hour windows, final review, and release authorization remain open. A new campaign and fee scope have not been approved. Keep PR #220 draft; no merge, tag, release, or public-readiness claim.
