# Pre-start Follow fee ceiling review

Status: implementation design for the stopped original-profile CATalyst run. The approved Coin Prep on Harvestr completed with a 4,059,096,837-mojo ceiling and 774,766,315 mojos confirmed spent. The requested initial Follow ceiling is exactly 5,000,000,000 mojos. No Follow run exists yet, so the active-run ceiling revision flow cannot apply.

## Required behavior

- A completed standalone Coin Prep session may receive a fresh, explicit **pre-start** ceiling review for its exact existing wallet identity, economic scope, plan, configuration, receive address and prepared target coins. The review never creates a wallet effect or starts trading.
- The operator sees the prior ceiling, lifetime spent, held, previously approved protected cancellation amount, exact proposed ceiling, current fee funding and review expiry. Completed Coin Prep needs no new preparation quote; the separate Follow review obtains a fresh shutdown fee quote before any run can be approved. This pre-start path permits exactly 0.005 XCH, only if current fee inventory funds it and protected cancellation cannot shrink. Later adjustments use the active-run review. The UI must distinguish fee principal from paid fees.
- A native final click consumes one short-lived, immutable review. Confirmation rechecks wallet identity, configuration and targets before and after the serialized ledger transaction; that transaction checks the original completed session, latest approval version, exact spent and held accounting, protected amount, funding bound, absence of an existing Follow run, and reviewed ceiling. Any drift fails closed for Follow authority.
- Confirmation appends a new approval version in the **same scope and plan**. It never changes or deletes the completed prep record, prior approval, reservations, outcomes, or confirmed fees. The new approval is a ceiling authority only; no prep worker or offer dispatch follows from its creation.
- The new latest approval remains eligible for the existing Follow principal and 24/24 continuous run review. That review still proves current replacement counts, slot fit, maximum safely selectable XCH/MZ after protected fees, and shutdown funding. Existing active-run ceiling revisions retain their separate native review and immutable accounting.
- Ordinary Coin Prep previews keep their current completed-session generation rotation. A pre-start ceiling review must deliberately reuse the completed session; it must not mint a new session. If another action rotates that session before final confirmation, the review fails closed.
- Browser/API callers cannot fabricate reviewed identity, amounts, quote, scope or plan, and cannot use the pre-start review to bypass native confirmation. No code path silently raises a ceiling or treats a request as approval.
- Bot and site PRs remain draft/unpublished. Live EXE replacement and each financial final click require their separate action-time Computer Use confirmation; the source change itself grants neither.

## Evidence and acceptance

- Harvestr completed Coin Prep: 146 exact target coins, two confirmed fee operations, 774,766,315 mojos spent, none held or pending. The existing 4,059,096,837-mojo approval and completion remain immutable.
- Isolated tests prove a completed session can review and append a 5,000,000,000-mojo version while preserving paid/held totals, then obtain a 24/24 continuous Follow review; tests also prove stale/wrong wallet, changed plan/targets, held or spent drift, replay, concurrent confirmation, insufficient funding, lower protection, session rotation, and existing-run cases refuse without a new approval.
- Native UI/E2E tests show the exact review and no direct HTTP approval bypass. Targeted, full-suite, build, exact-head CI, binary hash and both original profile identities must be checked before any proposed live replacement. No 24/24 or observation pass claim follows from tests alone.
