# Exact 515b41c primary TEST 7 read-only start

This is a startup checkpoint, not a 24-hour pass or public-readiness claim.

The exact runtime and clean detached package source is
`515b41c200fb506594225be498b099b0dbe6c03d`. The executable is
`E:\catalyst-pr220-combined-build\dist\Catalyst\Catalyst.exe`, SHA-256
`D8FC061FD883ABB268F03A93CDB4B0B4631906043E95588CAAB0F6902A5A0238`.

At `2026-10-09T03:59:31Z`, a fresh read-only preflight of the older original
TEST 7 process found Sage mainnet fingerprint `736588221`, wallet name TEST 7,
CAT wallet ID 2 and MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Sage was synced and reachable. XCH was `138470301476875` mojos and MZ was
`780212284` atomic units, both fully spendable; pending transactions and
nonterminal offers were zero across the complete 4,095-offer history. The bot
was stopped; the database had zero active campaigns, open offers, unresolved
operations and mutation blockers. Safety was allowed with an owned lease.

The older `0bf0346` executable, SHA-256
`1CFCB4BAD65A16F4E8DCA48DA7799F595D4BE02A04847BD80D9E1A5CC00657D5`,
received a normal window-close message and exited by `03:59:44Z`; port 5000 was
released. No forced kill or wallet cancellation was used. Its historical
monitor ended after seeing the process exit. Its trace already contained two
process-count alerts from isolated package smokes and is not a clean 24-hour
acceptance run.

The exact `515b41c` executable started as sole PID `150240` and sole
`127.0.0.1:5000` owner by `04:00:07Z`. A fresh read-only sample at
`04:00:12Z` reconfirmed the same Sage identity, balances, complete terminal
offer history, zero pending/open offers, stopped bot, zero active campaigns and
unresolved operations, safety allowed and a renewing owned lease. The candidate
monitor at `E:\catalyst-stability-monitor-515b41c-prepared\trace-60s.jsonl`
started at `2026-10-09T04:00:27.293672Z` as PID `171796`; sample 1 was clean
with the same state. Before launch, the monitor's negative guard rejected the
older PID due to exact path/hash mismatch without creating a trace.

The monitor is configured for 25 hours. The 24-hour threshold is
`2026-10-10T04:00:27.293672Z`; credit requires the complete trace and a fresh
independent end-state audit after that time. There was no new campaign, fee
approval, Coin Prep, bot start, offer mutation, or wallet effect during this
rollover. Active-offer lifecycle/recovery, full native UI, secondary
original-profile acceptance, both final-candidate 24-hour windows, and final
review remain open. PR #220 remains draft.
