# TEST 7 requote cancellation: live safety stop

Status: **open acceptance blocker**. This records observed state; it does not
authorize a latch release, restart, cancellation retry, or offer Take.

## Exact runtime and monitor

- Original TEST 7 profile was running source
  `f03432f5500588588f59de69ef2912a5441f863f` as PID 171260 from
  `C:\catalyst\.superpowers\desktop-resume-f034-build\dist\Catalyst\Catalyst.exe`
  (SHA-256 `378E7F36ED914F2344F04DEE9F502044660AAB9AEBD76ABEB95A57D74A5A55A3`).
- The exact PID/hash 60-second trace is
  `E:\catalyst-stability-monitor-f03432f-normal-20261013\trace-60s.jsonl`.
  Its first 319 samples were clean. Sample 320 at 2026-10-13 08:55:48 UTC
  recorded `UNRESOLVED_OPERATIONS`; the bot was stopped by sample 322.
  This window **failed** its safety gate, regardless of later uptime.

## Cancellation and authoritative observations

- A live requote staged replacement buy and sell offers at 08:54:26–29 UTC.
  The parent buy trade ID was
  `376406992d61590c83092ec392348d347871c0e37d840ec042d42a2dfd268ecf`.
- Its durable cancellation journal finalized at 08:54:59 UTC with
  `CANCEL_SUBMITTED_UNCONFIRMED`, transaction ID
  `cbe19eece2aeb55ddb62cbb320082a562af9f9e1c93f6caf057512a6130c07f4`.
  The runtime safety latch tripped at generation 666 for this one operation.
- Sage's native relay log reported the exact transaction accepted. Sage then
  reported it pending while the original offer was still active. By about
  09:12 UTC, the transaction had left Sage's pending list and Sage reported
  the exact parent offer `cancelled`.
- A separate **read-only** call through the exact source's
  `offer_reconciliation.load_authoritative_evidence`,
  `_derive_single_cancel_context`, and `classify_terminal_evidence` returned
  `CANCELLED_PROVEN / EXACT_CANCEL_RETURN_PROOF` for the bound intent.
  The live app's `/api/safety/status` still reported `allowed=false`,
  `UNRESOLVED_OPERATIONS`, and one blocker at 09:15 UTC. No release was made.
- At the same read, Sage reported the original sell and both staged children
  active. The staged sell did not have a Dexie publication ID in CATalyst's
  database; the original sell and staged buy were publicly active on Dexie.
  The book therefore needs a fresh wallet/DB/publication reconciliation before
  any offer link is recommended for a Take.

## Next acceptance work

Investigate why CATalyst's built-in proof-only submitted-cancel recovery did
not clear the live gate, then verify no second wallet effect, exact latch
release, fee ledger, all four offer IDs and publication state. An unrelated
eBay Windows Security passkey prompt initially covered the native UI; the
user dismissed it, and it was not automated. Only after the live safety state
and exact book agree should TEST 7 resume or provide a public offer for the
requested Take test.

## 09:27 UTC native recovery attempt and isolated proof

- The user dismissed the passkey prompt and gave action-time approval for the
  final native **Cancel All** control. Immediately before the click, the live
  gate still reported `UNRESOLVED_OPERATIONS`, Sage had zero pending
  transactions and exactly three active offers, and CATalyst displayed four
  (including the cancelled parent). The bot was stopped.
- The native confirmation was clicked once. Its dialog closed, but at 09:29
  UTC the live gate still reported one blocker and `allowed=false`. The exact
  cancellation journal remained `CANCEL_SUBMITTED_UNCONFIRMED`; Sage still had
  the same three active offers and zero pending transactions. The campaign's
  authoritative fee-spend total remained zero. No second cancellation or
  other wallet effect was observed. The UI did not expose a useful result.
- A private SQLite snapshot of the original profile was made with SQLite's
  backup API under `C:\catalyst\.superpowers\forensic-test7-20261013`.
  Against that **copy only**, the exact packaged source classified the parent
  cancellation as `CANCELLED_PROVEN / EXACT_CANCEL_RETURN_PROOF` and
  `reconcile_offer` returned `applied=true`, resolved the copied latch, and
  cleared its blocker. This proves the recorded evidence can pass Task 9's
  database commit path. It does **not** prove the live API request reached that
  path or that the live gate is clear.
- Investigate the native recovery route's actual response, stopped-process
  quiescence check, and settlement worker outcome before another control
  attempt. Keep the original profile fenced. The user's requested TEST 7
  offer link remains withheld until the live state and offer book reconcile.

## 09:46 UTC GUI response defect and candidate fix

- Source review found a separate, deterministic GUI bug: the blocked-gate
  `/api/offers/cancel_all` route can return HTTP 202 with
  `success=false`, `async=true`, and `reconciliation_only=true` while it
  checks the old cancellation without submitting another transaction. The
  existing `confirmCancelAll()` treated every `success=false` response as an
  immediate error, closed the dialog, and never polled the proof result.
- A new Chromium test reproduced that behavior (no status poll), then passed
  after the GUI was changed to show and poll the proof-only operation. The
  revised GUI reports `reconciled` and `awaiting_authoritative_proof` as
  distinct terminal states and never starts a second cancellation from that
  response. Another red/green Chromium test proved that a preflight rejection
  such as `BOT_STOPPING` had no visible toast; the GUI now displays its exact
  error. Ten focused Cancel All tests, all 110 Chromium smoke tests, 17
  cancellation fee-flow tests, and 62 backend offers endpoint tests passed
  locally.
- A clean Windows PyInstaller build succeeded from this worktree. The bundled
  `bot_gui.html` SHA-256 equals the source HTML SHA-256
  `A112496160F3B7A0419ECB180C70714EB4F03A29845F107C2C5D9CDB5FBF06ED`.
  The rebuilt EXE SHA-256 is
  `1728F315C3BEB54FF83E5416BBA5AF2D2CE4ECBA3F6080B6D92FE0E519BAAC37`.
  Packaged API smoke passed against an isolated mock Sage RPC and temporary
  profile on a non-default port. This package has not run on the original
  TEST 7 profile and does not establish live reconciliation.
- This identifies why the UI did not show a useful outcome. It does **not**
  establish whether the live request was rejected by its quiescence check,
  entered the background proof worker, or failed during settlement. The
  original packaged process remains on the older GUI and its safety gate is
  still blocked. No wallet action or latch release was made by this fix.
