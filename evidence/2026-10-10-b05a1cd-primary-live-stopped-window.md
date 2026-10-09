# Exact `b05a1cd` primary TEST 7 stopped-profile window

## Planned source rollover

All 11 CI checks passed on draft PR #220 docs-only head
`0cf46a3d347a467c3d3f6479f4b2e44f53e4723e`. Exact production runtime
is `b05a1cd1d8210dd5e247094d38a6be4a54257805`; test-only child
`8fb45649e7d6b047ecbf27f3b5e818318c75b079` passed both full Windows
backend suites and the clean package acceptance.

At **2026-10-09T23:46:36Z**, fresh read-only preflight found the prior
`aba6667` app as sole PID `181868`, expected path and SHA-256
`F57F93F17B3E6981DDE1178A7C42798A019FC1C5CF24C2888F98CBDDE44E8E25`,
sole port-5000 owner, stopped bot, allowed fresh safety, owned lease, zero
blockers, zero DB open offers/active campaigns/unresolved operations. Sage
mainnet TEST 7 fingerprint `736588221`, CAT wallet ID `2` for the exact MZ
asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, XCH `138470301476875` mojos and MZ `780212284` atomic units,
zero pending transactions and zero nonterminal offers across complete 4,095
offer history matched the prior checkpoint. The old campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remained stopped, expired, with zero authoritative fee spend and no Coin Prep
approval.

VeeamAgent and VSSVC were active during the rollover. The prior app had no
safety alerts through sample 179, including the overlap. It received its
normal native window-close message while stopped, exited within eight seconds,
and released port 5000. No forced kill, cancellation, offer operation or
wallet mutation was requested. Its monitor recorded the expected missing
process/API at sample 180 and wrote its terminal record at
**2026-10-09T23:47:39.878342Z**. This preceding-source window lasted about
three hours and earns no 24-hour credit.

## Exact process and initial bound sample

The clean detached EXE
`C:\catalyst\.superpowers\manual-coin-start-b05-build\dist\Catalyst\Catalyst.exe`
started on the original default profile as sole PID `145164`. Its on-disk and
running-path SHA-256 was
`EF8F0E3AFB5966AF9A372CACD7CCED979D368CD4BB8DDD11D54F508F1CAA3C28`;
PID `145164` alone owned port 5000. A read-only process/API/DB/Sage/safety
sample at **2026-10-09T23:47:53Z** passed with zero alerts, unchanged identity
and balances, zero pending/open offers, stopped bot, owned lease and allowed
safety while Veeam snapshot processes were present.

The exact-PID/path/hash-bound 25-hour monitor is
`E:\catalyst-stability-monitor-b05a1cd-primary\monitor.py`, SHA-256
`CA02FEC11941E26EA162930D065CFD2B9CB167755EED33C5F59574DDC5BA9CB2`,
started as PID `207304`. Its trace is
`E:\catalyst-stability-monitor-b05a1cd-primary\trace-60s.jsonl`. The start
and first sample at **2026-10-09T23:48:14.082050Z** bound the production
source, PID, create time, EXE hash, original profile, port owner, safety,
database and Sage with zero alerts. The 24-hour gate cannot be credited before
**2026-10-10T23:48:14.082050Z**, and also requires an uninterrupted full trace
and fresh end-state audit. The monitor plans 25 hours.

Secondary original-profile acceptance, active-offer lifecycle/recovery,
genuine Splash peer receipt, complete native UI and final review remain open.
The specific new TEST 7 campaign and fee scope have not been approved, so no
wallet effect was attempted. PR #220 stays draft and no beta was deployed.
