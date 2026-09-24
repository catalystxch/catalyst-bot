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
  quote arrived. At that pre-approval checkpoint no mutation had occurred; the
  later explicit approval, dispatch, and authoritative outcome are recorded
  below.

## Still open

- Live offer publication/requote/cancel/remake cannot be observed while
  attributable market confidence remains RED. The live loop proved the
  fail-closed path; it did not fabricate market evidence or bypass safety.

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

## Approved live Coin Prep and exact accounting

- The operator explicitly approved the refreshed `0.000401997224 XCH`
  cumulative maximum. The app recorded approval
  `cae3170fdf37da6c24627bc93d6b25d0a7d92df2eecde7443d8e4b2a0fe89a50`
  for plan `7be772c324866231b479f6a97007a885f109fbc050015b0bc7c44048ac92f9cf`.
- Existing P&L, three fills, and 2,554 historical offer rows were preserved;
  no history-reset option was selected.
- CAT batch 1 reserved and then authoritatively confirmed an exact
  `0.000015034908 XCH` fee. XCH batch 2 reserved and then authoritatively
  confirmed an exact `0.000000528036 XCH` fee. The UI remained fail-closed
  with `COIN_PREP_EFFECT_UNKNOWN` while each submitted effect was unresolved.
- Final authoritative fee state was `complete`: `0.000015562944 XCH` spent,
  zero held, zero unresolved operations, two confirmed reservations, no
  released reservations, and `0.000386434280 XCH` of the approved cap unused.
  The protected `0.000090207400 XCH` cancellation allowance was never consumed.
- Direct-final-batch-v2 preparation completed successfully with two confirmed
  batches, 66 target outputs, and visible 8/8 XCH plus 8/8 MZ trading-coin
  readiness. Wallet totals remained 138.472836570155 XCH and 780212.284 MZ;
  fee-coin/output principal was not misreported as fee spend.

## Restart, recovery, and restored strategy

- The packaged candidate shut down cleanly and restarted from the same EXE.
  Before any new wallet mutation, `/api/coin-prep/status` recovered the fee
  session as complete with `15562944` mojos spent, zero held, zero unresolved,
  and `session_completed=true`; no duplicate transaction was dispatched.
- Restarted startup reverified Sage mainnet fingerprint `736588221`, wallet
  `2`, MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
  Splash, and the configured Spacescan path.
- The temporary 4/4 settings were replaced with the intended 3-buy / 3-sell
  strategy. The app recognized the prepared 8/8 XCH and 8/8 MZ ladder as
  sufficient for 3/3 without requesting another fee approval.
- A post-restart live start passed all 10 checks, reconciled zero wallet
  offers and zero orphan locks, ran one 2.83-second loop with zero errors, and
  again created no offers because attributable market confidence was RED.
  Stop completed cleanly; authoritative `/api/status` reported
  `running=false`, zero open offers, zero locked coins, and runtime safety
  allowed with zero unresolved operations, reservations, or publications.
  The browser converged to the same STOPPED state on its subsequent status
  poll.

## Specification acceptance matrix

| Requirement group | Evidence | Result |
|---|---|---|
| Transaction-specific estimates | Strict normalization covers missing versus zero, malformed/NaN/negative/boolean values, integer bounds, matching cost/target, source provenance, original observation age, and upward Decimal rounding. Exact current unsigned costs and clearly labelled projections are exercised by focused and full regressions. | PASS |
| Freshness and providers | Quotes expire after 60 seconds without cache-age renewal. The live stale quote blocked approval until Refresh; current Coinset guidance used the 300-second target. Outage, malformed evidence, source disagreement, and manual-fee bypass attempts fail closed in tests and package probes. | PASS |
| Canonical preview and consent | HTTP/native/GUI previews are read-only and server-owned. The GUI showed wallet/pair, exact/projected counts and costs, source/age, target, retained principal, funding, editable maximum, and protected cancellation allowance. Approval is durable and scope/plan-bound. Cancel and duplicate confirmation have no unintended effects. | PASS |
| Exact dispatch enforcement | Supported direct CAT/XCH and bounded prerequisite paths rebuild and inspect unsigned effects, converge fee/cost with bounded retries, reserve the exact final fee atomically, permit only within-cap repricing, and pause unsupported or over-cap paths. Bootstrap, retry, direct API, and native bridge bypass cases are covered. | PASS |
| Protected cancellation | Preparation cannot borrow the protected allowance. Exact Sage cancellation uses its own inspected bundle and durable hold; cancellation/no-effect/recovery and insufficient-allowance behavior are covered across backend, API, native, and browser regressions. The live prep did not consume the reserve. | PASS |
| Durable accounting and recovery | Concurrency, conflicting replay, crash-before-signing, submitted/unknown, confirmed, authoritative no-effect, later approval versions, reset preservation, and restart idempotency are covered. Live restart recovered 15,562,944 mojos spent, zero held/unresolved, with no duplicate dispatch. | PASS |
| Accurate UI/API status | Projected versus exact evidence, source age, funding/principal, cumulative/remaining totals, waiting/paused/preparing/submitted/complete states, reload recovery, and actionable failures are exercised by 156 Chromium cases and focused regressions. Live `/api/coin-prep/status` agreed with the GUI and ledger. | PASS |
| Build and package | Full suite: 6,981 passed, 157 skipped, 422 subtests. Focused fee/live-acceptance selection: 948 passed. Fresh Windows EXE SHA-256 `703E707F74977FEE071C93B0940FBEE665446C3620782B393A72DF229C990223`; API/Sage/recovery/fee-denial probes and operator native clean/duplicate/persisted/safety launches passed. | PASS |
| Live TEST 7 Coin Prep | Sage mainnet fingerprint `736588221`, MZ wallet `2`, and the exact asset ID were verified. Genuine GUI approval covered `0.000401997224 XCH`; two batches confirmed for `0.000015562944 XCH`, produced 8/8 XCH and 8/8 MZ readiness, and survived restart without double accounting. | PASS |
| Live bot start/stop and fail-closed market gate | Intended 3/3 strategy was restored. Preflight, reconciliation, start, loop, stop, zero-lock and zero-unresolved checks passed before and after restart. Current attributable market confidence remains RED, so zero offers were created as designed. | PASS |
| Live create/requote/cancel/remake | Automated publication, requote, cancellation, retry and recovery coverage is green, but a live cycle cannot be honestly produced while the market gate has no attributable trusted executable price. CATalyst correctly refuses to fabricate price evidence or bypass the gate. | BLOCKED — external market evidence |

Ruling: the approved fee feature meets its own completion contract because its
live preview, consent, exact prep, accounting, restart, supported-path and
no-bypass gates are proven. The broader other-PC handoff goal remains active
because it explicitly also asks for a live create/requote/cancel/remake cycle.
Waiting for genuine non-RED market evidence is safer than altering production
confidence thresholds; if this ruling is wrong, acceptance is delayed rather
than funds being exposed under fabricated pricing authority.

## Latest read-only runtime audit

- At 24 September 2026 10:53 BST, `/api/status` still reported the intended
  Sage/MZ identity, `running=false`, 8 prepared XCH and 8 prepared CAT trading
  coins, zero locked coins, zero open offers, zero pending cancellations, zero
  unresolved operations/reservations/publications, and runtime safety allowed.
- The latest loop evidence still said `No attributable trusted offer-book price
  is available; new exposure and requotes remain blocked`. This is the only
  outstanding live-cycle gate, not a missing permission or fee-consent gate.
- The operator has now authorized acceptance of displayed fee prices during
  continued testing as well as start/stop, Coin Prep, Smart Settings,
  cancellation, requoting and offer remake actions. CATalyst's plan-bound
  recorded caps and safety checks remain mandatory.

## Fresh market-gate retry — 24 September 2026 10:59 BST

- Immediately before the authorized start, the GUI showed Sage fingerprint
  `736588221`, MZ wallet ID `2`, the expected asset, 8/8 prepared trade coins,
  and zero active offers or locked coins. Startup reconciled the wallet to zero
  open/unknown offers and passed the effect-safety checks.
- Coinset's optional early-fill lookup timed out during startup. CATalyst
  classified this as one non-critical service failure and retained wallet-RPC
  fill detection; it did not weaken price or transaction authority.
- A fresh live cycle replaced the expired confidence snapshot. Dexie evidence
  was current, but confidence remained RED because out-of-range depth was
  excluded, ask-side independent depth remained insufficient, and only one
  provider supplied usable price evidence. Splash had an empty offer set and
  the other evidence sources supplied no current independent executable price.
- Two loops completed with zero errors, zero buy/sell offers, zero XCH/CAT
  locks, and no wallet mutation. The bot was then stopped through the GUI.
  Authoritative `/api/status` confirmed `running=false`, zero pending
  cancellations, zero unresolved operations/reservations/publications, and
  `runtime_safety.allowed=true`.
- Result: the live offer-cycle gate remains externally blocked by genuine
  market evidence after an active retry. Permission, wallet readiness, fee
  consent, application startup, and Coin Prep are not the blocker.

## Blocked-state audit — 24 September 2026 11:00 BST

- A third consecutive goal audit re-read authoritative `/api/status` after the
  fresh cycle. The candidate remained stopped on Sage/MZ wallet `2` with the
  expected asset, two completed loops, zero errors, zero offers, zero XCH/CAT
  locks, zero pending cancellations, and zero unresolved operations,
  reservations, or publication claims. Runtime safety remained allowed.
- The latest authoritative market log still stated: `No attributable trusted
  offer-book price is available; new exposure and requotes remain blocked`.
  There is no remaining independent test or code change that can create honest
  live create/requote/cancel/remake evidence without an external market-state
  change. The active goal is therefore blocked, not complete; all completed
  fee-prep and package evidence remains valid and no safety gate was weakened.

## Read-only receipt reconciliation — 24 September 2026 12:03 BST

- Re-read the new native/operator and live acceptance receipts rather than
  treating the earlier pending-operator checkpoint as current. Native success
  remains operator-reported; it was not independently rerun in this audit.
- The process listening on localhost:5000 was PID 72524, running the exact
  `candidate-review-fixes-dns-20260923/dist/Catalyst/Catalyst.exe`. A fresh hash
  matched `703E707F74977FEE071C93B0940FBEE665446C3620782B393A72DF229C990223`.
- Fresh GETs of `/api/status` and `/api/coin-prep/status` independently
  corroborated the recorded completed fee session: approval `cae3170f...`,
  `15562944` mojos spent, two confirmed reservations, zero held/unresolved,
  `session_completed=true`, and `dispatch_authorized=false`. Protected
  cancellation remains `90207400` mojos; unused total budget is `386434280`.
- Current status reported stopped, two loops and zero errors, no active buy
  or sell offers, no locked XCH/CAT coins, no pending cancellations, and zero
  runtime safety blockers. Selected MZ asset and CAT wallet ID 2 match the
  target. The public fingerprint is hashed, so this read alone is not a new
  full Sage identity attestation. No wallet action was attempted.
- `/api/market/confidence` at `2026-09-24T12:03:06.592046+01:00` returned RED,
  `data_valid=false`, and all creation/requote/exposure permissions false.
  Its underlying assessment is from `2026-09-24T09:59:42.218421Z`, with the
  recorded depth/provider reasons plus expired snapshot/evidence flags.
  This confirms the current app gate, not a fresh external market survey;
  stopped-runtime observations cannot prove the market has not changed.
- The registered goal remains blocked, not complete. Native-result requests
  must not be repeated. Only live offer lifecycle acceptance remains open;
  no strategy/consent change, bot restart, transaction, push, merge or release
  was performed during this reconciliation.

## Public-book refresh without trading — 24 September 2026 13:05 BST

- Inspected `/api/market/intel` and its order-book refresh path, then used
  that existing GET endpoint while the bot remained stopped. It returned a
  0.7-second-old book, six refreshes and zero book errors. Public display
  source was `dexie_v3_orderbook`, best bid `0.00004` and ask `0.00011` XCH/MZ.
  Its aggregate depth is not independently attributable eligible depth and
  must not be used as authority to trade or replace the confidence policy.
- The subsequent confidence read still denied creation/requotes: its policy
  assessment remained the expired `2026-09-24T09:59:42.218421Z` snapshot. The
  public-book refresh does not run or approve a new trading cycle.
- Status remained stopped, two loops/zero errors, zero locks, zero runtime
  blockers, and no own offers. Fee status stayed complete with `15562944`
  mojos spent, two confirmations and zero held/unresolved. No wallet action,
  settings change, fee approval or bot start was performed. This establishes
  a read-only monitoring path, not a passed live offer-cycle gate.
