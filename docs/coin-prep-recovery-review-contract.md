# Coin Prep replacement review integration contract

Status: owner-only admission, scope inspection, unsigned preview and the
one-shot consent route are wired. Live replacement submission still requires
the user's explicit click on the displayed fee review.

The current preview route takes an empty body: the server selects the exact
operation, source coin and unique matching Sage pending transaction. It prices
the candidate through `prepare_coin_prep_rbf_review`, records its immutable
review journal and returns only sanitized display fields. The HTML page uses
an explicit preview form submission; JSON callers send `{}`. No fee, action,
transaction ID, unsigned bundle or destination is accepted from the browser.

## Current startup boundary

`desktop_app._initialize_startup_ownership()` reconciles submitted Coin Prep
operations, then retries normal authorization. A remaining
`COIN_PREP_RECOVERY_REQUIRED` blocker enters the separate standard-library
`read_only_diagnostics` listener. That listener must remain unchanged: every
request other than its safety page and safety-status GET is locked, including
all POSTs. It must never acquire a lease, initialize the main API, or build a
wallet replacement.

The existing campaign `/api/coin-prep/fee-preview` and `fee-approval` routes do
not replace a pending transaction and must not be reused for recovery.

## Owner-only admission

Add a separate restricted mode only after the recovery service supplies an
exact candidate predicate and durable replacement-attempt journal. Follow the
existing `activate_no_effect_creation_restricted_startup` pattern:

1. Require the exact durable Coin Prep recovery reason and unresolved-operation
   identity, configured wallet fingerprint/network, no bot, and no current
   runtime. Reject unrelated blockers and additional unresolved operations.
2. Acquire an exclusive lease with the configured wallet identity binding.
   Recheck the durable latch, exact operation version and candidate after
   acquiring the lease. Require `owned_by_this_run`.
3. Start the lease heartbeat before making the recovery page available. On any
   failure release only this run's owned lease and preserve the latch.
4. Skip `create_bot()` and `_start_owned_runtime_services()` in this mode.
   `_create_desktop_bridge()` must return `None`; never attach `AppBridge`.
5. Extend the global restricted-mode route allowlist only for `/`, safety
   status and dedicated recovery routes. Apply existing loopback, local-token,
   origin and private-read checks. HEAD must not invoke wallet observations.

Do not authorize a general wallet mutation merely because restricted startup
owns a lease. The service must validate a recovery-scoped authority for the
exact operation and replacement attempt on every request.

## Dedicated service hooks

`inspect_pending_recovery(authority)` returns the exact durable operation ID,
operation version, wallet/network binding, original transaction ID, original
input coin IDs and integer mojo amounts, original fee, confirmation/mempool
observations and observation time. Missing or ambiguous evidence returns an
unavailable result. It never clears a latch or dispatches a transaction.

`preview_pending_replacement(authority, operation_id, operation_version,
fee_mojos)` constructs and independently inspects an **unsigned** replacement.
It never signs or submits. The result includes a server-owned attempt ID,
expiry, unsigned-spend hash, original transaction ID, exact input set, output
coin IDs and amounts, total fee and original fee, fee delta, and the
operation/journal version. All amounts cross JSON as canonical decimal integer
strings. The preview must show unchanged intended split outputs and explain
which change output funds the fee. Additional inputs or destination changes
require a fresh explicit review. The suggested fee is shown before approval.

The submission handler accepts only the immutable attempt ID, review digest
and explicit confirmation, never a client-provided spend bundle. It rechecks lease,
wallet binding, operation/journal version, original inputs still unspent,
original/replacement confirmation state, preview expiry and fee consent before
signing. It persists a sign intent before Sage signing and a separate one-shot
submit marker immediately before the Sage submit request. Ambiguous submission
stays latched and is not retried automatically.

## Page behavior

Use a separate recovery HTML page, not the trading dashboard. Render wallet
data with `textContent` (or `escapeHtml` for necessary HTML). Show original
pending transaction and proposed replacement side by side, including exact
IDs, input/output amounts, original fee, replacement fee and fee delta. Link
neither identifiers nor destinations to unvalidated URL schemes.

The initial page only loads inspection data. An explicit **Build unsigned
replacement preview** click requests a fresh cost-specific network fee; the
browser supplies no fee or transaction details. A stale quote, changed
authority or error disables submission. No preview request runs on page load,
polling or a GET navigation.

The enabled review requires an unchecked fee acknowledgement and an explicit
**Submit this replacement** click. The durable one-shot marker rejects repeat
submissions; an uncertain response displays pending reconciliation and must
never automatically repeat the request. Successful submission still leaves
trading blocked until independent exact on-chain reconciliation completes.

## Required integration verification

- A non-owner diagnostics process rejects every recovery route and every
  write verb, imports no wallet module and leaves database bytes unchanged.
- Admission rejects missing/stale/foreign lease, other reason codes, wallet
  mismatch, additional unresolved operations and a candidate changing between
  the precheck and lease acquisition. Startup constructs no bot or bridge.
- Restricted owner routes reject trading, settings, coin-prep triggers and
  ordinary campaign fee approval. Foreign-origin and missing-token requests
  cannot inspect private recovery details or build a preview.
- Inspection and unsigned preview never call signing/submission adapters or
  normal fee-approval hooks. Repeated previews cannot dispatch an attempt.
- Test exact mojo strings above JavaScript's safe integer limit; reject float,
  bool, exponent, negative, whitespace and noncanonical fee inputs.
- Preview validation rejects changed source inputs, output destinations,
  operation version, wallet binding or fee mismatches. Stale previews cannot
  authorize a later attempt.
- Browser verification confirms hostile server strings remain inert, no
  submission occurs on load/preview/reload, fee edits revoke approval, and a
  double click or ambiguous response cannot cause a second dispatch.
- Reconciliation tests cover original confirming before replacement, the
  replacement confirming, neither confirming, source spent elsewhere, crash
  before dispatch and crash after ambiguous dispatch. Only exact terminal
  evidence may clear the startup blocker.
