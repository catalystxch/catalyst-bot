# Live TEST 7 acceptance evidence — 24 September 2026

## Identity and services

- Current-candidate executable SHA-256 remains recorded as
  `703E707F74977FEE071C93B0940FBEE665446C3620782B393A72DF229C990223`.
- Sage v0.13.0 connected through the packaged first-launch flow.
- Selected fingerprint: `736588221` (TEST 7), network: mainnet.
- Selected CAT wallet: wallet ID `2`, Monkeyzoo Token (`MZ_XCH`), asset ID
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Live balances loaded: 138.472852133099 XCH and 780212.284 MZ spendable.
  Splash started and reported connected. The configured Spacescan path
  continued successfully and returned holder/activity context.

## Live start / stop and safety result

- Existing 3-buy / 3-sell, 0.1 XCH settings were reviewed and saved through
  the packaged browser UI. Existing prepared coins were verified as ready, so
  no new fee consent or wallet mutation was required for that plan.
- The operator confirmed the live start/stop action at the action boundary.
  CATalyst passed all 10 preflight checks, reconciled 0 open wallet offers,
  found no unknown offers or orphan-looking locks, and started normally.
- One complete live loop finished in 2.9 seconds with zero errors. Current
  offer-book confidence was RED (`out of range depth excluded`, `insufficient
  ask depth`, `single provider dependency`), so adaptive targets remained
  zero. CATalyst created zero buy offers and zero sell offers and logged that
  new exposure and requotes remained blocked because no attributable trusted
  price was available.
- Stop completed cleanly. Post-stop state had zero active offers, zero locked
  coins, zero unresolved operations/reservations/publications, and runtime
  safety remained allowed.

## Smart Settings and balance rejection

- Balanced Smart Settings in Follow mode failed closed because current market
  evidence was unsuitable; the form retained the existing 3/3 values.
- Loading the saved `pre-fee-live-acceptance` preset produced the expected
  unsaved 45/45 Bootstrap form. It rejected the plan: 45 sell offers required
  about 783,289 MZ, and the full 72-coin preparation plan required about
  1,443,328.718 MZ after headroom versus 780,212 available. The preset was
  discarded without saving. Reload confirmed the persisted 3/3 strategy.

## Fresh dynamic fee quote

- A temporary affordable 4-buy / 4-sell plan was saved solely to force a fresh
  Coin Prep estimate. Verification recommended re-preparation for two
  transactions and displayed the correct wallet/pair identity.
- The first estimate was marked expired at 69 seconds and blocked approval
  until Refresh. Refresh returned a current Coinset quote, 25 seconds old,
  with the default 300-second target:
  - cumulative maximum / remaining plan estimate: `0.000401997224 XCH`;
  - protected cancellation allowance: `0.0000902074 XCH`;
  - existing commitments: `0 XCH` spent and `0 XCH` held;
  - fee-coin principal: `0.05 XCH`, identified as principal, not fee spend;
  - fee funding available: `124.502663594778 XCH`;
  - evidence: one exact unsigned cost and three projected costs;
  - exact CAT prep: `0.000015034908 XCH`;
  - projected XCH prep: `0.000296754916 XCH`;
  - projected cancellation XCH: `0.000003288565 XCH` each for 1-8;
  - projected cancellation CAT: `0.00000798736 XCH` each for 1-8.
- The UI enabled `Yes, Prepare Coins (+0% headroom)` only after the fresh
  quote arrived. No approval has been recorded and no preparation transaction
  has been dispatched. The next click is a real financial action and needs
  operator confirmation of this exact displayed cumulative maximum.

## Still open

- Approve and execute the exact 4/4 Coin Prep budget above, verify exact final
  repricing/reservations/confirmation accounting, then restore and reverify the
  intended 3/3 strategy unless the operator chooses to retain 4/4.
- Live offer publication/requote/cancel/remake cannot be observed while
  attributable market confidence remains RED. The live loop proved the
  fail-closed path; it did not fabricate market evidence or bypass safety.
- Restart accounting after a real Coin Prep operation remains open.

## Focused automated regression rerun

- A fresh focused run covering all `test_coin_prep_fee_*` and `test_fee_*`
  modules plus unsigned preview, worker cancellation, split retry, cancellation
  outcomes/journal, cancel-all integration, startup recovery, and publication
  recovery completed successfully: **948 passed in 346.62 seconds**.
- After the run, the packaged UI refreshed the live Coinset estimate. The
  identity remained Sage fingerprint `736588221`, wallet `2`, MZ/XCH mainnet;
  the estimate remained current at `0.000401997224 XCH` cumulative maximum,
  with `0.0000902074 XCH` protected cancellation allowance, zero spent, zero
  held, and the same 1 exact / 3 projected evidence split.
