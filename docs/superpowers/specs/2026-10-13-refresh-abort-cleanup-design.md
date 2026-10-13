# Confirmed refresh cancellation with an unpublished child

Status: design for a **separate recovery implementation**. PR #268 prevents a
new parent cancellation in this state; it does not repair the already submitted
TEST 7 cancellation. The live wallet remains fenced while this design is
implemented and reviewed.

## Incident and operator intent

The TEST 7 operator pressed Cancel All after stopping the bot. The first sell
parent's cancellation is confirmed on chain, and its selected MZ coin has an
exact same-amount return in the connected wallet. Its replacement child is
still Sage-active but only `created` in CATalyst. Its Dexie outbox row was
queued without an attempt; Splash recorded local dispatch but no reciprocal
peer receipt. Another buy remains Sage-active. The current safety latch names
the submitted parent cancellation.

The operator's requested outcome is an empty wallet offer book with exact
terminal and fee accounting. Publishing the child merely to satisfy a refresh
coverage rule would increase exposure contrary to Cancel All.

## Required separation of facts

1. **Chain outcome:** exact Task 8 cancellation request, transaction/spend,
   selected inputs, confirmed height, and owned return coin prove the parent
   cancelled. Record this fact once through Task 9's authoritative terminal
   journal, coin rebinding, and legacy offer projection.
2. **Market coverage:** the child remains `created` with its original Sage
   trade and offer fingerprint. Its queued Dexie row and Splash local dispatch
   are not evidence of peer visibility. Do not set `first_visible_at`, mark it
   `visible`, or commit Task 11's successful refresh lineage.
3. **Trading authority:** a durable abort/cleanup fence must remain from the
   moment the exceptional parent terminal result is recorded until all exact
   cleanup targets are terminal. The bot, Coin Prep, creation, replacement and
   publication stay disabled throughout. An app restart cannot forget it.
4. **Cleanup authority:** only exact already-live offer IDs in the operator's
   wallet-wide Cancel All scope may be cancelled. Each cancellation uses the
   normal Task 8 journal, wallet identity, owned mutation lease, fee approval,
   Sage preflight and Task 9 terminal proof. The confirmed parent is never
   submitted again. No generic latch bypass may issue wallet or network work.
5. **Exit:** suppress only still-queued publication rows for offers proven
   terminal, prove zero pending and live Sage offers, close the cleanup fence,
   and retain an explicit `aborted` lineage record distinct from a successful
   Task 11 refresh. New campaign eligibility must not mistake the aborted pair
   for a successfully covered refresh. Any ambiguity keeps the fence closed.

## Entry and atomicity

### Blocked-profile startup entry

The submitted parent cancellation already trips the normal startup gate.
The recovery UI therefore cannot depend on an ordinary `allowed` startup or
on the normal BotLoop creation path. A separate restricted startup entry must
first validate the exact single parent/child candidate, existing cancellation
blocker, stopped campaign, wallet binding and complete Sage read. It must not
run legacy reconciliation on that parent: the normal registry rule rejects an
unpublished child and would add a second denial blocker before the scoped
abort can be created. A second blocker or changed evidence leaves the normal
read-only diagnostics screen in place.

Only after those checks may this process acquire and renew an inactive lease
for restricted recovery. The durable latch stays tripped, the generic
mutation gate remains blocked, and no trading BotLoop or publication worker
starts. The restricted native view exposes the preview and exact abort stages;
every wallet effect still uses the one-target cleanup permit and fresh fee,
identity, Sage-book and lease checks. A crash or failed preflight releases no
fence and returns to read-only diagnostics. Normal startup is retried only
after the abort is durably complete and its blocker is released.

- Entry requires a stopped bot and campaign, an owned renewing lease, the
  expected latch generation with exactly the named submitted cancel blocker,
  reciprocal parent/child binding, and a complete same-wallet/network Sage
  snapshot. It refuses unknown wallet effects, a pending transaction, an
  in-flight publication dispatch, or a mismatched parent/child trade, asset,
  side, tier, slot, generation, fingerprint or selected coin.
- A durable abort identity is derived from the exact parent/child intent IDs,
  Task 8 operation ID and observed latch generation. Creating or replaying the
  abort record is compare-and-set and cannot alter its target list. Its own
  blocker is added before the parent Task 8 blocker can be closed. It may be
  committed in an earlier transaction while the existing parent blocker still
  holds; there must be no gap where a queued publication or new wallet
  mutation can run.
- A crash between any two stages replays the same proof and never resubmits
  a confirmed cancellation, issues an extra publication, enlarges cleanup
  scope, or silently clears the abort fence.

## Refusal and observation rules

- A local Splash acknowledgement is diagnostic only. A Dexie HTTP 404 or
  expired discovery deadline is not proof that no peer ever saw an offer.
  On-chain cancellation of the child is the cleanup outcome even if a stale
  marketplace listing later appears.
- Fresh Sage authority can contradict the retained snapshot. A fill, changed
  input ownership, a newly pending transaction, an unknown additional offer,
  ambiguous publication dispatch, fee-budget mismatch, or lease/generation
  change halts cleanup for operator review. It never falls back to SQL edits,
  arbitrary fee use, an out-of-band Dexie post, or a broad gate release.
- The UI must name the exact stage and show that no second cancellation was
  submitted when proof or authority is incomplete. It cannot claim all offers
  cancelled from a stale CATalyst counter; the final state requires Sage and
  database reconciliation.

## Verification

Use disposable DBs and mock Sage for red/green tests of the exact incident,
normal visible-child refresh unchanged, wrong wallet/lineage/lease/latch
generation, additional blocker, pending or in-flight effect, failed no-effect
child, publication suppression only after terminal proof, crash/replay after
each boundary, fee and selected-coin identity, and an unknown extra live
offer. Verify that Task 11 continues to reject the unpublished child and that
start, Coin Prep, offer creation and publication all remain fenced during
cleanup. Then run the relevant backend and GUI suites, full Windows suite,
package/Defender checks, independent review, and an isolated packaged replay
before considering an original-profile handoff. The original TEST 7 wallet
must remain unchanged until those gates pass and the operator sees the final
native action under the computer-use rules.
