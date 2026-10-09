# Primary exact `6e579f4` stopped-profile window — in progress

The exact runtime/source is `6e579f4ec62857e6b7051ee94ec733def74a02bf`.
This is an observation of the original TEST 7 profile, not a completed
24-hour acceptance result or an active-offer lifecycle test.

At the action-time read-only preflight, the previous sole app was PID 150240
from `E:\catalyst-pr220-combined-build\dist\Catalyst\Catalyst.exe` with SHA-256
`D8FC061FD883ABB268F03A93CDB4B0B4631906043E95588CAAB0F6902A5A0238`.
It owned port 5000, the bot was stopped, safety allowed with zero blockers,
and its lease was owned. Sage reported mainnet TEST 7 fingerprint 736588221,
CAT wallet ID 2, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138470301476875 XCH mojos and 780212284 MZ atomic units confirmed and
spendable, zero pending transactions and zero nonterminal offers in the
complete 4095-offer history. The DB had zero open offers, active campaigns,
and unresolved operations. The prior campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
was stopped with zero authoritative fee spend and no approval.

The historical `515b41c` monitor was still running but its trace had already
failed: samples 282, 387, and 388 each recorded `PROCESS_COUNT_NOT_ONE`.
Its audit reported 431 samples, six problems, and `trace_status: invalid`.
The monitor was retired and the older stopped app closed through its main
window. Port 5000 and the Catalyst process were then absent.

The clean detached EXE
`E:\catalyst-splash-6e-build\dist\Catalyst\Catalyst.exe` was checked against
SHA-256 `0D6EACE79EDAB03778F84C098D5C0C486E421570A0E886BE1204F5BDDAB07E63`
and launched on the original default profile. The sole process is PID 136324;
it owns `127.0.0.1:5000`. The live API reported a stopped Sage bot, safety
allowed, an owned lease, and zero blockers. No wallet mutation was requested.

The exact-PID/path/hash monitor is PID 209836, running
`E:\catalyst-stability-monitor-6e579f4-prepared\monitor.py`. Its trace is
`E:\catalyst-stability-monitor-6e579f4-prepared\trace-60s.jsonl`. The start
record is **2026-10-09T11:12:28.672095Z**; sample 1 at
**2026-10-09T11:12:28.676091Z** had no alerts. It recorded one process, the
expected port owner/hash, safety allowed with zero blockers and owned lease,
stopped bot, zero DB offers/campaigns/operations, synced Sage identity and
unchanged balances, zero pending transactions, and zero nonterminal offers.
The audit reports `in_progress` with zero problems. Veeam/VSS processes were
present in that sample and are part of the observed environment.

The earliest 24-hour elapsed point is **2026-10-10T11:12:28Z**. The monitor
plans 25 hours, and only its completed trace plus fresh end-state process,
Sage, DB, campaign, ledger, and UI review can qualify this window. A clean
stopped-profile window will not by itself prove Splash peer receipt, active
offer lifecycle/recovery, secondary original-profile acceptance, or public
beta readiness. PR #220 remains draft.
