# Escape Doctor Report duration in the HTML modal

Draft PR #220 exact source `15047c86f9b705cbf3a8c01957fa3e45c629771e`.

The Doctor Report modal placed `report.duration_ms` from an API response into
`innerHTML` without escaping it. A Chromium regression supplied markup in that
field and reproduced an injected element before the fix. The modal now passes
the value through `escapeHtml()`. The regression and complete opt-in Chromium
suite passed **228 tests in 161.99 seconds**. Ruff check and format passed for
the modified test. The complete exact-source serial Windows backend passed
**7,277 tests, 229 skipped, and 433 subtests in 1259.06 seconds**.

The clean detached checkout at
`E:\catalyst-doctor-xss-15047c8-package` built the Windows EXE with
PyInstaller 6.21.0 and release version 1.4.0. The bundled HTML hash equals the
source HTML hash. The 192-file ZIP passed CRC and contains one EXE with the
same hash as the clean build. Inno Setup 6.7.3 compiled the unsigned installer.
The packaged synthetic Sage mTLS worker passed with mock fingerprint 123456789.
Defender custom scans of the bundle, ZIP and installer added zero detections
(six historical detections before and after).

A unique-AppId QA installer (`{EDD6C8DA-8E45-4E5C-A25C-E17C12AB35B5}`)
installed to an isolated E: directory, registered version 1.4.0, and installed
an EXE identical to the clean build. Silent uninstall exited 0 and removed the
QA EXE and registration. The original TEST 7 app remained running. An earlier
automatic approval review rejected launching a second isolated packaged EXE
before execution; that specific packaged API/recovery route was not retried
through another tool.

A second unique-AppId QA sequence (`{D3C51EAB-8DDA-44CA-9FED-F634DF4A931C}`)
installed the prior `2028c84` bundle, verified its EXE hash, then performed a
same-version upgrade to this exact bundle and verified the new EXE hash.
Both installer runs exited 0. Final silent uninstall exited 0 and removed the
QA EXE and registration. The original TEST 7 process and port owner remained
unchanged.

The ZIP, unsigned installer and checksum manifest are pinned at artifact commit
`acdf255b6ed1d79694a4b8f2d0071ca136ad8f3d` on
`codex/coin-prep-fee-approval-artifacts`. Independent HTTP
downloads of both pinned binaries matched these local SHA-256 hashes:

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/acdf255b6ed1d79694a4b8f2d0071ca136ad8f3d/acceptance-artifacts/CATalyst-15047c8-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/acdf255b6ed1d79694a4b8f2d0071ca136ad8f3d/acceptance-artifacts/Catalyst-Setup-15047c8-1.4.0.exe)

| Artifact | SHA-256 |
| --- | --- |
| Clean `Catalyst.exe` | `D2C9AD43F4F7D47E9FCFED4A1C13DE7D22BE92CE45CF086E366530A4EFC6D6C8` |
| Bundled `bot_gui.html` | `C6D2A4E7653606CA367410D97118D3985D01A4B1B9832D98763D69C5048071F3` |
| `CATalyst-15047c8-primary-acceptance.zip` | `BDFEDDA6352B91C4217D2274D988792C48213CE924B8DE13C7069CCE46FD0A7A` |
| Unsigned `Catalyst-Setup-15047c8-1.4.0.exe` | `3E1F07702AB3AD365BEC5948FE8674E292C88CC045A8F877809FE4CAE4E4E283` |

All eleven exact-source PR checks passed. At packaging, PR #220 remains draft. Exact-source original-profile rollover,
active-offer lifecycle and recovery, secondary original-profile acceptance,
both final-candidate 24-hour windows, and final review remain open. No new
campaign or wallet effect was started.

## Original TEST 7 read-only rollover

The prior stopped `2028c84` app was closed through its native shutdown flow
with offer cancellation unchecked. The exact clean `15047c8` EXE then launched
as the sole CATalyst process, PID `100576`, from the E: build path above. Its
on-disk SHA-256 matched `D2C9AD43F4F7D47E9FCFED4A1C13DE7D22BE92CE45CF086E366530A4EFC6D6C8`,
and the sole `127.0.0.1:5000` listener belonged to that PID. The native UI
acknowledged the testing Risk Disclosure under existing operator authorization,
connected Sage mainnet fingerprint `736588221`, and selected Monkeyzoo Token
`MZ_XCH`. The bot remained stopped.

The live API reported CAT wallet ID `2`, exact asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138.470301476875 XCH and 780212.284 MZ, a healthy synced Sage wallet, zero
open offers, inactive Bootstrap, and safety allowed with zero blockers and an
owned lease. The native Logs > Run Doctor flow displayed its Doctor Report
modal successfully: nine passed, one warning (Splash unreachable), and the
duration rendered as `4579.5ms`. The preceding independent Sage read-only
preflight found zero pending and fillable offers across the complete 4,095
record offer history, and the prior campaign stopped with zero authoritative
fee spend. A second independent read-only Sage check after this exact build's
startup confirmed TEST 7 mainnet fingerprint `736588221`, zero pending
transactions, and zero fillable offers after classifying the complete 4,095
record offer table. XCH selectable and owned balance both remained
`138470301476875` mojos. Direct exact-asset Sage `get_coins` reads found 60
selectable and 60 owned MZ coins, each set totaling `780212284` atomic units.
Read-only database functions confirmed the prior campaign remains `stopped`,
its authoritative fee spend is zero mojos, and there is no active MZ/mainnet
campaign for this fingerprint. No bot, campaign, Coin Prep, offer, or wallet
action was started.

Fresh exact-PID/path/hash read-only monitors began on
`2026-10-06T13:49:13Z` in
`E:\catalyst-stability-monitor-15047c8` (60-second safety/health/offer trace)
and at `2026-10-06T13:49:10Z` (30-second port-owner trace). Their first samples
showed the same process/hash, one owned listener, allowed safety, an owned
renewing lease, synced Sage, stopped bot, and zero open offers. The 24-hour
stopped-profile gate cannot be counted before `2026-10-07T13:49:13Z` plus
complete trace and end-state review. The prior candidate's traces are
historical. Active-offer lifecycle/recovery, secondary original-profile
acceptance, the active-profile 24-hour window, and final review remain open.

The same native exact-build session traversed Dashboard, Offers, P&L, Market
Intel, Settings Setup and Live, Logs, Data Reset, Help, and About. The Offers
view showed zero active buys, sells, and pending cancels. Market Intel showed
RED confidence and unavailable Splash without presenting an authorized
tradable range. The Live settings controls remained disabled while the bot
was stopped; the Data Reset view described its confirmations, and no reset
action was selected. Help and About modals opened and closed. After returning
to Dashboard, the API still reported the same fingerprint, wallet ID, exact
asset, XCH/MZ balances, zero open offers, stopped bot, inactive Bootstrap,
synced Sage, and allowed safety with an owned lease. No UI error or wallet
effect was observed in this traversal. Active-state UI acceptance remains open.
