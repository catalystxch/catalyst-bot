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

At that checkpoint this was evidence for a candidate recovery path, **not**
a completed live recovery or general public-readiness gate. The subsequent
original-profile proof and end-state audit are recorded below.

## Original-profile native proof (2026-10-15 16:16 UTC)

After the user returned control of the primary PC and approved this exact
launch, the old stopped CATalyst window was closed through its native shutdown
dialog with **Cancel all currently active wallet offers** unchecked. The new
EXE above was launched from this worktree as sole PID 218844 and sole owner of
127.0.0.1:5000; its on-disk SHA-256 matched the package hash above. Native
startup selected Sage TEST 7, fingerprint 736588221. Splash was skipped and
remained off. The original bot stayed stopped.

Immediately before the native proof, a separate read-only wallet facade check
found Sage mainnet TEST 7, a complete local table of 4,123 offers with **zero
fillable**, **zero pending transactions**, and balances of 138470190098731 XCH
mojos and 780212284 MZ atoms. The stored campaign remained active at revision
0 with zero authoritative fee spend, and safety latch generation 668 was
resolved. The native Settings pane showed that exact fingerprint, MZ pair,
ALLOWED runtime safety, six open campaign intents and the enabled **Verify
Expired Offers** button.

The operator used the native button and its confirmation, which expressly
stated that no wallet transaction would be sent. CATalyst reported **six
expired offers verified in Sage**. The six exact Sage trade IDs were each
independently observed in status `expired`; the same six registry intents were
committed `terminal` at `2026-10-15T16:16:12.293349Z`. A second complete
Sage read found zero fillable offers and zero pending transactions, unchanged
XCH and MZ balances, zero authoritative campaign fee spend, and latch 668
still resolved. The native Offers view showed Active 0, Buy 0, Sell 0 and
Pending Cancels 0. The campaign remains stored active but expired; its native
status now says **stop campaign before renewal**. The bot remains stopped.

The user then gave specific action-time approval to stop this zero-offer
campaign. The native final dialog said no campaign-owned offers needed
cancellation and history would remain untouched. The operator confirmed it.
The original DB recorded campaign `stopped`, revision 1, reason `manual`, at
`2026-10-15T16:18:22.007145Z`. A fresh complete Sage read still found zero
fillable and zero pending offers; balances and fee spend stayed unchanged.
All registry intents were terminal and latch 668 remained resolved.

This closes the specific original-profile all-expired proof and campaign-stop
gates. A new live fill/cancel/restart cycle, independent Harvestr recovery,
reciprocal Splash receipt, final-candidate 24-hour audits and final review
remain open. No general public-readiness claim follows from this proof.
