# TEST 7 expired-offer proof candidate (2026-10-15)

## Problem and bounded change

The original TEST 7 campaign `a97ddb10f0ada7c3317f580b07b48c44b9caa8b3b1544385a71935c6d4bc6288`
expired while six campaign intents remained nonterminal in CATalyst. Sage's
complete live-offer view had no fillable offers or pending transactions. The
native UI therefore could not safely stop the campaign: it still counted the
six intents as offers requiring cancellation. The bot remained stopped.

Source `215854c504ce5f9b83299ff718c2fbbb9e0fca4b` adds a native **Verify
Expired Offers** control and a protected proof-only endpoint. It requires the
exact reviewed trade IDs, the same campaign revision and wallet identity, a
stopped bot, completed offer creation, two stable complete Sage offer/pending
snapshots, and `EXPIRED_PROVEN` evidence for every target before applying Task
9 terminal transitions. It neither sends a Sage transaction nor stops or
renews the campaign. The operator must review the resulting zero-offer
campaign and stop it separately.

## Verification of this exact source and package

- Full local backend: **7,770 passed, 301 skipped, 457 subtests passed**
  (`python -m pytest -n 2 --dist=loadfile --tb=short tests -q`).
- Focused bootstrap API, mutation-gate, and native/browser contract checks
  passed; the browser cancellation/recovery suite had **16 passed**. The
  complete Chromium suite later passed **300 tests**
  (`python -m pytest tests/e2e -q --e2e --tb=short`).
- Draft PR #268 at this exact head had **all 11 CI checks green**, including
  unit tests, lint, security scan, Semgrep, Gitleaks, and CodeQL.
- Clean `python build.py` produced `dist/Catalyst/Catalyst.exe`, SHA-256
  `94FE45BD2F0EAFE1487D1275C6F97F8A696631DF5ADA80D85414C1B8BBECEC29`.
  Defender's custom package scan reported zero detections.
- Isolated packaged API startup, authenticated mock Sage RPC, and native
  clean/duplicate/persisted/safety launch smokes passed against that EXE.
  They used temporary profiles and sent no live wallet transaction.
- A copy of the original TEST 7 database was used for a separate rehearsal
  against real Sage read-only evidence. The endpoint proved all six exact
  naturally expired offers, committed six terminal intents in the **copy**,
  left the campaign active, and sent no wallet effect. A separate real Sage
  classifier probe returned `EXPIRED_PROVEN` for each exact trade ID.

## Original-profile boundary at last check

The approved launch of the new build on the original TEST 7 profile was
interrupted by the user's physical Escape key **before computer-use window
selection**. No original-profile reconciliation occurred. The older stopped
CATalyst process remained PID 181980, sole port 5000 owner, at
`C:\catalyst\.superpowers\refresh-lineage-26e-build\dist\Catalyst\Catalyst.exe`.
The original-profile read-only preflight found Sage mainnet fingerprint
736588221, CAT wallet 2, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
zero fillable offers, zero pending transactions, six nonterminal campaign
intents, safety latch generation 668 resolved, and zero authoritative
campaign fee spend. Campaign revision 0 remained stored `active` after its
expiry; the bot was stopped.

This is evidence for a candidate recovery path, **not** a completed live
recovery or general public-readiness gate. The exact new build still needs
original-profile native proof, end-state audit, a reviewed campaign stop,
another real fill/cancel/restart run, Harvestr recovery, reciprocal Splash
peer receipt, full final-candidate 24-hour audits, and final review.
