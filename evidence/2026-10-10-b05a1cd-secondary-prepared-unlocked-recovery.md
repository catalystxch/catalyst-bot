# Independent exact `b05a1cd` prepared-input recovery

The secondary PC ran the exact packaged runtime/source
`b05a1cd1d8210dd5e247094d38a6be4a54257805`, EXE SHA-256
`EF8F0E3AFB5966AF9A372CACD7CCED979D368CD4BB8DDD11D54F508F1CAA3C28`,
against a fresh isolated synthetic Sage mTLS profile and non-5000 ports.
It did not access the original wallet profile, real Sage, or the independent
25-hour synthetic canary.

The scenario seeded a `PREPARED` offer-creation intent whose selected input
coin was authoritatively still owned, unspent, and unlocked. On packaged
restart, recovery finalized the journal entry as `FINALIZED`/`FAILED` with
reason `CREATE_PREPARED_INPUT_PROVEN_UNLOCKED` and `blocks_mutation=0`. The
intent became `creation_failed`; the selected coin was free with no trade ID.
Safety was allowed, with zero offers. There were zero synthetic Sage mutating
RPCs and zero Dexie posts. `PRAGMA quick_check` returned `ok` for the
bootstrap, recovered, and terminal database snapshots. The lease was released
and the safety latch resolved after shutdown. This proves this specific
prepared-input recovery path, not a real-wallet lifecycle.

An initial exploratory probe falsely failed its harness by comparing a
database-normalized `0x` coin ID with an unprefixed fixture. That probe was
preserved. The fixture comparison was corrected, and a fresh isolated run
passed without a product-source change.

At postflight, the protected exact-build canary remained alive at monitor PID
`22808` and app PID `5656`, sample 50 at `2026-10-10T00:42:03.037406Z`,
with zero alerts and zero synthetic mutation paths. C: free space was
4,677,931,008 bytes.

The complete remote report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\exact-b05-prepared-unlocked-recovery-20261010T0150BST\acceptance-report.md`,
SHA-256 `21EFF72FB831EF30302F0BAABF7571AE30D4CD39E661C512E4D5A91F356C701B`.
The result JSON and terminal DB snapshot SHA-256 values are respectively
`AB54028206C5AEC5E6B6CE71131704C857DB4F35EE359DB9D38133743CF19FCD`
and `D081107C34084E2BCF1E834D08B9C1D98696C37796070BB9E4CAA408027A4A85`.
