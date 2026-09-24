# Primary review of secondary-PC defect fixes

Date: 2026-09-24

Target branch: `codex/coin-prep-fee-approval`

Reviewed pull requests separately:

- PR #221, CAT Coin Prep live-tier sizing
- PR #222, duplicate packaged desktop-window handoff

Neither pull request was merged and `main` was not changed. The reviewed commits
were cherry-picked onto the target feature branch after source inspection and
focused verification.

## Review conclusions

### PR #221

The reported defect was confirmed: prepared CAT output counts include spare
coins, while sell sizing must divide inventory only across live sell slots. The
change passes a separate live CAT tier-count contract to the worker and retains
the historical total-count fallback for older callers.

Primary review added an endpoint regression proving that the Flask trigger
passes `inner=3` as total prepared CAT outputs while independently passing one
live inner sell slot. This closes the gap between the submitted worker-unit
regression and the actual subprocess command.

### PR #222

The handoff change retains exact owner PID and exact window-title verification.
It attaches input queues only after an ordinary foreground attempt is denied,
retries activation, and detaches in reverse order. Missing evidence or any API
failure remains fail-closed.

Primary review added a partial-attachment failure regression proving that an
already-attached foreground input queue is detached when joining the verified
owner thread fails.

## Primary verification

- Coin Prep economics and endpoint tests: **85 passed**.
- Focused desktop handoff tests: **7 passed**.
- Broader Coin Prep and sell-ladder selection: **682 passed**, 2 existing
  collection warnings.
- Desktop mutation gate, packaged smoke unit, process lifetime and instance
  lock selection: **271 passed**.
- Ruff on all changed production and test files: passed.
- `git diff --check`: passed.

The secondary PC separately recorded a green full suite, fresh Windows builds,
packaged smoke evidence, and a successful live TEST 7 Coin Prep for PR #221.
The remaining live publication and fee-estimator outcomes are documented safety
blocks, not bypassed gates.
