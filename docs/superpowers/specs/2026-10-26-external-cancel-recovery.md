# External Sage Cancellation Recovery

## Problem and evidence

TEST7's original profile has one locally open `normal_lifecycle` SELL intent for
`e6e9274b...8569e`. The human cancelled it in Sage while CATalyst was closed.
Sage now reports the offer cancelled, with no active offers or pending wallet
transactions. CATalyst's four recorded cancellation attempts all finalized
`CANCEL_FAILED` before a wallet effect. Task 9 currently requires a Task 8
submitted-effect claim to commit `CANCELLED_PROVEN`, so it cannot truthfully use
those failed attempts as authority for the later external transaction.

## Required behavior

1. A proof-only recovery path must detect a locally open intent whose exact Sage
   trade is cancelled and whose selected input coins were spent by a confirmed
   cancellation transaction returning the offered asset to the same wallet.
   The transaction's spent and created coin flows, fee, height, timestamp,
   trade identity, wallet fingerprint, network, and immutable intent economics
   must agree. An offer status label or missing offer alone is insufficient.
2. The durable record must explicitly identify the effect as **external**.
   It must never claim CATalyst submitted the wallet effect or retrofit a failed
   Task 8 attempt. It must not consume or enlarge a new Follow run's approved
   cumulative fee ceiling. The exact external fee belongs in a separate audit
   record and wallet balance reconciliation.
3. Commit the terminal offer, intent, coin rebindings and external fee audit
   atomically. Replaying the same proof is idempotent; changed proof or a second
   spend for the same input fails closed. An unresolved or contradictory proof
   keeps the local row open and blocks new trading on that wallet.
4. The native app must show the exact trade, wallet, returned amount, fee and
   evidence status before the user confirms local recovery. This confirmation
   changes local records only. It must never call a wallet-effect method.
5. Startup and running-state checks must surface the discrepancy plainly.
   The 24/24 Follow run cannot start until Sage and the original database agree
   on the terminal outcome and the profile passes the normal safety gates.

## Boundaries

- Existing Task 8/Task 9 CATalyst-submitted cancellation proof remains intact.
- A generic `CANCELLED` Sage label, expired offer, pending transaction, absent
  coin, external coin flow, or mismatched selected input is not recovery proof.
- The test wallets use the original profiles. No database reset or direct SQL
  repair is part of this workflow.
- Current user choice for a subsequent Follow run is an initial 0.005 XCH
  cumulative fee ceiling per PC, revisable during the active run only after a
  fresh native review of spent, held, and proposed ceiling.

## Verification

- Pure evidence tests for exact external return, same-asset/coin mismatch,
  missing height, fee mismatch, duplicate return and conflicting fill.
- Transactional database tests for atomic terminal rebindings, external fee
  audit, replay, and refusal to borrow failed Task 8 authority.
- Native route/UI tests that preview is read-only and confirmation cannot call
  Sage's cancel method.
- Original TEST7 read-only evidence, then reviewed native proof-only recovery,
  then fresh independent Sage/database comparison before any Follow start.
