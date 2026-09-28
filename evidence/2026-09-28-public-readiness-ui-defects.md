# Public-readiness UI defects found on the exact d048f44 package

Date: 28 September 2026. Primary Windows PC, browser served by the running
`C:\catalyst\.superpowers\public-ready-d048f44\dist\Catalyst\Catalyst.exe`.
Executable SHA-256 was independently rechecked as
`C200D870F3849A8D8D5E3541F5FBED5C7E36B95C5AD42A967DBCF4CF824CC200`;
the rediscovered process was PID 19568 at that exact path. Branch head
`5b5207c785bef95209dcd020e737e3ee6d5f2800` differed from runtime source
`d048f44cacd056abc9dbcc6fae3c588dc4c80e27` only in
`evidence/2026-09-24-live-test7-acceptance.md` before this fix.

The live readback at 10:58 UTC showed Sage fingerprint 736588221, mainnet,
CAT wallet 2, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
the same active bounded Bootstrap campaign and revision 0, three buys and
three sells, six unique non-reserve offer coins, zero wallet/database offer
discrepancies, zero pending cancellations, zero fee holds and zero unresolved
operations. Fee approval version 3 had 561,860,690 mojos total, 60,190,086
mojos confirmed spent, 0 held and 501,670,604 remaining. The campaign budget,
corridor, 10% deployment, reserves and 5% loss stop were unchanged. Bot health
reported Sage synced, zero consecutive failures and 129 completed cycles with
zero errors. No wallet mutation was performed during this UI review.

## Defect 1: Coin Prep approval reopened over a running book

Reproduction: open a fresh browser tab at the packaged app's localhost page
while the live 3/3 Bootstrap bot is running. After hydration the Dashboard
correctly showed `RUNNING`, six offers and a complete Coin Prep status, but a
full-screen Coin Prep modal opened with `Re-preparation Required` and a new
fee estimate/approval control. The modal was dismissible only by navigating
back to Settings. It made the running state appear to require another fee
approval even though the offer coins were merely locked by the current book.

Root cause: `restoreCoinPrepReadiness()` treated a historical completed worker
record as a reason to rerun the free-coin verifier for the active campaign on
every window reload. It did so while the bot was already running and its
prepared coins were locked by six live offers. The verifier's insufficient
free-coin result then opened the fee dialog.

Regression: `test_running_bootstrap_reload_does_not_request_coin_prep_again`
uses a completed, identity-matched campaign and live offers. It requires the
reload path to preserve the current-book state without a new verification,
fee-preview request or modal. It failed on the prior code because the real
path called `/api/config`, `/api/coin-prep/verify`, returned `checking` and
opened the modal. The correction skips free-coin verification only for a
completed, identity-matched, currently running book with active offers;
stopped campaign reloads still use the exact verifier.

## Defect 2: Splash local acceptance was labelled publication success

Reproduction: open Offers > Active in the same live package. All six cards
showed `Publication: Dexie succeeded · Splash succeeded`, while each card's
Splash discovery remained `pending`. The daemon log recorded repeated
`Broadcasting Offer failed: InsufficientPeers`; Market Intelligence showed
zero peers, six local submissions and no received offer. The API's durable
`publication.splash.state=succeeded` records the local daemon's HTTP 2xx
acknowledgment. It does not prove peer broadcast or exact external discovery.
Dexie exact discovery independently verified all six offers.

Root cause: the Offers renderer printed the durable publication state verbatim
for both Dexie and Splash. Splash's local acknowledgment semantics were lost
in the user-facing wording.

Regression: `test_splash_local_acknowledgement_is_not_labeled_published`
renders a locally acknowledged Splash offer with pending discovery. It failed
on the prior code because the card said `Splash succeeded`. The correction
labels that state `Splash local submit acknowledged; peer broadcast unverified`
and leaves the exact discovery state visible separately. No durable publication
or wallet state is rewritten.

## Verification and candidate scope

- Both new Chromium regressions failed for their intended assertions before
  the production correction and passed afterward: 2 passed.
- The complete affected Coin Prep fee approval Chromium file plus the new
  regressions passed: 31 passed in 20.21 seconds.
- The complete Chromium suite passed: 167 tests in 92.72 seconds.
- Ruff check passed repository-wide; format verification passed 478 tracked
  Python files and the new test file; `git diff --check` passed.
- The full Python suite, fresh Windows package and packaged/live checks are
  pending at the time of this checkpoint.

These are source changes. The old d048f44 package and its live observations
cannot establish acceptance of the revised candidate. Both 24-hour windows
and all final release gates remain open until the exact revised artifacts are
verified. PR #220 remains draft. No merge, tag, upload or public release was
performed.

## Defect 3: Startup risk dialog leaked keyboard focus

The secondary PC independently tested the exact d048f44 package at 360, 480,
768 and 1280 pixel widths using a separate isolated profile. The startup risk
disclosure scrolled correctly, but Tab moved from its Close app button into
background navigation. Shift+Tab also escaped from the Continue button. The
monitored secondary process was preserved. Its focused stale-fee, provider
outage and recovery E2E checks passed. The secondary evidence is in its
`outputs/d048f44-packaged-ui-readonly-20260928` directory.

Root cause: the generic modal observer only watches `.active` transitions,
while the startup overlay is visible by default and never receives `.active`.
It had neither a keyboard focus trap nor an initial focus target.

The new `test_startup_risk_dialog_keeps_keyboard_focus_inside` failed on the
original behavior when Tab left Close app. The correction labels the startup
overlay as a dialog and wraps Tab/Shift+Tab between its two enabled actions.
If both actions are disabled while checking wallet status, focus stays on the
dialog. The first version focused Continue immediately, but a 360-pixel-window
regression showed that this scrolled the overlay down 402 pixels, hiding the
risk explanation. `test_startup_risk_dialog_opens_at_top_on_small_window`
failed with that exact scroll offset. The corrected initial focus is the
dialog container with `preventScroll`, and Tab moves to Continue. The focused
E2E file then passed all four tests. Full suites and a new exact-commit
package are required for this further source change.
