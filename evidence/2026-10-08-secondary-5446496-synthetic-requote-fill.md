# Secondary exact-package synthetic requote and fill acceptance

On 2026-10-08, the independent secondary PC reported a bounded pass from a
fresh isolated profile using packaged source
`54464960fdad711c378e521f3969593e24439717` and EXE SHA-256
`37DFA6EDEDE426712102CCC0A4973822944DC6C916D5974047A90D14AD59B110`.
Its full local report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\exact-544-synthetic-requote-fill-attempt5-20261008T1915BST\REPORT.md`,
SHA-256 `D62EE80C8D9E7FCAE6A4FC3EAC9669324617FCEC799B5F84DFA0FD3792D36F1A`.

The product created and published an initial offer, reacted to a 297 bps
market move by creating and publishing a distinct replacement, confirmed
cancel of the old offer, and restarted with unchanged mutation counts and no
duplicate. A synthetic Sage chain fill then became
`verified_authoritative` with an immutable receipt. CATalyst created and
published one post-fill replacement, waited through its fill-sweep window,
stopped, and completed authoritative Cancel All. The mock wallet recorded
exactly five effects: make, make, cancel, make, cancel. Three Dexie
publications succeeded; Splash remained safely suppressed.

The synthetic fill transaction was
`3d5757ada81821f3e9e2aef7dae5727dcf3ef3e039250301f1dbb76c13da11dc`
at height 7000002. Its selected CAT coin was spent and the synthetic return
was 10,712,000,000 XCH mojos. The final audit reported zero API buys/sells,
nonterminal intents, blocking journal operations, locked coins, fee approvals
or reservations, active reservation leases, publication work, lineage
blockers, wallet-effect claims, and sweep registrations. The runtime latch
was resolved and its lease released.

One immediate-restart attempt entered the packaged app's conservative native
safety fallback. Its durable DB latch and lease were resolved and the state
remained safe. It did not recur with a two-second process-exit gap. The
secondary preserved this attempt at
`evidence\exact-544-synthetic-requote-fill-attempt4-20261008T1900BST`;
the restart timing warrants targeted diagnosis before final acceptance.

The concurrent exact-byte synthetic 24-hour canary remained clean through
reported sample 73 with zero wallet-mutating RPCs or alerts. The original
Harvestr process remained responsive and untouched. This synthetic pass does
not satisfy the required live mainnet TEST 7 offer/fee lifecycle, either
complete 24-hour audit, or secondary original-profile acceptance.
