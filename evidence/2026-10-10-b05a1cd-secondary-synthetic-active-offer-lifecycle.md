# Independent exact `b05a1cd` synthetic active-offer lifecycle

The secondary PC ran the pinned production runtime/source
`b05a1cd1d8210dd5e247094d38a6be4a54257805` from the extracted Windows
acceptance package. The packaged `Catalyst.exe` SHA-256 was
`EF8F0E3AFB5966AF9A372CACD7CCED979D368CD4BB8DDD11D54F508F1CAA3C28`.
It used a fresh isolated synthetic Sage mTLS mainnet profile (fingerprint
`123456789`, wallet ID `2`), synthetic Sage port `54881`, Dexie port `54882`,
and CATalyst ports `54883`, `55169`, and `55209`. The original wallet profile,
real Sage, port `5000`, and the independent 25-hour canary were untouched.

The scoped lifecycle passed: create and publish an offer, requote it and
authoritatively cancel the original, restart CATalyst and recover the
replacement without a duplicate Sage mutation, prove the replacement fill,
create and publish a remake, then authoritatively cancel the remake. The
three offer IDs were
`0a864dd23e3f8eae8c87c784698606da24276ae5831189dd16242752b3597ed8`,
`b17a72e31bb39abb67ef7342279f812b488edf3b8e4ca8f3ad55d2c64872caea`,
and `74675b982009f74f3860a03fbcfa677307e8a61735f38fbdfe618e99816281ae`.
The synthetic fill had transaction
`3d5757ada81821f3e9e2aef7dae5727dcf3ef3e039250301f1dbb76c13da11dc`
at height `7000002`. Sage mutation order was exactly make, make, cancel,
make, cancel; Dexie received three publications.

The terminal database audit returned `PRAGMA quick_check: ok`. All three
offers were terminal (two cancelled, one filled); all three intents were
terminal. Eight journal operations had terminal authoritative outcomes and
their latest `blocks_mutation` values were zero. Three outbox rows succeeded
and three were suppressed; three reservation leases completed. There was one
fill and one authoritative receipt, with zero approved fee reservations,
fee approvals, active worker delegations, or active offers. The runtime lease
was released and the safety latch resolved. All separate lifecycle app PIDs
exited. No CATalyst defect was found in this scoped run.

The secondary's independent 25-hour exact-build canary stayed live at
monitor PID `22808` and app PID `5656`, with 21 sequential samples and zero
alerts at its postflight check. This synthetic lifecycle does **not** prove
the original TEST 7 wallet lifecycle, an injected unresolved-authority
conflict, or a completed 24-hour window.

The complete remote report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\exact-b05-synthetic-active-offer-20261010T0110BST\acceptance-report.md`,
SHA-256 `8E43B6B343D1161B86016AA10CDF5D3C7137B3B4300D9BDA028B54E787920CC6`.
The result, terminal audit, and harness SHA-256 values are respectively
`F6C475E72F632979585050F41F12B110D22E2CC29B9B6F819313B5BB4A800B0F`,
`80370D74ADD958B43F70ABB8A6978C41200175BD9845DD289136FC7087C0B47F`,
and `AE6964CF0697AE571881B42FAA815BD021FB1F30CEC062C958A49D296C03B08B`.
