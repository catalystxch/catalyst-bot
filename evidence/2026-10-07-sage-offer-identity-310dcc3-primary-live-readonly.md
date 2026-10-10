# Exact `310dcc3` primary live read-only acceptance

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `310dcc3ddb3cb4562b35080498316f1e3b92a636`. This is an
intermediate acceptance record, not public-readiness approval.

## Original TEST 7 profile rollover

The preceding f677 application was stopped with no bot or open offers; its
process and port 5000 listener exited. The clean detached exact candidate
started as the sole `Catalyst.exe` process and port 5000 owner, PID `175392`,
from `E:\catalyst-sage-identity-310dcc3-build\dist\Catalyst\Catalyst.exe`.
The running path's SHA-256 was
`D4705DD2764A7D27C19DA8E1B10505CFDDCF9FF7529E199159675ADBF0B902D7`.

The native UI Risk Disclosure was acknowledged under the operator's standing
testing authorization. The native startup connected Sage, visibly selected
`TEST 7` fingerprint `736588221`, skipped the optional Splash node, chose
Spacescan Free Tier, and selected `Monkeyzoo Token (MZ_XCH)` in the pair
picker. No bot, campaign, offer, coin-prep, or fee action was taken.

After selection, the read-only app status showed mainnet CAT wallet ID `2`,
asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138.470301476875 XCH and 780212.284 MZ, synced Sage, stopped bot, zero
open offers, safety `ALLOWED`, and an owned renewing lease. A direct Sage
read-only mTLS snapshot at `2026-10-07T06:23:08Z` independently found
138470301476875 selectable XCH mojos, 780212284 selectable MZ atomic units,
zero pending transactions, and 4095 terminal offers (3326 cancelled,
231 expired, 538 completed), with zero nonterminal offers. Snapshot:
`E:\catalyst-sage-identity-310dcc3-live\sage-readonly-after-selection.json`.

The prior campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remains `stopped`, bound to mainnet fingerprint `736588221`, wallet ID `2`,
and the exact MZ asset. Its authoritative fee spend is zero. There is no
new campaign approval; the old `c665...` approval is invalid for a new
campaign.

## Native read-only UI

Dashboard showed TEST 7/MZ, stopped bot and no active Bootstrap campaign.
Offers showed zero buy and sell offers. P&L displayed the existing three
confirmed historical buy fills, with no pending verification. Market Intel
showed RED confidence and no tradable independent depth; no trading was
started. Settings displayed fingerprint `736588221` and the selected MZ/XCH
pair. Logs, Data Reset, Help and About opened. No setting was saved and no
reset control was used. The app was left on Dashboard.

## Exact-candidate stability trace

`E:\catalyst-stability-monitor-310dcc3-clean\monitor.ps1` began its
read-only, exact-PID/hash stopped-profile trace at
`2026-10-07T06:21:06.760559Z` in `trace-60s-clean.jsonl`. The first three
samples were clean: process alive, safety allowed, owned renewing lease,
synced Sage, bot stopped, and zero open offers. This is an incomplete window;
the 24-hour gate cannot pass before `2026-10-08T06:21:06Z` and a full trace
and end-state audit.

Live active-offer lifecycle and recovery, secondary original-profile live
acceptance, both final-candidate 24-hour windows, and final review remain
open. Keep PR #220 draft; no merge, tag, release, or public-use claim.
