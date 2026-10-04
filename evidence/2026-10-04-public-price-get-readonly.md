# Public price GET stopped-state side effect

The exact `6191cf4` primary live UI pass showed price-strategy and dynamic-limit initialization logs while the bot was stopped. Source review found `GET /api/price` called `PriceEngine.get_price()` whenever the `bot` object existed. That method advances the trading reference and calls `record_price()`, writing `price_history`. The nearby stopped `/api/status` path explicitly avoids the same method to prevent UI polling from writing the database or advancing trading risk state.

Two new endpoint tests failed red on the prior source: both stopped and running GET requests called `PriceEngine.get_price()` and returned its synthetic value `9` rather than the selected pair's public quote `0.00008`. The route now uses the existing pair-bound, expiring Dexie setup-price cache. It retains the public response's `mid`, `mid_price`, `dexie_price`, strategy, retired TibetSwap fields and `success` shape, and does not call the PriceEngine method. This is a source correction; the currently running `6191cf4` EXE does not contain it.

Focused verification: 87 backend tests and four subtests passed across the new route tests, setup pricing, retired TibetSwap checks, and status endpoints. Ruff check/format and Git whitespace checks passed. A clean detached package, exact-source full tests/CI, primary live retest, independent secondary acceptance, both 24-hour windows and final review remain required. No campaign, fee approval, offer or wallet transaction was created while investigating this issue. PR #220 remains draft.

## Exact 9dc6519 package and primary retest

All 11 PR checks passed on exact source `9dc65197a95afb23a405e3c569a587cb6aa9a305`. The clean detached Windows build at `E:\catalyst-price-get-9dc6519-build` passed packaged API, synthetic Sage RPC, publication recovery, and native clean/duplicate/persisted/safety smokes. Its 192-file ZIP passed CRC; the independently downloaded ZIP extracted to an EXE with the same hash and passed packaged API smoke. A separate-name, unique-AppId current-user QA installer passed clean install, installed EXE hash comparison, installed API and synthetic Sage checks, and uninstall. The QA EXE and registry entry were absent afterward. Defender custom scans of the bundle, ZIP and installer produced zero matching detections. Both pinned HTTP downloads matched local SHA-256 hashes.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `1B5A5362D10DA11DB65100DF556ECB59A0B7112795DCA1BEBFCF2E5BE295CD5E` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-9dc6519-primary-acceptance.zip` | `8B8C3F83DED2D47106503EDD54D1181EC0A0BC188B76571F31EB254764132AB2` |
| Unsigned `Catalyst-Setup-9dc6519-1.4.0.exe` | `37EE99EA54D2C27BD174E0688BED5A50D8E43772E6B71BFD4B7637379818A4A1` |

The binaries and manifest are pinned at artifact commit `52e7d2a76f2d4e2bef9abbc1a515eb3e6048e878`. The full exact-source local Windows backend suite is running separately.

The older `6191cf4` app was shut down through its native UI with cancel-offers unchecked and zero open offers. The exact `9dc6519` EXE started on original TEST 7 as PID 143552 and became the sole port 5000 owner. The operator-authorized Risk Disclosure was acknowledged in the native UI, Sage fingerprint 736588221 was selected, optional Splash was skipped, the configured Spacescan key retained, and the exact MZ trading pair selected. Read-only checks found mainnet, CAT wallet ID 2, asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, 138.470301476875 XCH and 780212.284 MZ, zero pending Sage transactions, zero open offers, stopped bot, no active campaign, ALLOWED safety with all blocker counts zero, and the prior campaign still stopped with zero authoritative fee spend.

Five consecutive live `GET /api/price` calls returned the selected MZ midpoint `0.0000675156445`. The 20-minute persisted price-history window contained zero samples before and after; current-session status logs contained zero `price_strategy` or `dynamic_limits_init` events. This passes the exact-package primary read-only price-route retest. It does not verify live offer lifecycle, fee action, or either 24-hour stability window. No new campaign, approval, offer, or wallet transaction occurred. PR #220 remains draft.
