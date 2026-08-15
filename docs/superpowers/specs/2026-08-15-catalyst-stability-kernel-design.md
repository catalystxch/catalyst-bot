# CATalyst Stability Kernel Design

**Date:** 2026-08-15  
**Status:** Approved  
**Implementation branch:** `codex/stability-kernel`  
**Source baseline:** `15f6aab` (`Fix dashboard Sage balance cache`)

## Context

CATalyst currently has useful offer lifecycle, pending-cancel, fill verification,
coin reservation, and startup recovery logic, but the safety decisions are spread
across large orchestration modules. A private V50.11-derived bundle adds stronger
ideas: a durable offer registry, typed cancel outcomes, authoritative terminal
proof, a process/durable mutation latch, replacement lineage, purpose-separated
capacity, staged refresh, durable publication, and long-gap recovery.

The private bundle is reference material, not a merge base. It has no usable Git
history, diverges substantially from current CATalyst, uses a large CSV registry
beside SQLite, and its evidence contains both clean focused runs and an earlier
combined run with failures. We will adapt its safety invariants to the current
SQLite architecture and preserve current CATalyst behavior where it is already
stronger.

The local Sage inspection also found two current-source hazards:

1. `wallet_sage.py` reads Sage settings directly from environment state and may
   generate a new client certificate when the canonical user-data `.env` lacks
   the Sage certificate paths. Sage rejected that certificate on this machine.
2. Sage `get_offers(include_completed=False, end=500)` returned 1,934 terminal
   records. Callers cannot trust filtering or absence without local normalization
   and freshness/provenance metadata.

## Goals

- Make offer creation, cancellation, replacement, fill recognition, and
  publication crash-recoverable and idempotent.
- Fail closed whenever wallet identity, wallet freshness, ownership, submission,
  or terminal state is ambiguous.
- Keep all durable state in CATalyst's SQLite database through `database.py`.
- Preserve exact parent/child replacement lineage and coin purpose.
- Make operator-visible reasons specific enough to diagnose and safely recover.
- Verify behavior with deterministic fault injection, the full test/build suite,
  and staged mainnet testing on the explicitly authorised Sage `TEST 7` wallet.
- Keep all work local until the user separately authorises GitHub integration.

## Non-goals

- Wholesale copying of the private fork.
- Running the private unsigned executable.
- Replacing CATalyst's Python/Flask/PyWebView architecture.
- Treating Dexie, Splash, or missing Sage records as authoritative terminal proof.
- Mutating any Sage key other than the configured and freshly verified key.
- Automatically clearing ambiguous state merely to restore trading throughput.

## Safety invariants

These invariants apply at every wallet mutation boundary:

1. **Exact wallet binding.** The active Sage fingerprint, network, key kind, and
   signing capability must match the operation's durable binding immediately
   before a wallet mutation. A mismatch blocks the operation.
2. **Intent before effect.** CATalyst persists a unique operation and its exact
   intent before calling Sage. It never holds a SQLite transaction open across a
   network call.
3. **Unknown is not success.** Timeout, disconnect, malformed data, 404, stale
   cache, missing record, conflicting providers, or missing transaction identity
   becomes an unresolved outcome.
4. **Absence is not terminal proof.** Filled, cancelled, and expired transitions
   require an authoritative Sage status or exact transaction/coin/height proof.
5. **Unresolved state freezes mutations.** Any unresolved create, cancel,
   replacement, fill, or registry inconsistency trips a durable mutation latch.
   Read-only reconciliation and diagnostics remain available.
6. **One identity, one effect.** Unique database constraints and idempotency keys
   prevent duplicate creation, cancellation, fill recording, or publication.
7. **Lineage before retirement.** A refresh parent is not retired until the child
   creation and visibility state required by policy is durably verified.
8. **Atomic amounts only.** Prices and display amounts use `Decimal`; coin and
   offer amounts use integer atomic units. Serialized amounts are exact strings
   where SQLite's signed integer range could be insufficient.
9. **Evidence is bounded and durable.** Raw RPC evidence is redacted, size-bounded,
   canonicalized, and accompanied by a digest. No secrets or full puzzle reveals
   are persisted in diagnostics.
10. **No silent escape hatch.** Clearing a durable safety latch requires the
    recorded blockers to be authoritatively resolved or an explicit operator
    quarantine operation that preserves the prior state and evidence. Quarantine
    cannot restore mutation permission unless a fresh authoritative full-history
    read proves the offers absent and their input coins owned and unlocked.
11. **One mutation owner.** One CATalyst run owns the mutation lease for a data
    directory. A second process is read-only. A coin-prep child receives a narrow,
    expiring delegation token instead of becoming an independent owner.

## Architecture

### 1. Durable registry and journal

New tables are created idempotently by `database.py`:

#### `offer_intents`

The canonical identity and current state of every CATalyst-owned offer:

- `intent_id` primary key and `run_id`
- wallet fingerprint hash, network, asset ID, side, tier, and purpose
- generation and nullable parent/child intent IDs
- offered/requested atomic amounts as exact decimal strings
- selected coin IDs as canonical JSON and a digest
- offer text hash, Sage trade ID, and publication identity
- lifecycle state and optimistic row version
- creation, submission, confirmation, visibility, terminal, and update timestamps

Unique constraints cover Sage trade ID, offer hash, and active slot/generation
where applicable. Foreign-key-like validation is performed in database functions
because existing SQLite migration behavior must remain compatible.

#### `offer_operation_journal`

Append-only events for `CREATE`, `CANCEL`, `REPLACE`, `PUBLISH`, `FILL`,
`RECONCILE`, and `QUARANTINE` operations:

- unique event and operation IDs
- intent ID, attempt number, phase, and typed outcome
- request timestamp and wallet identity snapshot
- transaction/spend identity when available
- bounded canonical evidence JSON, evidence SHA-256, reason code, and timestamp

The current operation state is derived through database query helpers. Callers do
not issue raw SQL.

#### `runtime_safety_latch`

A singleton durable latch containing generation, tripped/resolved state, reason,
blocking operation IDs, wallet binding, and timestamps. A process-local event
mirrors it for fast checks, but the SQLite row is authoritative after restart.

#### `runtime_mutation_lease`

A singleton run lease with owner UUID, process metadata, wallet binding,
heartbeat, and expiry. Acquisition and takeover use compare-and-set transactions.
Expiry alone does not permit takeover: the new process must also prove the prior
process is gone locally and reconcile all in-flight operations. Child workers use
operation-scoped delegation records tied to the parent run and exact purpose.

#### `publication_outbox`

Durable, idempotent publication records keyed by network, offer fingerprint, and
publication epoch. States are queued, claimed, succeeded, retryable, suppressed,
or unresolved. Stale claims can be safely reaped after ownership checks.

### 2. Domain modules

- `mutation_gate.py`: validates durable blockers, current wallet identity, network,
  signing capability, and freshness immediately before mutation.
- `cancel_outcomes.py`: canonical typed outcomes and safe result normalization.
- `offer_registry.py`: pure transition/authorization policy over records returned
  by `database.py`; it contains no raw SQL or wallet calls.
- `offer_reconciliation.py`: read-only evidence collection and pure terminal
  classification, followed by a narrow database commit boundary.
- `refresh_safety.py`: deterministic staged refresh plans and verified lineage.
- `replacement_capacity.py`: purpose-aware reserve/readiness decisions.
- Existing `wallet.py` remains the only adapter entry point. Defense-in-depth
  mutation checks are placed both in orchestration and immediately around adapter
  calls so a bypassing caller cannot mutate silently.

The private fork's pure helpers may be adapted when their semantics and tests fit.
Its CSV persistence and environment-driven registry bootstrap will not be copied.

### 3. Configuration and Sage identity

`config.py` and its `cfg` singleton remain canonical. Wallet modules stop making
independent configuration decisions from `os.getenv()` where a typed `cfg` value
exists.

Sage certificate resolution becomes deterministic:

1. Explicit canonical `cfg` paths.
2. Auto-detected Sage `wallet.crt`/`wallet.key` pair in Sage's platform data dir.
3. A generated client certificate only if a supported Sage version explicitly
   accepts it; otherwise setup fails closed with an actionable reason.

Startup reports the chosen source without exposing private paths or key material.
RPC error output uses the existing encoding-safe console/log path rather than
printing Unicode directly to a CP1252 terminal.

For the mainnet lab, an isolated `CMM_DATA_DIR` binds `SAGE_FINGERPRINT` to
`736588221`. Every mutation also verifies Sage reports name `TEST 7`, fingerprint
`736588221`, `network_id=mainnet`, `kind=bls`, and `has_secrets=true`. The
fingerprint is a test-environment binding, not a hard-coded production constant.

## Operation flows

### Create

1. Build and validate an immutable intent using atomic amounts.
2. Check slot uniqueness, coin purpose, reservation, latch, and fresh wallet
   identity.
3. In one short SQLite transaction, insert the intent and `CREATE/PREPARED` event
   and reserve selected coins.
4. Call Sage outside the transaction with an idempotency/operation correlation ID
   where the RPC supports it.
5. Record `CONFIRMED`, `SUBMITTED_UNCONFIRMED`, `FAILED`, or `UNKNOWN` with bounded
   evidence.
6. Only confirmed creation commits the Sage trade ID and unlocks publication.
   Submitted/unknown creation trips the latch until reconciliation proves whether
   an offer exists.

A crash after step 3 leaves a prepared operation that startup can reconcile. A
crash after step 4 cannot lead to blind re-creation because the durable intent is
already present.

### Cancel

Canonical cancel outcomes are:

- `CANCEL_CONFIRMED`
- `CANCEL_SUBMITTED_UNCONFIRMED`
- `CANCEL_FAILED`
- `CANCEL_UNKNOWN`

`success=true`, HTTP 404, an absent open-offer row, or a third-party terminal
status is never sufficient by itself. Submitted results require a transaction ID
or exact spend identity. Ambiguous submissions retain the locked coins and block
replacement until the reconciliation path proves cancellation or fill.

### Terminal reconciliation

The reconciler gathers fresh Sage offer history, transaction history, and relevant
owned/spent coin records with source timestamps. A pure classifier returns one of:

- `FILLED_PROVEN`
- `CANCELLED_PROVEN`
- `EXPIRED_PROVEN`
- `ACTIVE_PROVEN`
- `UNKNOWN`
- `CONFLICT`

Proof must match offer identity, assets, exact atomic amounts, input coins, height,
and timing as applicable. Conflicting fill/cancel evidence stays blocked. Database
and fill mutations occur only after policy authorization and in one transaction.

### Replacement and refresh

Refresh is staged by default. A replacement intent points to exactly one parent,
and the parent records exactly one child. Capacity is counted by explicit purpose:
normal lifecycle, replacement, fill response, operator recovery, or fee reserve.

The default sequence is create child, durably verify creation, publish/verify when
required, cancel parent, prove the parent's terminal state, and commit lineage.
If safe capacity cannot support overlap, the plan pauses instead of mass
cancelling. Explicit mass cancellation remains an operator action and is still
subject to ownership and mutation-gate checks.

### Publication

Creation queues publication in the same database transaction that confirms the
offer identity. Workers claim rows using compare-and-set state. Retries retain the
same idempotency key. Terminal offers suppress queued/in-flight publication.
Dexie/Splash visibility affects publication health and replacement policy but does
not prove wallet terminal state.

## Startup and long-gap recovery

Startup is read-only until all gates pass:

1. Initialize database and validate migration/integrity.
2. Load the durable latch and unresolved operation set.
3. Verify Sage RPC, exact identity, network, signing capability, sync/freshness,
   and certificate source.
4. Normalize Sage offer history locally; do not trust remote filters or page
   bounds without validation.
5. Reconcile prepared, submitted-unconfirmed, unknown, and nonterminal operations.
6. Reconcile publication claims and coin reservations.
7. Permit mutation only when blockers are empty and required reads are fresh.

After a VM pause, system sleep, clock jump, or long polling gap, the bot repeats
the freshness and reconciliation gate before resuming. Last-known-good data may be
displayed with age/provenance but cannot authorize a mutation.

## Diagnostics and operator controls

The API/GUI exposes a compact safety status:

- allowed/blocked state and stable reason code
- active wallet/network binding (fingerprint redacted except in explicit setup)
- data freshness and last successful authoritative read
- unresolved operations grouped by type
- registry, lineage, reserve, and publication counts
- recommended safe action

AppBridge methods keep the existing `{success: bool, ...}` contract. Server data
rendered into HTML follows the existing escaping and event-delegation rules.
Operator quarantine archives the unresolved epoch and evidence; it does not label
unknown offers cancelled or release possibly locked coins without proof. If full
history or input-coin ownership remains indeterminate, the quarantined epoch stays
on the latch's blocker list and mutation remains disabled.

## Delivery phases

### Phase 1: offer-safety kernel

Implement schema, typed outcomes, registry policy, durable/process latch, wallet
identity/freshness guard, create/cancel journaling, and startup reconciliation.

### Phase 2: replacement and coin safety

Add exact lineage, staged refresh, purpose-aware capacity, idempotent coin prep,
post-split verification, and ambiguous-coin blocking.

### Phase 3: recovery, publication, and diagnostics

Add outbox-based Splash/Dexie publication, claim recovery, long-gap/session
recovery, configuration/certificate hardening, and operator-facing status.

### Phase 4: local and mainnet verification

Complete deterministic and fault tests, full regression/build verification, then
run the staged `TEST 7` mainnet acceptance plan.

Each phase is independently testable and commit-sized. Later phases cannot weaken
earlier invariants.

## Test strategy

Implementation follows red-green-refactor. Production behavior is added only
after a focused failing test demonstrates the missing guarantee.

Automated coverage includes:

- schema migration from current and representative legacy databases
- state-machine and invalid-transition tables
- cancellation result normalization, including 404/timeout/disconnect cases
- crash injection before and after every durable/network boundary
- restart recovery for prepared and submitted-unconfirmed operations
- duplicate/racing create, cancel, fill, and publication attempts
- competing process leases, stale-owner recovery, and worker delegation expiry
- exact evidence matching and deliberately ambiguous/conflicting histories
- wallet fingerprint/network changes between preflight and RPC call
- stale/zero/malformed Sage reads and ignored remote filters
- parent/child lineage, staged batches, and reserve-purpose accounting
- SQLite WAL concurrency and lock contention
- CP1252-safe logging and Sage certificate-source selection
- API/AppBridge diagnostics and frontend escaping where UI changes are made

Fast deterministic tests use fake clocks. Real-time waits are confined to explicit
timing/soak tests. The current baseline is:

`3300 passed, 13 skipped, 3 warnings, 42 subtests passed`.

Completion requires fresh successful runs of relevant focused tests, the full
suite, static/security checks already used by the repository, and `python build.py`.

## Authorised TEST 7 mainnet acceptance

Mainnet mutations are authorised only when the live identity gate reports:

- Sage name: `TEST 7`
- fingerprint: `736588221`
- network: `mainnet`
- key kind: `bls`
- signing: enabled

Any asset and contents in that wallet are authorised. Testing remains staged to
make failures diagnosable:

1. Read-only identity, balance, CAT discovery, offer normalization, and freshness.
2. One small, wide-spread SBX/XCH create/publish/cancel lifecycle.
3. Forced app restart after prepared, created, submitted-cancel, and publication
   checkpoints where safely reproducible.
4. Sage disconnect/stale-read, sleep/long-gap, and retry tests with mutation freeze.
5. Multi-offer staged replacement waves and coin-purpose verification.
6. At least one genuine on-chain fill path, followed by authoritative fill
   recording and replacement-capacity checks. If an external maker fill is not
   available in a practical window, use an isolated same-`TEST 7` self-take with
   disjoint, pre-verified inputs and preserve the transaction evidence.
7. Sustained soak with periodic invariant snapshots.
8. Final reconciliation of Sage history, SQLite registry/journal, publication
   state, reservations, offer book, and balances.

The live run fails if it produces a duplicate offer, false terminal transition,
unproven coin release, identity bypass, unexplained balance drift, unresolved
operation, or mutation during stale/blocked state. A failure returns to automated
reproduction and repair before live testing resumes.

## Completion and handoff

The goal is complete only when all four phases are implemented, the clean build
and automated verification pass, the authorised mainnet acceptance has reconciled
without unresolved safety findings, and the user receives the local build,
evidence summary, known limitations, and exact branch/worktree location.

No push, pull request, merge, or change to GitHub `main` is part of this design.
