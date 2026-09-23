# Whole-feature review of `0ad637e`

Reviewed range: `89027426d9390492c2e57a9a1e7c2b70336dc48a` to
`0ad637e84a47db7d94aeb936a895b734f5df7ec8`. Review was read-only; no wallet
actions or duplicate full-suite run. These findings supersede any inference
that the previous candidate's green tests established software readiness.

## Findings and dispositions

1. **Critical: cancellation executable/summary disagreement.** The shared
   cancellation validator checks summary arithmetic and removal IDs but does
   not bind executed additions, destinations, assets and fees. Cost-only CLVM
   execution is not that proof. A 1,000-mojo input whose executable returns
   900 can be sealed with a summary claiming 1,000 returned and zero fee.
   Reproduced in real-module tests: six builder cases (changed amount or
   destination in cancellation or fee components), plus unsealed and
   correctly-digested sealed submission reached the unsafe boundary. Eight
   red tests; three native/CAT positive characterizations passed. The common
   validator now binds actual executable effects, and the ordinary path uses
   that same validator. Cancellation/ledger regression group: 169 passed.
   One intermediate test overmocked the submit helper and rejected even a
   refusal object; corrected it to keep the real helper and block only actual
   external RPCs. Do not require output
   address equality with input address: legitimate rotation must work.
2. **Important: fragmented-XCH staged workflow.** Preview discloses future
   bounded 50-to-1 prerequisites after CAT prep, but both exact pricing and
   final hold reconstruction leave `allow_bounded_prerequisite=False`.
   Approved 61/153-root scenarios can fail after CAT fees are spent. Need a
   real CAT -> prerequisite -> final XCH integration regression and consistent
   pricing/hold/stage support, or refusal before any initial spending.
3. **Important: fee-budget renewal.** A refreshed preview ignores prior scope
   cancellation protection/commitments. GUI submits only the new cancellation
   estimate; declining estimates conflict with the ledger's correct
   non-decrease rule and strand reapproval. Return/disclose the protected
   minimum and cumulative required ceiling; test partial spend and falling
   estimates. Do not weaken the ledger.
4. **Important: stationary restart recovery UI.** Non-running approved/held/
   paused work is shown on a progress screen without polling or actionable
   review/resume controls. Preserve no-auto-dispatch semantics, continue
   read-only recovery observation and gate explicit action on unresolved
   effects. Test recovery through resolution and deliberate resumption.
5. **Important: provider health evidence.** `full_node_synced=False` is accepted
   as available fee guidance, including zero. Reject unhealthy or malformed
   supplied evidence, preserve missing metadata as unknown and expose relevant
   diagnostics. Normalization and matched-quote validation are now corrected;
   preview persists exact diagnostic strings and the browser distinguishes
   missing metadata from observed zero. Adapter snapshots no longer fabricate
   absent metadata as false/zero. 29 normalization, four matched-quote, two
   persisted-preview, two adapter and two browser cases failed first; current
   network/preview/confirmation regression group: 199 passed, focused fee UI:
   16 passed. Provider-outage reason propagation through the public runtime
   preview still needs explicit follow-up; do not infer it from these passes.
6. **Disclosure:** replace the unconditional five-minute completion promise
   with a per-transaction 300-second target and no completion guarantee.
   This is part of the approved fee disclosure, not a reason to change fees.

The parent independently verified findings 1, 2 and 5 against current code;
findings 2–4 and the duration copy still require implementation/regression
work. No automatic second full-feature review is commissioned.

The pre-fix full run completed: **6,884 passed, 147 skipped, 422 subtests** in
1,122 seconds (session 40526, exit 0). It proves the `0ad637e` baseline only.
Changed-source full run is session **23219**, `fee-safety-review-full.log`;
changed-source broad Chromium run is **30297**, `fee-safety-review-e2e.log`.
The Chromium run finished with **148 passed in 99.56 seconds**, exit 0. The
default suite remains running; do not substitute baseline results.

## Preserved boundaries

- Exact-candidate native and live trading acceptance remain separate open
  gates. Existing source runtime and installed package were not replaced.
- The broader ownership trust model for Sage's `receiving` assertion was not
  established as a separate defect; executable-to-summary destination binding
  is required without inventing an incompatible wallet-address constraint.
- No new live campaign, fee consent, offer or transaction was created.
- The `0ad637e` native test may provide diagnostic evidence but cannot make
  this candidate release-ready or suitable for new live spending.
