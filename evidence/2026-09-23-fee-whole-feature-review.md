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
   **Implemented:** exact pricing and hold reconstruction now use the same
   bounded prerequisite planner. Preview also discloses native-first and later
   consolidation stages. Four real worker/pricing/CLVM/ledger simulations
   cover 61/153 roots in two-sided and buy-only modes through authoritative
   confirmation and completion. Only external wallet transport/observation is
   synthetic. Related regression group: 90 passed. The existing eight-batch
   worker limit is now shared with preview; two additional regressions first
   demonstrated plans being approved above that bound. Bound/staged/worker
   regression group: 44 passed in 67.52 seconds; combined fee regression:
   318 passed in 150.43 seconds.
3. **Important: fee-budget renewal.** A refreshed preview ignores prior scope
   cancellation protection/commitments. GUI submits only the new cancellation
   estimate; declining estimates conflict with the ledger's correct
   non-decrease rule and strand reapproval. Return/disclose the protected
   minimum and cumulative required ceiling; test partial spend and falling
   estimates. Do not weaken the ledger.
   **Implemented:** retained protection and held/spent commitments are returned
   in a consistent DB snapshot; preview and UI display the cumulative minimum
   while funding compares only uncommitted spending. Confirmation submits the
   retained reserve. Seven backend and two browser cases failed first; 129
   related backend tests passed. Authoritative confirmed/no-effect renewal and
   restart/reset persistence are covered without changing ledger safety rules.
4. **Important: stationary restart recovery UI.** Non-running approved/held/
   paused work is shown on a progress screen without polling or actionable
   review/resume controls. Preserve no-auto-dispatch semantics, continue
   read-only recovery observation and gate explicit action on unresolved
   effects. Test recovery through resolution and deliberate resumption.
   **Implemented:** stopped recovery continues read-only polling and cannot
   infer completion from percentage/error while effects are unresolved. Once
   resolved, explicit review checks latest status and canonical scope/plan,
   reuses persisted choices and never auto-approves/launches. Launch now uses
   the multiplier actually previewed rather than an unrelated edited field.
   Three recovery browser and one trigger-choice regression failed first;
   status/choice/API group: 75 passed, expanded focused UI: 21 passed, broad
   Chromium: 155 passed. These passes precede the provider-message follow-up.
5. **Important: provider health evidence.** `full_node_synced=False` is accepted
   as available fee guidance, including zero. Reject unhealthy or malformed
   supplied evidence, preserve missing metadata as unknown and expose relevant
   diagnostics. Normalization and matched-quote validation are now corrected;
   preview persists exact diagnostic strings and the browser distinguishes
   missing metadata from observed zero. Adapter snapshots no longer fabricate
   absent metadata as false/zero. 29 normalization, four matched-quote, two
   persisted-preview, two adapter and two browser cases failed first; current
   network/preview/confirmation regression group: 199 passed, focused fee UI:
   16 passed. **Outage follow-up implemented:** allowlisted source/reason/time
   diagnostics now survive local-node/Coinset failure through exact/projected
   preview, HTTP/native readback and the browser. No raw exception, credential,
   URL or arbitrary provider text is forwarded. Twenty public-surface cases
   and one sanitization case failed first, then all 21 passed. Focused browser
   fee workflow now passes 24 tests including the new outage disclosure.
6. **Disclosure:** replace the unconditional five-minute completion promise
   with a per-transaction 300-second target and no completion guarantee.
   This is part of the approved fee disclosure, not a reason to change fees.
   **Implemented:** duration copy now describes a per-transaction inclusion
   target and explicitly avoids guaranteeing whole-preparation completion.

The parent independently verified findings against current code and implemented
the above corrections test-first. Broad final-source/package verification is
still required. No automatic second full-feature review is commissioned.

The pre-fix full run completed: **6,884 passed, 147 skipped, 422 subtests** in
1,122 seconds (session 40526, exit 0). It proves the `0ad637e` baseline only.
Changed-source full run is session **23219**, `fee-safety-review-full.log`;
changed-source broad Chromium run is **30297**, `fee-safety-review-e2e.log`.
The Chromium run finished with **148 passed in 99.56 seconds**, exit 0. The
default suite subsequently ended with **3 failed, 6,929 passed, 149 skipped,
422 subtests in 1,329.40 seconds**. Renewal/recovery source edits occurred during
that run, so it is intermediate evidence, not a final-source certification.

Failures (none omitted):

- `test_mutation_gate.py::test_free_port_standalone_process_defers_to_existing_durable_owner`:
  diagnostics startup timeout; stable-source rerun passed. A passing retry alone
  does not establish the timeout's cause.
- `test_task9_authoritative_terminal_policy.py::test_generation_selector_uses_bounded_indexed_queries`:
  `inspect.getsource` retrieved a different function while source lines changed
  during the run. Stable-source rerun passed (both reruns: 2 passed in 26.33s).
- `test_wallet_sage_bulk_cancel_method.py::SageTypedBatchCancelCompatibilityTests::test_fee_bearing_batch_adds_one_explicit_fee_spend_before_one_submission`:
  old synthetic fixture claimed outputs absent from its executable spends.
  The strengthened validator correctly refused it. Replaced only that fixture
  with real CAT2/native effects, retaining one-fee/one-submission assertions;
  cancellation file plus adversarial executable regressions: 19 passed in 1.48s.

## Follow-up found by final regressions: local ownership DNS latency

The frozen final run 68774 exposed a Windows resolver exception and delay in
`pid_liveness`, then resumed. A bounded independent `getfqdn()` process exceeded
15 seconds. We interrupted the suite at 36% before changing source; exit 1
without a pytest summary is incomplete, not a passing result.

Eight failing regressions covered local/physical-FQDN/remote-name and missing
OS evidence. Fixing the runtime copy alone passed 255 ownership tests but two
startup cases still timed out:

- `test_free_port_standalone_process_defers_to_existing_durable_owner`
- `test_spawned_desktop_waits_for_arbiter_before_foreign_owner_preflight`

The startup preflight had its own eager `getfqdn()` copy. Parameterizing the
same regressions across both entry points produced eight additional failures
while the runtime cases passed. Both now share a standard-library-only local
host evidence helper: exact hostname first, Windows physical configured FQDN
second, uncertainty remains fail-closed. This helper is safe before writable
application imports. No network/firewall setting or ownership guard changed.
Final ownership regression **52980 exited 0: 265 passed in 119.16 seconds**,
including both former startup timeouts without extending their deadlines.
All prior package receipts predate this correction and need a refreshed exact
snapshot/build. Final full regression is now 4916, with source/tests frozen.

**Final software verification:** run 4916 exited 0, **6,981 passed, 157 skipped,
422 subtests in 1,037.25 seconds**. Browser suite: 156 passed. Fresh Windows
build and final isolated API/Sage/recovery/fee rejection probes passed; see
`2026-09-23-review-fix-acceptance.md` for hashes and the separately corrected
smoke-harness evidence (14 tests, eight added after full-suite collection).
All corrections are saved in local code commit
`bc7203d8f1c8ce29e6bb9fab8980422c6688d0ba`; no push/main merge/release.
Native-window and real-wallet acceptance remain unverified on this candidate.

## Preserved boundaries (unchanged)

- Exact-candidate native and live trading acceptance remain separate open
  gates. Existing source runtime and installed package were not replaced.
- The broader ownership trust model for Sage's `receiving` assertion was not
  established as a separate defect; executable-to-summary destination binding
  is required without inventing an incompatible wallet-address constraint.
- No new live campaign, fee consent, offer or transaction was created.
- The `0ad637e` native test may provide diagnostic evidence but cannot make
  this candidate release-ready or suitable for new live spending.
