# Exact `aba6667` primary TEST 7 stopped-profile window

## Planned rollover, 2026-10-09

All 11 checks on draft PR #220 docs-only head
`e6c292d74aed60ea35bd0bf11ba3e54f25330736` completed successfully,
including CI unit tests. The exact runtime/source is
`aba66676628e364ca25cc6529999fcd1c34a93b8`.

The prior `0534103` process was the sole original-profile PID `185680` and
port-5000 owner. Fresh preflight at **20:45:59Z** confirmed its path/hash,
Sage mainnet TEST 7 fingerprint `736588221`, CAT wallet ID `2`, exact MZ
asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, XCH `138470301476875` mojos and MZ `780212284` atomic units
confirmed and spendable, zero pending transactions and zero nonterminal offers
across a complete 4,095-offer history. CATalyst had a stopped bot, allowed
fresh safety, owned lease, zero active campaigns, zero DB open offers, zero
unresolved operations, and zero blocker counts. The prior campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
was stopped with zero authoritative fee spend and no fee approval.

The old app received its normal native window close message while stopped,
exited within six seconds, and freed port 5000. No forced kill, cancellation,
offer operation or wallet mutation was requested. Its monitor recorded an
expected process/health/safety failure at sample 97 after the planned exit,
then wrote a terminal record at **20:47:06.163425Z**. That earlier-source
window lasted about 96 minutes and earns no 24-hour credit.

## New exact process and first read-only sample

The clean detached EXE
`C:\catalyst\.superpowers\coin-prep-stop-aba-build\dist\Catalyst\Catalyst.exe`
started on the original default profile as sole PID `181868`. Its on-disk and
running-path SHA-256 was
`F57F93F17B3E6981DDE1178A7C42798A019FC1C5CF24C2888F98CBDDE44E8E25`;
PID `181868` alone owned port 5000. Public health returned HTTP 200, v1.4.0,
Sage wallet and `bot_running=false`. Public safety was allowed/fresh with an
active owned lease and zero blockers.

An exact-PID/hash read-only sample at **20:48:25.986594Z** confirmed the same
Sage identity and balances, zero pending/nonterminal offers, zero DB open
offers, zero active campaigns and unresolved operations, stopped bot, owned
lease and zero alerts. This establishes startup and stopped-profile state only.

The 25-hour read-only monitor is
`E:\catalyst-stability-monitor-aba6667-primary\monitor.py` (SHA-256
`8DAF5CDBFFF69CACA3F9FD390C23EE06E492FB87225990FC624C67FAC6FFD614`),
PID `85464`, bound to PID/path/hash/port 5000, original profile, safety,
database and Sage. Trace:
`E:\catalyst-stability-monitor-aba6667-primary\trace-60s.jsonl`. It began
at **2026-10-09T20:48:34.592596Z** and its first sample had zero alerts.
The 24-hour gate cannot be credited before **2026-10-10T20:48:34.592596Z**
and also requires a complete continuous trace and fresh end-state audit.

The secondary original-profile and synthetic exact-`aba6667` windows have
been delegated and remain open. Active-offer lifecycle/recovery, genuine
Splash peer receipt, complete native UI and final review remain open. The
specific new TEST 7 campaign and fee scope remain unapproved, so no wallet
effect was attempted. PR #220 and website PR #89 remain draft; no beta was
deployed.
