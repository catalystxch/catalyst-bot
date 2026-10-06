# Atomic stopped-wallet offer snapshots

Draft PR #220 exact source 676028287b4fba1948de4542567abd2ab0a3a020.

The stopped Dashboard read the last wallet offer cache and its freshness metadata without the lock used by the wallet-sync writer. A concurrent read could combine new buys with old sells or metadata and present that mixed book as fresh. A regression paused a writer after its buy update while it held the sync lock; the pre-fix reader completed against the partial book. The fixed reader waits for the writer and copies buys, sells, closed offers, and metadata under the same reentrant lock. The regression then passed, along with the 67-test related slice.

The complete serial local Windows backend passed 7,278 tests, with 229 skipped and 433 subtests. Ruff check and format passed on the changed files. The clean detached 1.4.0 build used PyInstaller 6.21.0; bundled bot_gui.html equals the unchanged source HTML. The 192-file ZIP passed CRC and its embedded EXE hash matches the clean build. A unique-AppId current-user QA installer clean install produced an identical EXE, and silent uninstall removed its EXE and registration. Defender scans of the bundle and installer added zero detections. Independent HTTP downloads of the pinned ZIP and installer matched local SHA-256 hashes.

| Artifact | SHA-256 |
| --- | --- |
| Clean Catalyst.exe | B30E7B656309098E1601A9D21AD93ACF0DD9377D6A87DE99DF9F7A6EF3A75D5E |
| Bundled bot_gui.html | C6D2A4E7653606CA367410D97118D3985D01A4B1B9832D98763D69C5048071F3 |
| CATalyst-6760282-primary-acceptance.zip | 94B8EB4B7F53E3D862037CA7F55DA76AE07DE73C622982D3904A4DA448FC7A76 |
| Catalyst-Setup-6760282-1.4.0.exe, unsigned | 828BA0FABF60181EEDFD9EE45E0E3C2AAF5537F7E36C1E95B1D867C111997FFE |

The binaries and checksum manifest are pinned at artifact commit 1288e23408dfc48fa596a97aca878f954830296e:

- ZIP: https://raw.githubusercontent.com/catalystxch/catalyst-bot/1288e23408dfc48fa596a97aca878f954830296e/acceptance-artifacts/CATalyst-6760282-primary-acceptance.zip
- Installer: https://raw.githubusercontent.com/catalystxch/catalyst-bot/1288e23408dfc48fa596a97aca878f954830296e/acceptance-artifacts/Catalyst-Setup-6760282-1.4.0.exe

At this package checkpoint the previous 15047c8 EXE still owns the original TEST 7 profile and port 5000. The new EXE has not run against that profile. No new campaign, fee approval, or wallet action occurred. Exact-source CI, original-profile rollover, active-offer lifecycle/recovery, secondary original-profile acceptance, both final-candidate 24-hour windows, and final review remain open. PR #220 stays draft.

## Original TEST 7 read-only rollover

The prior stopped 15047c8 app closed through its native shutdown flow with offer cancellation unchecked. The exact 6760282 clean EXE then became the sole CATalyst process and port 5000 owner, PID 109092. Its on-disk SHA-256 matched the clean-build hash above. The native startup acknowledged the testing Risk Disclosure under existing operator authorization, selected Sage mainnet TEST 7 fingerprint 736588221, and selected Monkeyzoo Token MZ_XCH. Splash was skipped because it was not running; the existing Spacescan key configuration was retained without entering or saving a key. The bot remained stopped.

Read-only live API showed CAT wallet ID 2, exact asset b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105, 138.470301476875 XCH and 780212.284 MZ spendable and total, zero buy/sell offers, wallet sync state synced, and safety allowed with an owned lease and zero blockers. No campaign, Coin Prep, offer, settings save, or wallet action was started.

Fresh exact-PID/path/hash monitors began at 2026-10-06T15:00:43Z for 60-second safety/health/offer samples and 15:00:40Z for 30-second sole port ownership. Both first samples passed. The stopped-profile 24-hour gate requires the complete traces and end-state review no earlier than 2026-10-07T15:00:43Z. Prior candidate traces are historical. Active-offer lifecycle/recovery, secondary original-profile acceptance, the active-profile 24-hour window, and final review remain open; PR #220 stays draft.
