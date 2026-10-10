# Candidate acceptance audit: 0ad637e

Candidate: `0ad637e84a47db7d94aeb936a895b734f5df7ec8`, branch
`codex/coin-prep-fee-approval`. This is an open-gate audit, not release approval.
It supersedes older candidate identifiers in the chronological checkpoint for
the purposes of the next acceptance run. No main merge or release occurred.

**Review update:** the baseline full run passed, but a subsequent whole-feature
review reproduced uncovered cancellation and integration defects. See
`2026-09-23-fee-whole-feature-review.md`. This build is superseded for readiness;
its successful package checks do not establish that the new fixes are packaged.

## Software evidence

| Requirement | Evidence on this candidate | Status |
| --- | --- | --- |
| Accurate indicative/trusted-price and running empty-book display | Regression coverage in the final Chromium run, 146 passed / exit 0 | Automated browser gate passed |
| Fee disclosure and exact CAT denomination/count previews | New red-to-green headroom, saved-zero confirmation and decimal count cases; 34 focused browser tests passed | Automated gate passed |
| Spare counts must not alter live ladder denominations | Two failing asymmetric-spare cases corrected; live counts price denominations while live+spare counts determine quantity; 60 economics/frozen-execution tests passed | Focused backend gate passed |
| Approved frozen worker dispatch and relevant frontend contracts | 142 tests passed / exit 0, including no missing-consent dispatch, exact holds, protected cancellation cover, frozen targets and related frontend files | Relevant regression gate passed |
| Full baseline regressions | Execution session 40526, `candidate-0ad637e-full.log`, exit 0: 6,884 passed, 147 skipped, 422 subtests in 1,122 seconds | Passed for this baseline only; later review fixes need a new run |
| Fresh Windows build and assets | Exact tracked export, `build.py --no-clean` exit 0; v1.4.0; source/bundled HTML hashes match | Build gate passed |
| Packaged API and wallet adapter | 8-endpoint API smoke, synthetic Sage mTLS worker, interrupted-publication recovery all exited 0 | Scoped package gates passed |
| Compiled fee entry-point rejection | Invalid preview/approval requests rejected with exact reason and false dispatch authority; trigger without consent rejected; mock RPC allowlist showed no wallet effect | Negative package fee gate passed, not positive live spending proof |
| Native Windows first-run, duplicate-window handoff, relaunch and identity fallback | Exact candidate has no native result; current controls could not launch that test and no alternate route bypassed the restriction | Operator test needed; see native-check handoff |

The fresh package retains the documented `importlib_resources.trees` build
warning. The optional Splash helper is not supplied by the tracked archive;
these checks do not certify that helper. No runtime-error-free claim is inferred
from a successful build.

## Scope of fee-control evidence

The implementation plan's requirements are exercised by distinct tests, not by
the packaged health endpoint alone:

- `test_fee_estimation.py`: strict values, original observation freshness,
  cost/target matching and unavailable-versus-zero guidance.
- `test_coin_prep_unsigned_preview.py` and `test_coin_prep_fee_projection.py`:
  actual executable CLVM, bound effects and disclosed future-stage projection.
- `test_coin_prep_fee_confirmation_api.py` and preview API tests: real HTTP /
  AppBridge routes, durable duplicate confirmation, no worker launch from
  consent, and lossless mojo readback. These are not native-window execution.
- Frozen-execution, dispatch-pricing and worker-dispatch tests: exact economic
  targets, within-cap repricing, atomic fee holds, scope/identity/freshness
  rechecks and no manual-fee or unsupported-backend bypass.
- Cancellation, ledger, recovery and session-completion tests: protected
  allowance, no replay authority, unknown effects remain held, and terminal
  accounting follows authoritative idempotent evidence.

The full-suite result above does not cover the later review fixes. These
coverage references do not replace their verification or live acceptance.

## Live acceptance remains open

The existing source runtime and browser draft were preserved, not silently
upgraded to this candidate. Historical TEST 7 evidence proves only the earlier
bounded uniform prep: two confirmed transactions, 22,837,112 mojos spent and
zero held/unresolved after recovery. It is not a completed live cycle on this
new executable.

Remaining live evidence must include:

1. Exact candidate identity plus Sage mainnet TEST 7 fingerprint 736588221,
   CAT wallet 2, MZ asset
   `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
2. The operator's actual displayed campaign/fee-budget confirmation, preserving
   protected cancellation funds. The review-only draft is not activation.
3. Live Coin Prep and authoritative fee/accounting readback for the test plan.
4. Offer creation/publication on both sides, genuine fill/requote evidence,
   stopping, active-load cancellation, remaking and restart recovery.

Follow mode's RED market confidence is a legitimate safety blocker, not a test
failure to bypass. The Bootstrap alternative still needs its final operator
action. Natural fill evidence cannot be substituted with historical fills or
a mocked transaction. The saved pre-fee 45/45 strategy exceeds available MZ;
it remains preserved, not activated or silently resized.

**Disposition:** not yet secondary-PC acceptance-ready under the full goal;
not main-merge or release-ready. Continue available software verification while
the separate native/live operator steps are pending.

## Receipts and operator handoff

- Chronology: `2026-09-16-coin-prep-fee-approval-checkpoint.md` in this directory.
- Native command: `2026-09-23-candidate-native-check.md` in this directory.
- Build and test logs: `.superpowers/sdd/2026-09-16-coin-prep-fee-approval/`.
- Executable SHA-256:
  `3C5FC6155D3B1BA0E0CD46FDE09D0CBFD8DB79267F3A3D3F665C4E7AFE2EFD1F`.
- Bundled HTML SHA-256:
  `DB933827F5BF55BC51EB798DB601F71A9BB4A8AA6EBE69C76A6A55509AB7B23D`.
