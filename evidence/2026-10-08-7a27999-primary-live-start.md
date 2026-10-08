# Exact 7a27999 primary TEST 7 live start

## Scope

This is an interim, read-only original-profile startup record for exact source
`7a279999d7eb448788e259d569c39fbc011178eb`. It does **not** prove a
24-hour stability window, an active-offer lifecycle, or public readiness.

## Historical rollover

The earlier `f9a1d3e4f7443595c44352d714d2aea3f1fef755` stopped-profile
monitor was intentionally retired after sample 391. Its partial trace and
`E:\catalyst-stability-monitor-f9a1d3e\retirement-note.json` were preserved.
It cannot count toward the final candidate's 24-hour gate. The old app was
stopped by its native window close event after the bot and wallet were checked
stopped; PID 38104 exited and port 5000 became free. An unauthenticated API
shutdown request returned 401 and caused no shutdown or wallet effect.

## Exact package and preflight

- Detached build checkout `E:\catalyst-cancel-wallet-final-build` was at exact
  source `7a279999d7eb448788e259d569c39fbc011178eb`.
- Launched `E:\catalyst-cancel-wallet-final-build\dist\Catalyst\Catalyst.exe`.
  Its SHA-256 was
  `66FF84A8CA69E0C9CFCAFFFE464F1D6A419CD0A2EEDCD4E20BE98F21F10A2BF8`.
- The new app was sole `Catalyst.exe` PID 176760 and sole port 5000 owner.
  `/api/health` reported version 1.4.0, Sage backend and stopped bot.
  `/api/safety/status` reported allowed safety, owned active lease and zero
  blocker counts.
- Read-only Sage RPC showed mainnet TEST 7 fingerprint 736588221, CAT wallet
  ID 2 with MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
  synced wallet, 138470301476875 confirmed/spendable XCH mojos,
  780212284 confirmed/spendable MZ atomic units, zero pending transactions,
  and zero nonterminal offers across a complete 4095-offer history.
- Database reads showed zero open offers, active campaigns and unresolved
  offer operations. The previous campaign
  `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
  remained stopped with zero authoritative fee spend.

## Exact-candidate endurance gate

The exact-PID/hash monitor began at **2026-10-08T23:19:31.784379Z** as PID
34544, writing
`E:\catalyst-stability-monitor-7a27999-prepared\trace-60s.jsonl`. Its
first read-only sample had zero alerts, with matching process/hash/port,
allowed safety, owned fresh lease, stopped bot, zero durable offers and
operations, and unchanged Sage identity, balances, pending state and offer
history. The trace verifier reported `in_progress`, zero problems and no
terminal record.

Do not credit the 24-hour gate before **2026-10-09T23:19:31.784379Z**.
The monitor plans 25 hours; a complete terminal trace, independent end-state
audit, and a fresh wallet/DB review are required. The active-offer lifecycle,
secondary exact-candidate original-profile acceptance, active-profile
24-hour window, full native UI and final review remain open. PR #220 and the
website beta PR remain draft; no campaign, fee approval, offer, release or
website deployment was created here.
