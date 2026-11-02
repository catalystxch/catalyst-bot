# Coin Prep startup recovery routing on Harvestr

## Live finding

The first private v1.4.1 recovery package reached Startup Safety diagnostics on the original Harvestr profile. The durable Coin Prep operation stayed `PREPARED`; its wallet-effect claim had no resolution or dispatch; the latch reported `WALLET_EFFECT_CRASH_UNRESOLVED_UNRECONCILED`. No constructed outputs, fee reservation, fee outcome, pending transaction, offer, or wallet fee spend were found. Bot and Coin Prep stayed stopped.

The proof routine was not invoked. `desktop_app._initialize_startup_ownership` attempted Coin Prep recovery only for an explicit list of unresolved-operation reason codes, which omitted the live crash-claim reason. Commit `71faf54d39bf31a552e9b9e1f51cba93ab8590c3` adds that exact reason to the existing proof-only route. A regression failed before the change and passed afterward. Normal startup still requires a fresh authorization decision; failed or ambiguous proof remains in diagnostics.

## Verification

- Affected test groups: 362 passed.
- Exact-source serial Windows suite: 7,582 passed, 261 skipped, 457 subtests passed.
- Ruff, format, and all 11 PR checks passed.
- A clean detached private v1.4.1 package from the exact source passed packaged API and synthetic Sage certificate-authenticated read-only smokes, a Defender scan with zero detections, and a post-scan hash check. Executable SHA-256: `44784AA4842697336FA9F92FE9EFFB0E8717698941D95F64B9F42E7F585DA83E`. This is not a public release artifact.

The second PC made a SQLite online backup into an isolated data directory and proved both configured database paths resolved to the copy before invoking recovery. Fresh read-only Sage evidence showed the exact Harvestr identity, all 43 CAT source coins and the XCH fee coin selectable, and no pending transaction. The exact no-effect proof on the copy marked the operation `FAILED` with `AUTHORITATIVE_NO_EFFECT_CONFIRMED`, resolved the claim as `RELEASED_NO_EFFECT`, and cleared the latch. Independent read-only checks confirmed the original database hash and unresolved state did not change. No wallet effect occurred.

## Original-profile recovery

The operator launched the exact private executable on the Harvestr PC. The sole CATalyst process, PID 23560, ran from the verified package path with SHA-256 `44784AA4842697336FA9F92FE9EFFB0E8717698941D95F64B9F42E7F585DA83E` and exclusively owned `127.0.0.1:5000`. The package reported version 1.4.1 and a stopped bot.

Read-only inspection of the original database found `PRAGMA quick_check` `ok`. The stuck operation became terminal `FAILED` with `AUTHORITATIVE_NO_EFFECT_CONFIRMED` at `2026-10-10T19:14:22.188464Z`; constructed outputs remained null. Its generation-1 wallet-effect claim became `RELEASED_NO_EFFECT` with `PRE_DISPATCH_PREP_NO_EFFECT_CONFIRMED`. There were zero wallet dispatches, approved-fee reservations, or approved-fee outcomes for the operation. The generation-144 safety latch was resolved, with no blockers. The runtime lease was owned and renewing. There were no active workers, active offers, nonterminal publications, active reservations, or unresolved Coin Prep operations.

An independent read-only Sage check confirmed Harvestr mainnet fingerprint `3702373391`, wallet ID 2 and the exact MZ asset. XCH remained `240.800676512155`, MZ remained `3381521.720`, and pending transactions and fillable offers were zero. No wallet action was performed during recovery.

## Remaining gate

Bot and Coin Prep remain stopped. The active campaign has a 2,400,000 MZ budget, which differs from the separately approved 2,864,600 MZ scope. It must not be started without correcting that scope and a fresh action-time review. This private recovery result does not by itself complete the live offer lifecycle or general public-readiness gates.
