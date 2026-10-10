# Independent exact `b05a1cd` packaged authority conflict

The secondary PC exercised the pinned production runtime/source
`b05a1cd1d8210dd5e247094d38a6be4a54257805` from the extracted Windows
acceptance package. The packaged `Catalyst.exe` SHA-256 was
`EF8F0E3AFB5966AF9A372CACD7CCED979D368CD4BB8DDD11D54F508F1CAA3C28`.
It used a fresh isolated synthetic Sage mTLS mainnet profile, fingerprint
`123456789`, wallet ID `2`, and non-5000 ports. The original profile, real
Sage, and independent 25-hour canary were untouched.

Five focused exact-source tests passed in 3.43 seconds, covering prepared and
submitted blockers, mutation API diagnostics, prepared-create publication
recovery order, unresolved publication fail-closed behavior, and active-offer
publication recovery.

The packaged negative scenario seeded a valid prepared offer-creation intent.
Synthetic Sage then reported the selected CAT coin as bound to a contradictory
offer ID. On restart, the packaged app entered read-only diagnostics. Safety
reported `allowed=false`, reason `UNRESOLVED_OPERATIONS`, with one blocker.
`POST /api/bot/start` and `POST /api/offers/cancel_all` both returned HTTP 423.
No synthetic Sage mutating RPC or Dexie publication occurred.

After synthetic Sage supplied exact mTLS `/get_offer` authority binding trade
`32ac45a75186669390e8622846a5f5958e5f19bfbdd397b39b5d249b326d922e`
to the original intent and marking it confirmed, the packaged app restarted
normally. Safety became allowed, and `GET /api/offers` returned exactly one
sell offer. The read-only run still had zero Sage mutations and zero Dexie
posts. Terminal DB `PRAGMA quick_check` returned `ok`; the latest operation
was `FINALIZED`/`CONFIRMED` with `blocks_mutation=0`, zero blockers, a
resolved latch, and a lease released after shutdown. Publication rows remained
queued and unclaimed with attempt count zero because strategy dispatch was
intentionally not started. Thus this scenario proves fail-closed recovery
and authority reconciliation, **not** packaged post-resolution dispatch.

Two exploratory probes were excluded from this passing result. One used an
unlocked coin and resolved automatically, so it did not create a conflict.
Another started strategy and invoked synthetic Coin Prep with one synthetic
`/create_transaction`; it cannot support the read-only negative claim. An
isolated leaked PID `20860` was stopped after exact-path verification. No
real wallet effect occurred.

The separate exact-build 25-hour canary remained undisturbed: monitor PID
`22808`, app PID `5656`, 39 sequential samples, zero alerts and zero
mutations at the secondary postflight check. C: had 4.377 GiB free then.

The complete remote report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\exact-b05-negative-authority-20261010T0140BST\acceptance-report.md`,
SHA-256 `06BAA8B710B001497CDE045D0B3FCB18E764071C4328D9461219FF871C53BED4`.
Result, terminal audit, scenario and harness SHA-256 values are, respectively,
`2C9A111B83FA4E9BEC4F0F06BAED444149064D1FF94BEB619603E6B0834E3E93`,
`B7D4FCA507030407E09DF52E01CC72B7C53CED4FB6C1437458CF433AE230A98D`,
`0F46272BC45D88CF03AABA15788B5C6AE07BAA17CD3FED4F0156B1A31DF842CA`,
and `5D7CEC94D3BC5BB12EDE0021C18278E211A6B74628DD4FEDB8ADB21E25BE5A3A`.
