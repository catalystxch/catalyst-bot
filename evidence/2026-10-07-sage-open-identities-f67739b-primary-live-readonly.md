# Exact f67739b original TEST 7 read-only rollover

Evidence for draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220). Timestamps are UTC. This is interim read-only acceptance, not release authorization.

## Exact process and rollover

- Runtime/source: `f67739b63aae05c13e6d8c6c9f4d77aa0ef634fc`. Clean Windows EXE: `E:\catalyst-sage-open-id-f67739b-build\dist\Catalyst\Catalyst.exe`, SHA-256 `A0C0BAA7F04792328E20AA87E99AC5034994C0F93E094789420DDD6BC59B635D`.
- The predecessor `3ea62b3` remained stopped with zero buy/sell offers, inactive Bootstrap, safety ALLOWED and sole port-5000 ownership. Its PID `131372` accepted native `CloseMainWindow()`, exited normally, and released port 5000. Its stability traces are historical for the new candidate.
- The exact f677 EXE launched from the path above as PID `164896` and became the sole port-5000 owner. Running path and SHA-256 matched the clean build. `/api/health` returned OK/version 1.4.0 with bot stopped.
- In the visible native UI, the operator-authorized testing Risk Disclosure was acknowledged, Sage TEST 7 fingerprint `736588221` was selected, optional Splash was skipped, Spacescan free mode was selected, and Monkeyzoo Token `MZ_XCH` was selected. No campaign, Coin Prep, offer, setting save, or fee approval was started.

## Wallet and durable safety checks

- Read-only app state after wallet and pair selection: Sage mainnet TEST 7 ready/synced; CAT wallet ID `2`; exact asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`; XCH `138.470301476875`, MZ `780212.284`; zero buy/sell offers; bot stopped; inactive Bootstrap; runtime safety ALLOWED with an owned renewing lease.
- Independent direct Sage mTLS snapshots at `05:29:35Z` and `05:33:21Z` each showed `138470301476875` selectable XCH mojos, `780212284` MZ atomic units at precision 3, zero pending transactions, and all `4095` Sage offers terminal (`3326` cancelled, `231` expired, `538` completed), with zero nonterminal offers. The snapshots are stored under `E:\catalyst-stability-monitor-f67739b-clean`.
- The prior stopped campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` had zero authoritative fee spend via the repository's read-only database helper. No new campaign or approval exists; the older `c665...` approval remains invalid for this candidate.
- Read-only native Dashboard, Offers, P&L, Market Intelligence, Settings, Logs, Data Reset, Help and About traversal passed. Data Reset controls, settings save, bot start, and wallet-effect controls were not used. The Dashboard showed Start locked pending settings review. Offers showed no active offers and three historical filled buy offers. Market Intelligence showed Dexie/Sage ready and offer-book confidence RED; its visible confidence snapshot had historical evidence time `2026-09-28T15:29:15` and no tradable range. This state was observed, not overridden.

## Stability trace

- Exact-PID/hash stopped-profile safety, health, open-offer and backup monitor began `2026-10-07T05:30:04Z` in `E:\catalyst-stability-monitor-f67739b-clean\trace-60s-clean.jsonl`. Initial four samples had safety allowed, owned lease, synced Sage, stopped bot, zero offers and no failure.
- Exact process creation/path/hash/sole-port-owner monitor began `2026-10-07T05:30:50Z` in `E:\catalyst-stability-monitor-f67739b-clean\trace-port-30s.jsonl`. The first attempt failed before writing a sample because its PowerShell host did not resolve `Get-FileHash`; the read-only script was changed to use .NET SHA-256 and restarted. Its initial five samples passed. The failed attempt is preserved in `port-error.log`.
- The final-candidate stopped-profile 24-hour gate cannot complete before `2026-10-08T05:30:50Z`, followed by complete-trace and end-state review. Live active-offer lifecycle/recovery, secondary original-profile acceptance, the active-profile 24-hour window, and final review remain open. Keep PR #220 draft; do not merge, tag, release or claim public readiness.
