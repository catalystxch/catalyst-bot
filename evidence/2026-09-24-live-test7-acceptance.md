# Live TEST 7 acceptance evidence — 24 September 2026

Latest artifact note: secondary-PC corrections were subsequently combined at
`088d9d6`. This file's live receipts remain valid for the executable identified
below; they do not certify a later build. See
`2026-09-24-combined-candidate-verification.md` for current combined-build tests,
the test-first Doctor-probe isolation correction, the recorded same-build native
acceptance and the completed 6,999-test regression run,
and the correction that Sage was running as `sage-tauri.exe` while CATalyst's
local service was unavailable. The secondary PC used a different fingerprint;
its receipts must not be relabelled TEST 7.

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

## Runtime unavailable — 24 September 2026, 13:03 UTC heartbeat

- The status and public-market GETs to localhost:5000 were both connection
  refused. A subsequent listener check found no port-5000 listener; the
  expected `Catalyst` and `sage` processes were not found. This establishes
  service unavailability, not whether shutdown was deliberate or a crash.
- Failed GETs yielded no authoritative status. Null-derived placeholder
  fields printed by the diagnostic wrapper, including offer counts, are
  discarded; they do not describe the wallet or app. The last successful
  status/fee observations remain the earlier recorded receipts.
- Worktree HEAD is `29f893d`; the intervening temporary artifact-workflow
  commits have no net tree difference from `5b54d94`. Tracked files were clean
  before this note. No app or wallet was relaunched, no setting was changed,
  and no wallet action occurred. Further local runtime observation needs the
  tested candidate and Sage reopened; the native smoke test does not need
  repeating. Live offer-cycle acceptance remains incomplete.

## Live Bootstrap lifecycle acceptance — 25 September 2026

- Relaunched the freshly rebuilt package and reverified Sage mainnet
  fingerprint `736588221`, CAT wallet ID `2`, and exact MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
  before wallet mutation. The active campaign remained revision `0` of
  `a6d5a1d32659ee250e9f7cf45bee19c4320748dd9644bf776f04fff3ea8fa2ac`:
  anchor `0.000075 XCH/MZ`, corridor `0.0000375-0.00015`, one-day expiry,
  budgets `1 XCH / 10000 MZ / 0.001 XCH fees`, subsidy disabled, 10% stage.
- Genuine GUI approval bound Coin Prep to approval
  `66cb34a8c79f881cb1c2332954f9e67c61e0ba5c0b42ebf08164a061acaac096`.
  The displayed cap was `0.000040060559 XCH`, including a protected
  `0.000011111490 XCH` cancellation allowance. Two exact operations confirmed
  for `0.000008563369 XCH` total actual fee, with 66 targets, zero held fee,
  and zero unresolved operations.
- A post-completion UI defect was reproduced: because the campaign approval
  deliberately remains `paused_budget` to retain cancellation cover, the
  browser reopened the fee-recovery view even though Coin Prep status was
  complete. Two Chromium regressions were added first and failed. The minimal
  fix gives authoritative `complete=true` / `phase=complete` priority over an
  overlapping active approval in both initial restoration and live recovery
  controls. The focused regressions then passed, the full fee browser file
  passed `26/26`, and 104 related backend/API/lifecycle tests passed.
- Fresh Windows build SHA-256:
  `DD9971CD19890E728D32459E9CFC63C7016DE06D642BBA52D49DC65667BA20DC`.
  Packaged API, Sage RPC, upgrade/publication recovery, and native
  clean/duplicate/persisted/safety launch smokes all passed. Restarting that
  exact EXE restored Coin Prep as complete and enabled Start Bot without a
  duplicate preparation transaction.
- The first live Bootstrap start created exactly six bounded offers: three
  buys totalling `0.1000 XCH` at `0.0000675`, `0.00007125`, and `0.0000735`;
  three sells totalling `1000.00 MZ` at `0.0000765`, `0.00007875`, and
  `0.0000825`. All six were exactly rediscovered by Dexie. Splash submission
  acknowledgement remained provisional: exact Splash rediscovery was pending
  and daemon observations included `InsufficientPeers`. It is not counted as
  authoritative Splash publication acceptance. RED Follow confidence did not
  suppress the explicitly bounded Bootstrap book.
- The bot was stopped, then GUI Cancel All processed the book in two balanced
  batches. CATalyst remained fail-closed with `UNRESOLVED_OPERATIONS` while
  Sage proof was pending, advanced from `0/6` to `3/6`, and completed only at
  `6/6` authoritatively terminal, zero failures. Wallet locks then read zero
  XCH and zero CAT, and runtime safety returned to allowed with zero unresolved
  operations, reservations, or publications. Subsequent audit proved that the
  dashboard invoked the generic manual cancellation path, not the campaign's
  protected approval path. The two confirmed native batches each spent
  `864000000` mojos, so this operation is defect evidence rather than a passing
  protected-cancellation acceptance result.
- The same saved settings were revalidated. Coin Prep correctly reused the
  already prepared denominations without a new preparation or approval. A
  second live start remade the exact six-offer book; the first four loops each
  completed with 3 buys / 3 sells, zero errors, zero pending cancellations,
  exact Dexie rediscovery for all six offers. Current locks are the intended
  `0.1000 XCH` and `1000.00 MZ`. CATalyst was then terminated without another
  cancellation, leaving these offers live while fee safety is repaired.
- Durable reconciliation now attributes `1728000000` cancellation mojos plus
  `8563369` Coin Prep mojos to the campaign: `0.001736563369 XCH` total against
  its displayed `0.001 XCH` campaign fee budget. The materialized campaign row
  incorrectly remained `fee_spent_xch=0`, and its Coin Prep approval still
  showed the protected allowance untouched. This is a release-blocking fee
  accounting and enforcement defect; the live create/cancel/remake gate is not
  closed.
- Focused red regressions reproduce both failures: campaign status ignored
  authoritative fee evidence, and generic Cancel All dispatched a
  `678000000`-mojo mock cancellation under a `500000000`-mojo campaign cap.
  The repair derives campaign spend from confirmed non-cancellation approval
  outcomes plus deduplicated authoritative cancellation cohorts, automatically
  binds every campaign-owned cancellation path to the latest explicit approval,
  checks the fixed campaign fee budget after exact pricing, and keeps campaign
  authority active until protected cancellation has been reserved. No further
  live fee-bearing action is permitted until full regression/package evidence
  is green and a genuine displayed recovery budget is available.

### Recovery-budget correction — 25 September 2026

- The journal-proven `0.001736563369 XCH` historical campaign spend now enters
  the exact approval scope as cumulative spent fee. The immutable original
  `0.001 XCH` campaign budget is preserved rather than silently rewritten.
- A fresh read-only preview discloses that prior spend and prices recovery
  against current unsigned CLVM cost and network guidance. Only deliberate
  confirmation creates a newer append-only approval whose displayed cumulative
  ceiling can exceed the original campaign budget.
- Exact cancellation and its atomic reservation both count the journal-only
  historical difference. The old approval remains blocked; direct and
  concurrent callers cannot reuse the missing-accounting gap.
- Red-first tests covered historical disclosure and explicit renewed-ceiling
  recovery. Current focused evidence: cancellation journal **121 passed**;
  Bootstrap/cancellation/API/lifecycle **89 passed**; approval-ledger,
  restart, confirmation and dispatch **176 passed**; Chromium fee workflow
  **26 passed**; Ruff passed.
- The app remains stopped and the second six-offer wave remains live pending a
  fresh package and genuine confirmation of the displayed recovery ceiling.
  No additional wallet effect occurred during this correction.

### Full regression and package checkpoint — 25 September 2026

- Added explicit stopped-campaign cleanup recovery: a stopped campaign with
  campaign-owned live offers may obtain a new read-only cancellation quote,
  while ordinary offer creation remains blocked. Recovery accepts only the
  single stop-induced revision increment over the frozen approved revision;
  it does not mutate the original campaign cap or create spend authority.
- Removed two whole-suite isolation hazards. Fee-estimation tests now block
  accidental Coinset access when switching to auto mode, and cancellation
  journal tests pin every lazily imported reconciliation/database dependency
  to their isolated test graph. The previously ordering-dependent proof-only
  cancellation failure was reproduced at 37%, fixed in the fixture, and then
  cleared under the complete suite order.
- Combined stopped-renewal/recovery/Bootstrap integration tests: **9 passed**.
  Complete Python suite: **7009 passed, 160 skipped, 422 subtests passed** in
  1089.53 seconds. Full Ruff check passed. Chromium E2E with `--e2e`:
  **159 passed** in 72.40 seconds.
- Fresh Windows build succeeded. The exact unpackaged working-tree executable
  is `dist/Catalyst/Catalyst.exe`, SHA-256
  `6C3B69255833CDC5D9B86318FC4E71C928EA9956F920A39D249D1F0855D675B3`.
  Packaged API, mock Sage RPC, upgrade/publication recovery, and native
  clean/duplicate/persisted/safety launch smokes all passed.
- Source base HEAD is
  `45f3df8505fb966b921df32791e8459a10d24cc1`; the candidate also contains the
  tracked working-tree corrections listed above, so this hash is provenance,
  not yet a final handoff commit identity. No merge or release occurred.
- No wallet action occurred during this checkpoint. The app remains stopped
  and the existing second-wave offers were deliberately left untouched. Live
  recovery still requires fresh TEST 7 identity verification and genuine
  confirmation of the displayed cancellation-recovery fee ceiling through the
  implemented workflow.

### Automatic-stop recovery correction and superseding package — 25 September 2026

- Live readback exposed the exact automatic-stop representation as campaign
  `status=active`, `stage=stopped`, revision `approved_revision + 1`. Recovery
  had recognized only `status=stopped`, so the read-only fee preview returned
  `FEE_PREVIEW_UNAVAILABLE` and recovery readback returned
  `FEE_APPROVAL_STALE`. Red-first regressions reproduce both failures.
- The recovery predicate now accepts this exact automatic-stop shape while
  retaining the one-revision bound, frozen plan identity and original campaign
  cap. It grants no dispatch authority and ordinary Coin Prep remains blocked.
  Focused stopped-renewal, recovery-policy and Bootstrap integration evidence:
  **11 passed**.
- Superseding complete Python suite: **7011 passed, 160 skipped, 422 subtests
  passed** in 1117.30 seconds. Full Ruff check passed. Chromium E2E with
  `--e2e`: **159 passed** in 93.04 seconds.
- A fresh Windows build completed after the old packaged process was verified
  and stopped. Exact executable: `dist/Catalyst/Catalyst.exe`; SHA-256
  `768CDE4B55B3335CB2652F10A455FB5FAAA0E4DB0ABF6FD43CBF561CFD26FD3B`.
  Packaged API, mock Sage RPC, upgrade/publication recovery, and native
  clean/duplicate/persisted/safety launch smokes all passed against this build.
- Source base HEAD is
  `c404f5082b9cd1d473b5202c16737d30891e2088`; tracked working-tree corrections
  remain uncommitted, so this remains test evidence rather than immutable final
  handoff provenance. No merge or release occurred.
- No wallet effect occurred during this correction or its automated/package
  verification. The six second-wave offers remain live and the bot remains
  stopped pending exact TEST 7 identity verification and genuine confirmation
  of the displayed recovery ceiling.

### Live protected cancellation, status repair, and final package — 25 September 2026

- The refreshed recovery quote disclosed a cumulative maximum of
  `0.001746988850 XCH`, including `0.001736563369 XCH` prior authoritative
  spend and `0.000011111490 XCH` protected cancellation allowance. The quote
  used fresh Coinset guidance for the default 300-second target. The operator
  approved this exact displayed ceiling through the implemented workflow; no
  blanket or fabricated approval record was used.
- Generic Cancel All first failed closed against the old cap with
  `FEE_CAMPAIGN_BUDGET_EXCEEDED` and produced zero effects. After the renewed
  approval and the separate explicit Cancel Offers confirmation, all six live
  offers reached authoritative terminal state in two batches: **6/6 terminal,
  0 pending, 0 failures**. Post-operation reconciliation found zero open buy
  or sell offers, zero wallet-only/stale offers, zero XCH/MZ locks, zero held
  fees and zero unresolved operations. The cancellation increased cumulative
  spend by only `0.000000402346 XCH`, to `0.001736965715 XCH`, below the
  displayed approved ceiling. The bot remained stopped.
- Restart readback exposed a reporting defect: `/api/coin-prep/status` selected
  the completed worker's older approval instead of the latest immutable
  campaign renewal. A red-first endpoint regression reproduced the mismatch.
  The endpoint now resolves the latest approval for the active Bootstrap
  campaign before materializing fee accounting. Focused post-fix verification:
  **3 passed**; broader approval/recovery group: **182 passed**; Ruff and diff
  checks passed.
- Superseding complete Python suite: **7042 passed, 165 skipped, 422 subtests
  passed** in 1821.60 seconds. Complete real-Chromium E2E: **164 passed** in
  124.07 seconds.
- A fresh Windows build completed after the exact prior packaged PID was
  verified and stopped. Exact executable: `dist/Catalyst/Catalyst.exe`;
  SHA-256
  `5B3D259964A8537D214E150F853B19B99ED6297D96A00B247F1E97BBFA07F6D4`.
  Packaged API, mock Sage RPC, upgrade/publication recovery, and native
  clean/duplicate/persisted/safety launch smokes all passed.
- Real-profile restart of that exact executable returned health `ok`, version
  `1.4.0`, zero open offers, and the correct latest approval
  `fe95e93d02ebe2b73650b61f4f590c57606766b77ab23961e228dea47328d8df`
  at version 3. Its durable accounting is total `1746988850`, spent
  `1736965715`, held `0`, remaining `10023135` mojos, `stale=false`, and zero
  unresolved operations. Sage RPC is authenticated and listening; configured
  identity remains TEST 7, CAT wallet 2 and the authorized MZ asset.
- Market publication remains legitimately fail-closed while confidence is RED
  (insufficient attributable in-range ask depth and provider independence).
  The saved pre-fee strategy still exceeds available MZ and was neither
  silently resized nor activated. No merge or release occurred.
