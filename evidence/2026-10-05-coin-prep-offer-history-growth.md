# Coin Prep live-book preflight after terminal history growth

The TEST 7 Sage wallet had 4,095 terminal offer records at the latest read-only
checkpoint. `load_sage_offer_history` has a 4,096-record hard limit. Coin Prep's
wallet-wide open-offer preflight requested completed records even though it
only uses nonterminal rows. Once the wallet accumulates more than 4,096 total
records, a complete Sage response makes that preflight fail closed before Coin
Prep can run.

A regression drives the actual Sage adapter with 4,097 cancelled records and
one active buy. It failed before the change because the open-offer snapshot was
incomplete. The preflight now requests `include_completed=False`. Sage may
ignore that filter, so the adapter first receives the complete `get_offers`
response and removes only recognized terminal rows locally. The same regression
then reports one active offer and its exact trade ID. No live wallet mutation
was performed.

Verification on the changed source:

- Regression: 1 passed after the observed pre-fix failure.
- Focused Coin Prep endpoint and mutation-gate suite: 312 passed.
- Full serial Windows backend: 7,219 passed, 224 skipped, 431 subtests passed
  in 1,454.73 seconds.
- Ruff check and format, and `git diff --check`: passed.

This correction covers the Coin Prep *live-book* preflight only. Exact terminal
offer reconciliation and quarantine proof still request completed history and
retain a separate 4,096-record source limit. An independent secondary-PC
network-blocked boundary check confirmed that 4,097 full-history rows return
`source_limit_exceeded`, leave an affected intent UNKNOWN, and trip the safety
latch. Batch-cancel proofs also require every member of the durable cohort;
filtering to one target row would weaken the proof. That broader, bounded
evidence design remains an open release blocker. The running `74da24c` package
and its stopped-profile monitor predate this source change and do not certify
it. PR #220 remains draft.
