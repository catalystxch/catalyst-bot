# TEST 7 campaign fee overrun — independent observer, 25 September 2026

Read-only observation during the 09:40 UTC heartbeat, continuing through
approximately 09:55 UTC. This receipt supersedes the earlier statement that
no live create/cancel/remake cycle had run. It does **not** certify acceptance.

## Identity, artifact and provenance

- `/api/bootstrap/status` re-read Sage identity as mainnet fingerprint
  `736588221`, CAT wallet `2`, MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- PID `81996` runs this worktree's `dist/Catalyst/Catalyst.exe`, fresh SHA-256
  `DD9971CD19890E728D32459E9CFC63C7016DE06D642BBA52D49DC65667BA20DC`.
  This is **not** the prior frozen `02F090A7...` executable. Do not transfer
  the old full-suite/build receipts to these new bytes.
- The active task **Review Catalyst work (3)** owns the live session and the
  current `bot_gui.html`, fee-browser-test and live-acceptance-document edits.
  This observer neither operated the wallet nor changed those files.
- Database observations used existing `database.py` read helpers with its
  read-only/query-only connection. No raw SQL, migration, accounting repair,
  signing, fee approval, cancellation or configuration write was performed.

## New lifecycle evidence

- Campaign `a6d5a1d32659ee250e9f7cf45bee19c4320748dd9644bf776f04fff3ea8fa2ac`,
  revision `0`, started `2026-09-25T09:16:58.710042Z`: fee cap `0.001 XCH`,
  principal caps `1 XCH / 10000 MZ`, deployment `0.1`, subsidy `0`.
- First wave: six campaign-bound intents created about 09:31 UTC, all exactly
  discovered on Dexie at `09:31:26.922161Z`; all subsequently terminal/cancelled.
- Cancel All readback reports two batches, six confirmed, zero failures and
  pending, complete at `09:39:03.715439Z`. Runtime at the initial observation
  was stopped after three loops, zero errors, zero offers and zero coin locks.
- Second wave: six new campaign-bound intents created about 09:42 UTC, all
  exactly discovered on Dexie at `09:42:14.358194Z`. Thus new creation, Dexie
  publication, authoritative cancellation and remake have durable evidence.
  That does not prove a distinct automatic repricing/requote or new fill.
- Splash emitted `InsufficientPeers` warnings. The other task records later
  publication-claim success; this observer's per-provider **discovery** rows
  remained pending. Publication claims and exact public rediscovery are not
  interchangeable. Further corroboration remains necessary for Splash.

## Confirmed release-blocking fee defect

The campaign's `fee_spent_xch` remains `"0"` and its status remains active,
despite the following two unique confirmed cancellation transactions:

| Cohort suffix | Transaction ID | Height | Members | Fee (mojos) |
| --- | --- | --- | --- | --- |
| `549f36708845ee139fae2f253c8561edcca34e6812e7977ef3b2c80dbfb361ab` | `2d15a10a372cdf7267419b3cd640be515faee5745cbe73d6c4f389c8b2ae098d` | 9341408 | 3 | 864000000 |
| `e2f3cd7ddb9c2f60f2de0926fe11e62cf285d9fb7bfa1ff4c82ce93f3e204dec` | `b1f6a533248167d94f3c8018ff07e6fc13eed719731920b6b043aac632bf2d79` | 9341404 | 3 | 864000000 |

For each member, the durable `cancel:<trade_id>` PREPARED event records reason
`manual_cancel_all` and that cohort's exact wallet fee. RECONCILED evidence
classifies it `CANCELLED_PROVEN` with `EXACT_CANCEL_RETURN_PROOF`, matching
fee and block height. Count each cohort once, **not once per member**.

- Unique cancellation spending: **1728000000 mojos = 0.001728 XCH**.
  Cancellation alone exceeds the campaign fee cap by **0.000728 XCH**.
- Coin Prep approval
  `66cb34a8c79f881cb1c2332954f9e67c61e0ba5c0b42ebf08164a061acaac096`
  separately records two confirmed operations, **8563369 mojos** spent,
  zero held/unresolved, protected cancellation **11111490 mojos** untouched.
  Its current version-2 total is **19674859 mojos**; do not confuse this
  readback with the earlier displayed approval amount recorded by the operator.
- Combined evidenced charges: **1736563369 mojos = 0.001736563369 XCH**,
  exactly matching balance movement from `138.472836570155` to
  `138.471100006786 XCH`. The cap overrun including prep is **0.000736563369 XCH**.
- These generic cancellations did not consume the protected Coin Prep ledger.
  Do not retroactively attribute unrelated operations to that scope or pretend
  the campaign counter's zero means no fees were paid.

## Root-cause trace and next gate

`bootstrap_runtime.derive_bootstrap_authoritative_evidence` retains
`previous.fee_spent_xch`; it does not derive actual charges from the fee/effect
journals. Generic `OfferManager.cancel_offers` without a `fee_approval_id`
uses `_plan_sage_bulk_cancel`, whose `_sage_bulk_cancel_fee_mojos` computes
`(20000000 + (members + 1) * 31000000) * 6` as a floor. For three members this
is 864000000 mojos. That path does not reserve against the campaign cap.
The protected Coin Prep cancellation path is separate and is not evidence
that this generic campaign cancellation path is budget-enforced.

The active test task has been notified to stop the bot without cancellation
and halt further fee-bearing tests pending reconciliation/enforcement fixes.
This observer has not itself stopped the live session; obtain a fresh runtime
readback before claiming it stopped. Do not increase a cap to conceal this
overrun. Preserve outstanding-offer authority and existing receipts.

Required before readiness: reproduce the generic campaign cancellation bypass
offline, enforce durable identity/campaign-bound aggregate caps at dispatch,
account confirmed/held/no-effect/retry/restart outcomes idempotently, preserve
cancellation allowance, cover mixed cohorts and concurrent calls, then rerun
relevant/full/browser/package verification. The post-completion UI correction
is independent and does not fix this financial safety defect.

No main merge, release, installed-package replacement or source fix was made
by this observer. Acceptance remains incomplete.

## Offline reproduction and coordination

- Added `tests/test_bootstrap_cancel_fee_budget.py` using a real disposable
  SQLite campaign/offer/cancellation journal and a no-network mocked wallet
  effect. The campaign cap is 500000000 mojos; generic two-offer Cancel All
  dispatches 678000000. The assertion that no over-cap effect may dispatch
  fails with `[678000000] != []`.
- Command: `C:\Python312\python.exe -m pytest
  tests/test_bootstrap_cancel_fee_budget.py -q`: **1 failed in 1.34s**, exit 1.
  This is intentionally RED, not fixed or accepted. Earlier harness drafts
  wrongly appeared green because their loose mock signature prevented wallet
  dispatch; correcting it to the real adapter signature produced the valid
  reproduction. No production code was changed to obtain RED.
- Ruff on the new test and `git diff --check` passed. No full-suite result is
  claimed for the new WIP. The old green suite does not cover this regression.
- The active task was sent the exact cohort receipts and the failing test;
  its new `tests/test_bootstrap_api.py` changes were observed and preserved.
  Backend ownership is being coordinated rather than concurrently editing
  the same safety path. The existing completion-UI fix is separate.
- A final GET `/api/status` was connection-refused. This proves endpoint
  unavailability, **not** that every remade offer has been cancelled or that
  the campaign is terminal. Last durable read had six remade visible offers.
  Preserve those obligations; do not submit an unbudgeted cleanup transaction.
- The existing automation remains ACTIVE with updated instructions naming
  this overrun and prohibiting further fee-bearing live tests before a fix.
  No duplicate automation or goal was created and readiness was not marked
  complete.
