# TEST 7 campaign fee overrun — independent observer, 25 September 2026

## Latest observer checkpoint — 13:45–13:54 UTC

**The original automatic-stop cases now pass; two composed recovery paths are
newly RED. Acceptance remains incomplete.** This observer made no live wallet
or runtime changes. Review Catalyst work (3) still owns production/UI repair
and the live session; both new reproductions were sent there before checkpointing.

### Fresh independent results

- The owner integrated the previous automatic-stop fixture/tests into
  `tests/test_bootstrap_stopped_fee_renewal.py` (the temporary standalone file
  is no longer needed). Campaign bypass, real-policy recovery, stopped renewal
  and Bootstrap integration now pass **12 tests in 10.87s**, exit 0:
  `C:\Python312\python.exe -m pytest tests/test_bootstrap_cancel_fee_budget.py
  tests/test_bootstrap_fee_recovery_policy.py
  tests/test_bootstrap_stopped_fee_renewal.py
  tests/test_coin_prep_fee_bootstrap_integration.py -q --tb=short`.
- New `tests/test_bootstrap_recovery_stop_sequence.py` composes a real automatic
  policy stop at revision 1 with the real explicit-stop database transition and
  a connection restart. The unchanged campaign economics now have revision 2.
  The real fee-preview endpoint returns **409 / FEE_PREP_CAMPAIGN_UNAVAILABLE**
  instead of a read-only new-consent quote: **1 failed in 1.81s**, exit 1.
  Consent/hold/effect counts remain unchanged. The one-step `approved + 1`
  exception is insufficient for this reachable sequence. This is a request to
  review new cleanup consent, not permission to execute stale approval across
  arbitrary economic/revision changes. Ordinary prep must remain refused.
- New `tests/e2e/test_campaign_cancel_fee_recovery.py` opens the actual GUI
  cancellation-budget recovery review and clicks its real confirmation button
  in Chromium. After one mocked successful approval, the GUI requests
  **`/api/coin-prep/trigger`**, even though the review describes cancellation
  recovery. The no-new-prep-dispatch assertion is RED: **1 failed in 1.83s**,
  exit 1. All financial responses are mocked; no wallet is contacted. Existing
  cancellation-error browser tests stopped at opening the review, so did not
  cover this next action. The review uses the ordinary `startCoinPrepFromModal`
  handler without a cancellation-only operation context. The new test is a
  bounded dispatch regression, not proof that the eventual cancellation retry
  or settlement works. Test setup import/overlay issues were corrected before
  obtaining this behavioral RED; those setup failures are not product evidence.

Both new files are left as shared WIP for the repair owner to integrate with its
untracked `bootstrap_fee_fixture.py`. The observer does not commit or overwrite
the owner's production changes or fixture. No duplicate full suite/build was
started while that task was active.

### Artifact/version boundary

At 13:54 UTC the current EXE hashes to
`FCD403F9EA294D2495FCB3674F33508DEB83EA1A10285323A4C852B956986AC0`
(file modified 13:40:28 UTC). Source and bundled HTML both hash to
`91C546EB3936B851FEB8E4F6CBFE5C9605A383ECD2E06D3C9B48F675C2BED26F`;
observed runtime source hashes to
`916F604954F909AC9EA6F7614E9F542B4DDFBF18356A0D77CEC595C960D864B2`.
Base HEAD is `c404f5082b9cd1d473b5202c16737d30891e2088` plus shared repair WIP,
not an immutable committed candidate.

The owner's latest written automatic-stop receipt reports 7011 backend passes,
160 skips, 422 subtests, 159 Chromium passes, and package/native smokes for
EXE `768CDE4B55B3335CB2652F10A455FB5FAAA0E4DB0ABF6FD43CBF561CFD26FD3B`.
That is **not the current FCD403 artifact**. Exact source/log/package provenance
was requested from the owner; do not relabel the older full/native receipt or
the independent 6C3B package checks below as verification of FCD403.

Logs under `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/`:

| Log | SHA-256 |
| --- | --- |
| `observer-auto-stop-green-20260925-1345.log` | `94E66B2929E205864DD9070808655D06511C73A72A8C2DF516620141D6666DBE` |
| `observer-stop-sequence-red-20260925-1345.log` | `424109FE08E4C3EE5A831C666D89CB262B1C65DA16B143382F313E57324C2977` |
| `observer-cancel-review-red-20260925-1355.log` | `80687E3EAE6FAFCB9E9CD1D8BC8089321AD32FC9B3539B1A307CFC0E68F82F17` |

The new backend and browser test SHA-256 values are respectively
`695C27483D4444E2574D25840AD7C056607E3BC65A187F7C25BC3918ED2BB157` and
`D7EE03130EBC990C6C33D93F61CD03D79FC6B82EAD94B0B0E837DF44A3330AC8`.
Reproduction commands:

```powershell
C:\Python312\python.exe -m pytest tests/test_bootstrap_recovery_stop_sequence.py -q --tb=short
C:\Python312\python.exe -m pytest tests/e2e/test_campaign_cancel_fee_recovery.py --e2e -q --tb=short
```

Ruff on both new test files and `git diff --check` passed after the reproductions.

Historical **1736563369 mojos** spent against the original **0.001 XCH** cap
remains unchanged evidence. No new consent, cap increase, fee-bearing live test,
strategy change, installed-package replacement, main merge or release occurred
in this observer run. Post-fix displayed recovery consent, exact capped cleanup,
authoritative settlement/restart, remaining requote and market/publication gates
are still open. The goal is not complete and the automation remains enabled.

## Prior observer checkpoint — 12:54–12:58 UTC

**New automatic-stop recovery boundary is RED; acceptance remains blocked.**
This is distinct from the explicit/manual stop cases that passed below.

Read-only inspection found the owner's new EXE already running as PID 19624,
started at 12:27:58 UTC, listening on localhost:5000. This observer did not
launch, stop or alter that live instance. GET `/api/bootstrap/status` freshly
reported Sage mainnet TEST 7 fingerprint **736588221**, MZ wallet **2**, and the
expected `b8edcc6a...dbec105` asset. The new package reports campaign fees
correctly: **0.001736563369 XCH**, with original **0.001 XCH** cap unchanged.
GET `/api/status` reported bot stopped, one loop, zero errors, six open offers
(three buys/three sells), zero pending cancellation and zero runtime blockers.
These are app readbacks, not fresh independent chain proof for all six offers.

The campaign now has **status=active, stage=stopped, revision=1**. Its unchanged
version-2 approval still binds plan/request revision **0**, with spent
**1736563369**, held **0**, remaining **-1716888510** mojos,
`state=paused_budget`, and `dispatch_authorized=false`. No new consent exists.

- New `tests/test_bootstrap_automatic_stop_fee_recovery.py` uses the real policy
  evaluator, `plan_bootstrap_state_update` and transactional
  `update_bootstrap_campaign_state`, then closes/reopens the isolated SQLite
  connection. An authoritative fee overrun produces precisely this active /
  stopped-stage / incremented-revision state. The ordinary prep readback still
  refuses, as required.
- The actual fee-preview API then returns **503 / FEE_PREVIEW_UNAVAILABLE**,
  rather than a read-only recovery quote. Explicit
  `allow_campaign_fee_recovery=True` readback separately raises
  **FEE_APPROVAL_STALE**. Both tests fail at these expected boundaries:
  **2 failed in 1.97s**, exit 1. No new consent/hold or wallet effect was created.
- Root cause: the new recovery fallback and one-step revision exception only
  recognize `status=stopped`. Automatic policy materialization advances the
  revision and sets the stage to stopped **without changing active status**.
  Do not repair this by ignoring arbitrary revision/economic changes or
  enabling ordinary preparation/creation under the overrun.
- Command: `C:\Python312\python.exe -m pytest
  tests/test_bootstrap_automatic_stop_fee_recovery.py -q --tb=short`.
  Log: `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/observer-automatic-stop-recovery-red-20260925.log`,
  SHA-256 `014E61362FCC62586C9BE48FB6E05694ECBF591B0CBCB00B6058B5FB34B1F2FD`.
  Test SHA-256 `814B90C503976BD8CFEC55F23ADEC9B248EBF1BDE5BDA0C6290D2C3A989C3708`.
  Ruff on the new test and `git diff --check` passed.
- The test is deliberately left as shared WIP for the repair owner to include
  alongside its required untracked `bootstrap_fee_fixture.py`; this observer
  does not commit the owner's fixture or production changes. The owner was
  sent the exact live readbacks, two failing cases and root-cause trace.

The earlier full-suite/build receipts do not cover this new regression.
No further fee-bearing live tests, release or readiness claim. Preserve the
six outstanding obligations, historical overrun, original budget and genuine
new-consent requirement. This observer made only read-only live GETs and
isolated offline tests, with no live wallet transaction or configuration change.

## Prior observer checkpoint — 12:43–12:53 UTC

The accounting/cancellation owner, **Review Catalyst work (3)**, has repaired
both recovery boundaries reproduced below. Fresh independent verification of
the shared working tree now passes. This supersedes the earlier RED status,
not the historical overrun or the unfinished live acceptance gates.

- Original generic-cap bypass, real-policy overrun recovery, stopped-campaign
  renewal (spent below and exactly at cap), and Bootstrap integration:
  **10 passed in 7.55s**, exit 0. Command: `C:\Python312\python.exe -m pytest
  tests/test_bootstrap_cancel_fee_budget.py
  tests/test_bootstrap_fee_recovery_policy.py
  tests/test_bootstrap_stopped_fee_renewal.py
  tests/test_coin_prep_fee_bootstrap_integration.py -q --tb=short`.
- Exact protected cancellation, ledger, authoritative recovery, atomic dispatch
  holds and cancellation journal: **196 passed in 111.45s**, exit 0. Command:
  `C:\Python312\python.exe -m pytest tests/test_coin_prep_fee_cancellation.py
  tests/test_fee_approval_ledger.py tests/test_fee_approval_recovery.py
  tests/test_coin_prep_fee_dispatch_hold.py tests/test_offer_cancel_journal.py
  -q --tb=short`. This includes concurrency, no-effect, duplicate and restart
  cases; it is not a rerun of the entire backend suite.
- Actual Chromium fee-workflow regression suite: **27 passed in 15.15s**,
  exit 0. Command: `C:\Python312\python.exe -m pytest
  tests/e2e/test_coin_prep_fee_approval.py --e2e -q --tb=short`. The fixture uses
  isolated test data and mocked financial responses, not the live wallet.
- The new `dist/Catalyst/Catalyst.exe` independently passed all three existing
  package probes with `--exe` pointing to that exact absolute path:
  `scripts/packaged_api_smoke.py` (nine API checks),
  `scripts/packaged_sage_rpc_smoke.py` (synthetic mTLS wallet), and
  `scripts/packaged_upgrade_publication_recovery_smoke.py`. Each exited 0.
  These use disposable profiles and loopback mock services; they do not prove
  a live campaign cancellation or the native window workflow.

### Exact observed provenance

- Branch `codex/coin-prep-fee-approval`, base HEAD
  `45f3df8505fb966b921df32791e8459a10d24cc1` **plus the owner's uncommitted
  repair**. The base commit alone is not the tested source. In particular,
  `tests/bootstrap_fee_fixture.py` remains an untracked required fixture.
- EXE SHA-256:
  `6C3B69255833CDC5D9B86318FC4E71C928EA9956F920A39D249D1F0855D675B3`.
- Source and bundled `bot_gui.html` both hash to
  `F05417633E035762CB4094A8C54F011826217E2E72335C314F44535136275E28`.
- Observed `coin_prep_fee_runtime.py` SHA-256:
  `EB4CC423A89731D8C12707EE8DB31E1A942201989202EB60F731408C74D1C42C`;
  `coin_prep_fee_cancellation.py`:
  `B98A5EBE9E647196888DBC2A583C8336243B3D12F167153873BDE48AC201DCC3`;
  `database.py`:
  `EA2A77A0808B7D9D3BCD93C69D58B85A4B1DB0B5FBFD8F51AE8B2826956C50D0`.

Logs remain under `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/`:

| Log | SHA-256 |
| --- | --- |
| `observer-recovery-green-20260925.log` | `F83C34014C28E7285B528A63D93EBE225B73E6B8260252735A0BD22AE56FECF3` |
| `observer-ledger-cancel-20260925.log` | `5CA0131769A0A0931767805A4F9D8921AE851773FC66606161221CCB20502782` |
| `observer-browser-fee-20260925.log` | `8417274BC9DA740ACCF151469EF6518C3726BF0B3075611A20E384EFEA1DE1C2` |
| `observer-package-api-20260925.log` | `037180AE72CB6968B24A4F9719E9A5644B6AA03656F45164F49C6405F82FCFD9` |
| `observer-package-sage-20260925.log` | `3C6D138DBE55C8BEAB1953D15458AF883C9AB2F1837086521D7EDAEF511BFD69` |
| `observer-package-upgrade-20260925.log` | `FA6D575A8134751BA4310D0E2A5C3BFC2F218A84D664387FE5132BB48A67AF7B` |

### Still open — do not promote to complete

The owner's `2026-09-24-live-test7-acceptance.md` now reports **7009 backend
passes, 160 skips, 422 subtests**, **159 Chromium passes**, a successful new
Windows build, and native clean/duplicate/persisted/safety smokes. Those are
owner-reported receipts: this observer has requested the exact supporting log
paths and final immutable source/package provenance, and has not independently
rerun or relabelled those complete-suite/native results. No duplicate full build
or full suite was started. All independent jobs above have finished.

Live cancellation recovery under a genuinely confirmed displayed cumulative
budget, authoritative settlement and post-fix restart accounting remain open,
as do the remaining live requote/market/publication acceptance gates. Last
durable evidence retains six second-wave offers; no current chain state or
offer disappearance is inferred from an unavailable app. Before any live
effect, reverify TEST 7 identity and coordinate with the live-session owner.
The original **0.001736563369 XCH** spend against **0.001 XCH** remains visible;
no historical cap or record was rewritten and no fee consent was manufactured.

This observer changed no production code, live profile, strategy, reserve or
installed package and performed no live wallet action. The other task's entire
WIP is preserved. No merge/release or readiness/completion claim; the automation
remains active for the unfinished gates.

## Prior observer checkpoint — 11:42–11:48 UTC

The other task's uncommitted repair now passes the prior real-policy overrun
recovery regression, including read-only preview after a stop and rejection of
ordinary preparation after an overrun. Independent command:
`python -m pytest tests/test_bootstrap_cancel_fee_budget.py
tests/test_bootstrap_fee_recovery_policy.py
tests/test_coin_prep_fee_bootstrap_integration.py -q --tb=short`:
**8 passed in 8.03s**, exit 0. This is focused source verification, not a new
Windows-package or live-wallet acceptance receipt.

A further recovery boundary remains RED:

- New `tests/test_bootstrap_stopped_fee_renewal.py` persists a genuine isolated
  campaign-owned created intent and trade binding, checks the campaign's
  outstanding trade list, and stops the campaign through the database API.
  The campaign cap is 10000000000 mojos; the two cases have authoritative spend
  **0** and **10000000000** respectively. A new 1000-mojo network quote exceeds
  the existing small explicit approval, so cleanup needs renewed consent even
  without a prior campaign overrun.
- Real `_active_bootstrap_coin_prep_context` returns no active creation context,
  and ordinary approved-prep readback correctly rejects the stopped campaign.
  The actual POST `/api/coin-prep/fee-preview` then returns
  **409 / FEE_PREP_CAMPAIGN_UNAVAILABLE** in both cases. The new fallback only
  recognizes a stopped campaign when spent is strictly greater than its cap;
  it does not handle ordinary budget-refusal/stop cleanup below or at the cap.
- No new consent, fee hold, prep operation or wallet effect claim was created.
  Required behavior is a truthful read-only recovery preview with creation
  still stopped and the original cap unchanged—not authority to spend without
  a fresh displayed approval.
- Focused reproduction: **2 failed in 2.78s**, exit 1, at the expected HTTP
  409-vs-200 assertion. Log:
  `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/observer-stopped-renewal-red.log`.
  An earlier two-case run before adding the outstanding intent also failed;
  the strengthened fixture is the authoritative reproduction. Ruff for the
  new file and `git diff --check` passed.
- Observed runtime SHA-256:
  `A9FDC5955B7E053F3A39D940D7AC92EA698ED45982636E65F550E863FCCDBE0D`.
  Regression SHA-256:
  `C88F25768B95FA8B77C21AF8868ECEE0F1A67B6FCC9D5CAD7EF19F73D218DE2F`.
  Production remains shared WIP owned by **Review Catalyst work (3)**. The
  owner received the exact failing cases and root-cause trace. This observer
  did not modify or commit that task's production/UI/fixture changes.

No live wallet action, package replacement, cap increase, full-suite rerun,
merge or release was performed by this observer. The historical overrun is
unchanged evidence. Post-fix full/backend/browser/native/Windows verification
and remaining live recovery/requote gates are still unfinished; readiness and
the persistent goal remain incomplete.

## Prior observer checkpoint — 10:41–10:50 UTC

The historical overrun below remains an actual overrun, not erased by the
in-progress repair. **Review Catalyst work (3)** owns the production fix and
live session in this same worktree. This observer changed only its own new
regression and this receipt; no live wallet action or package replacement.

- Independent focused rerun of `test_bootstrap_cancel_fee_budget.py`,
  `test_coin_prep_fee_bootstrap_integration.py` and `test_bootstrap_api.py`:
  **18 passed in 10.22s**, exit 0. The original unapproved generic-cancellation
  bypass test is now green against the other task's uncommitted fix. That is
  not certification of every atomic dispatch/recovery path.
- Read-only inspection of the real database through the new WIP helpers now
  derives **1736563369 mojos** and reports campaign `fee_spent_xch` as
  **0.001736563369**, not zero. Original cap remains **0.001 XCH**, revision 0.
  Current approval `66cb34a8...` remains version 2, total **19674859**, held 0,
  remaining **-1716888510**. This is source-helper readback, not proof that a
  rebuilt packaged runtime has launched or that historical records were edited.
- New RED `tests/test_bootstrap_fee_recovery_policy.py` preserves the **real**
  `_active_bootstrap_coin_prep_context`. Existing recovery tests replaced that
  function with a fixed recipe and therefore missed its policy precondition.
  The fixture verifies valid identity, dates and balances before injecting
  authoritative spend of 10000000010 against a 10000000000-mojo campaign cap.
  Real creation policy correctly refuses with
  `bootstrap_coin_prep_not_authorized:fee_reserve`. The actual fee-preview API
  then returns **503 / FEE_PREVIEW_UNAVAILABLE**, preventing the existing
  renewal workflow from displaying its read-only recovery quote.
- The test asserts no new consent, fee hold, operation or wallet effect claim
  was created. Its required recovery preview must disclose the actual prior
  spend and must not authorize dispatch or mutate the original campaign cap.
  Keep creation blocked: do not fix the preview by zeroing spend, ignoring the
  policy, or silently increasing a budget. A narrowly scoped cancellation-only
  or frozen-plan recovery workflow still needs real end-to-end verification.
- Reproduction: new test alone **1 failed in 1.98s**; combined with the original
  bypass test **1 failed, 1 passed in 3.11s**, exit 1. Failure is the expected
  HTTP 503-vs-200 assertion, not setup, expiry, identity or funding failure.
  Ruff on the new file and `git diff --check` passed. No full suite or new
  Windows build was run by this observer while the other task repairs source.
- Reproduced source hashes: `blueprints/coin_prep.py`
  `FFED3CB19188ACEBCF6461C8E85DB78F31C9DD4B65491F511D4C47AB32C33DC8`;
  `coin_prep_fee_runtime.py`
  `F2DBA262B7EBEBD2BC071C931C10238A5C1E2588E423E9F4704C187000AC0560`.
  New test hash:
  `D82BEBEF593563020F4926968DDFA4643DEF7A6F34F742705B03E09718FA1D10`.
- The repair task received the failing regression and a related review request
  to cover manual-stop cancellation refusal/submitted-unconfirmed followed by
  retry/restart. The latter is a traced concern, **not** a separately reproduced
  defect: current stop code terminalizes the campaign after any cancellation
  result dict while approved snapshots require an active campaign.

Fee-bearing live tests remain on hold. Exact post-fix full/backend/browser/
native/Windows-artifact verification and remaining live recovery/requote gates
are unfinished. No main merge, release, readiness or goal-completion claim.

## Historical observation

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
