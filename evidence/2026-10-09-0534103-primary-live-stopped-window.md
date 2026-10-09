# Exact 0534103 primary TEST7 stopped-profile window — 2026-10-09

## Controlled rollover

The prior `60eed8c` app was the sole original-profile `Catalyst.exe` and port-5000 owner. Immediately before rollover, a fresh read-only check found Sage mainnet TEST7 fingerprint `736588221`, CAT wallet ID `2`, MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, synced wallet, XCH `138470301476875` mojos and MZ `780212284` atomic units confirmed and spendable, no pending transactions, and a complete 4,095-offer history with zero nonterminal offers. CATalyst reported a stopped bot, allowed safety with an owned lease, zero blockers, zero DB open offers, zero active campaigns, and zero unresolved operations. The prior campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` was stopped with zero authoritative fee spend.

The old app was closed through its normal window close handler while stopped; it exited and port 5000 became free. Its monitor then recorded a planned `NoSuchProcess` observation at sample 83 and wrote a terminal record at **2026-10-09T19:10:57.630931Z**. The prior window lasted about 82 minutes and earns no 24-hour credit. No cancellation or wallet mutation was requested during rollover.

## New exact candidate

The clean detached `05341035a778a5a4e9680e74ba10dea8c14dde1f` package was started against the original default TEST7 profile as sole PID `185680` (created **2026-10-09T19:10:15.470714Z**) from `C:\catalyst\.superpowers\pr220-stop-retry-0534103-build\dist\Catalyst\Catalyst.exe`. The on-disk and running-path EXE SHA-256 was `94A1A2C31F241EF00EC1DEA3D2DC5229EAF6639B4B1CBB8C108AD79FFEAA0217`; PID `185680` alone owned loopback port 5000. The first public health and safety reads found v1.4.0, Sage wallet, stopped bot, allowed/fresh safety, an active owned lease, and zero blockers.

A fresh exact-PID/hash read-only sample after startup found the same Sage identity and balances, zero pending and nonterminal Sage offers, zero DB open offers, zero active campaigns and unresolved operations, and no alerts. This establishes startup and stopped-profile state only; it does not exercise offer creation, fee approval, fill, cancellation, or recovery.

An authenticated same-origin live `/api/status` read on the exact running process returned HTTP 200 with `status=stopped`, `running=false`, and `stop_retry_available=false`. The per-run token was read from the process environment for this local request and was not printed or persisted.

## Monitor gate

The exact-source read-only monitor is `E:\catalyst-stability-monitor-0534103-primary\monitor.py` (SHA-256 `20F1B0AB825C08AB837D77A2DB40B2A2FF26A3B3DFD5DD1110FCA7EF35777D91`) as PID `170184`, bound to PID `185680`, its path and hash, port 5000, the original profile, Sage, database, and safety. Trace: `E:\catalyst-stability-monitor-0534103-primary\trace-60s.jsonl`. It began at **2026-10-09T19:11:02.049122Z** with a clean first sample; the second one-minute sample was also clean. Windows Veeam/VSS services were present in those samples. The 24-hour gate cannot be credited before **2026-10-10T19:11:02Z** and requires a continuous clean trace and fresh end-state audit. The monitor is planned for 25 hours to allow that audit.

## Independent secondary synthetic window

The secondary PC preserved an explicit rollover sidecar for its old `60eed8c` isolated synthetic canary: 59 alert-free samples through **2026-10-09T19:14:23.190399Z**, exactly 60 seconds apart. That incomplete historical window earns no 24-hour credit. It then started the independently built exact `0534103` EXE (SHA-256 `1FCF9D93DE9C07401D79C29819D08CDDD42FFE2F1F8C7B0023B672BF1D5DC361`) as isolated app PID `4484` on loopback port `56175`, with monitor PID `22724` and local mutual-TLS mock Sage on `56174`. Its original-profile app PID `15436` and port 5000 were left untouched.

The secondary synthetic monitor began **2026-10-09T19:16:43.517723Z**, targets a 25-hour endpoint at **2026-10-10T20:16:43.517723Z**, and had three exactly spaced alert-free samples at its first verification. Its bot was stopped, safety and lease were healthy, all offers, Coin Prep operations, fee reservations, journals, publications, and worker delegations were zero, and no mutating Sage RPC occurred. Evidence is under `monitor-05341035-synthetic-20261009T2017BST` on the secondary PC. Its 24-hour gate remains open and requires a full trace/end-state audit; it is synthetic and does not replace secondary original-profile live acceptance.

The separate active-offer lifecycle and recovery, secondary original-profile acceptance, live Splash peer receipt, full native UI, and final review remain open. No new campaign or fee scope has been approved. PR #220 and website PR #89 remain draft; no merge, tag, release, or public-readiness claim was made.
