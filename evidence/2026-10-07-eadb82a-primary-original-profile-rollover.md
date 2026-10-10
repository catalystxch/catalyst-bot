# Original TEST 7 rollover to exact `eadb82a`

On 2026-10-07, the older original-profile `f0e1e97` app remained the sole
CATalyst process and port-5000 owner in terminal read-only
`HEARTBEAT_FAILED`. Its EXE path and SHA-256 matched the historical package.
Before rollover, direct Sage read-only mTLS returned mainnet fingerprint
`736588221`, the exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
selectable XCH `138470301476875` mojos, MZ `780212284` atomic units, zero
pending transactions and zero nonterminal offers across 4,095 Sage records.
The original database had zero active campaigns, open MZ offers, coin locks,
or unresolved offer-operation blockers. Prior campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
was stopped with zero authoritative fee spend and no campaign fee approval.
The old app was confirmed `bot_running=false` and safety-fenced, then closed
through its native window close handler. It exited and released port 5000.

The exact clean candidate EXE
`E:\catalyst-sage-tls-eadb82a-build\dist\Catalyst\Catalyst.exe` had SHA-256
`8E8EFDD7A175FE50D5BF168AF0EB4D6A4E7FB557BC8C6B68B2111C834356EF02`.
An initial hidden launch reached the API as sole PID `160668`, but the Sage
startup phase remained idle. It was stopped normally while the bot was off.
The same EXE was then launched with its native window visible. At
`2026-10-07T18:19:59Z`, it was sole PID `120856` and sole port-5000 owner.
Safety was allowed with a renewing owned lease and zero blocker counts. The
bot remained stopped. A post-rollover direct Sage read at
`2026-10-07T18:18:31Z` showed unchanged fingerprint, asset, balances, zero
pending transactions and zero nonterminal offers. A database read showed the
campaign still stopped and zero open MZ offers or unresolved blockers.

At this checkpoint, `/api/sage/startup-status` was `idle` with no selected
fingerprint and `/api/health` reported Sage `not_started`. Native UI inspection
showed the Risk Disclosure waiting for acknowledgement. The operator had
previously authorized testing acknowledgement, but an unrelated PhotoRec
recovery window was foreground and the prior native UI traversal had been
interrupted by the operator. No mouse input or API bypass was used. This is a
safe, stopped original-profile rollover, **not** live Sage acceptance or the
start of a 24-hour stability window. Complete native startup, recheck all
wallet/safety invariants, then begin an exact-PID/hash monitor. The earlier
`f0e1e97` 24-hour trace failed and cannot count. No wallet effect occurred.

PR #220 remains draft. Active-offer lifecycle and recovery, secondary exact
original-profile acceptance, both exact-candidate 24-hour windows, full UI
acceptance and final review remain open.
