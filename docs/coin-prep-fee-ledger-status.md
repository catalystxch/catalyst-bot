# Fee approval ledger: draft groundwork

This change adds a database component, not an operational fee approval feature.
No wallet submission path uses it yet. Do not rely on it to limit live fees.

Approvals are immutable and versioned within an economic scope. Reservations
use exact integer mojos and BEGIN IMMEDIATE to serialize competing callers.
Existing commitments count against later approvals in the same scope. Replaying
an unchanged existing operation returns its reservation; stale approvals cannot
reserve new operations. Total fees and the separate non-cancellation allowance
are checked together. The caller supplies cancellation policy and identity/plan
digests; these are not yet derived or validated against a live wallet.

Reservations are conservative permanent holds in this draft. Pending, unknown,
and confirmed effects are not yet distinguished. No release API exists: even a
proven no-effect operation stays counted. This avoids accidentally refunding an
unknown external effect, but can exhaust an allowance unnecessarily.

Remaining before live use:

- Bind exact validated fees and identity to every relevant wallet dispatch.
- Add authoritative confirmation/no-effect evidence and recovery transitions.
- Add unsigned estimates, freshness checks and explicit normal-GUI approval.
- Reconcile prior submitted operations and historical fees idempotently.
- Integrate diagnostics/accounting without double counting existing fees.
- Test affected GUI, cancellation/recovery and complete live workflows.

Tests use isolated SQLite databases and cover observed relay-fee boundaries,
protected cancellation allowance, stale/wrong-scope approval, duplicate/conflicting
operations, cap increases, connection restart, malformed fees and concurrency.
This draft is for review and must not be represented as fixing the live defect.
