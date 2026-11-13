# Single-approval CAT ladders

## Goal

A person can select any CAT in the connected Sage wallet, choose a BUY and SELL offer target (including 24/24 or 100/100), run Smart Settings, edit the proposed price and range, and approve one clearly described run. CATalyst then prepares coins and starts the ladder automatically. The approval remains effective until that person presses Stop, changes its material terms, or a genuine wallet-identity fault prevents safe operation.

This supersedes conflicting approval, stale-price and fee-cap requirements in `2026-11-03-thin-market-ladders.md`. The original two-PC MZ/XCH acceptance goal remains.

## One review

Smart Settings proposes offer counts only when the user has not chosen them. User-chosen targets are preserved. It calculates affordable coin sizes, per-side funding, tier counts, a fee-coin pool sized for about a week, a price anchor and range, and a low network fee recommendation plus an editable *maximum fee per transaction*. It must not silently replace a user-selected fee-coin principal or offer target.

The single review immediately after Smart Settings shows the wallet fingerprint, network, selected CAT, BUY/SELL targets, currently fundable slots, XCH/CAT principal, retained reserves, fee-coin principal, proposed price and editable min/max range, fee recommendation and editable per-transaction maximum. It describes the current market confidence rating and concrete RED reasons. It identifies the price evidence and warns when the anchor is old or inferred. The user can edit the proposed price and range before approval. One explicit approval covers initial coin prep, bot start, and later coin prep, fee-coin replenishment, creation, cancellation and requoting for that run, provided each fee is at or below the approved per-transaction maximum and other approved terms are respected.

The review is a user-facing decision, not an omission of internal effect checks. CATalyst retains wallet identity, exact effect, pending-transaction, lease, journal and duplicate-dispatch protections. Internal fee estimates and proofs must not create additional operator approval screens for tiny changes below the approved cap. The approval must be recorded durably and scoped to its wallet, CAT, targets, price policy and fee maximum.

## Automatic execution

After approval, CATalyst saves the run, verifies wallet state, reuses suitable coins, prepares only missing coins, and starts the bot. Coin prep is idempotent. Temporary Sage or network failures are retried automatically after rechecking the journal and authoritative chain state. A retry never blindly repeats an unknown wallet effect. When prep finishes, Start does not require another click.

Requested offer counts are targets, not a claim that all slots can always be funded. If the wallet cannot fund every slot, CATalyst posts as many valid offers as it can and fills the remainder when balances or reusable coins permit. The approval screen and dashboard show target, fundable and live counts separately. Arbitrary 50-per-side UI and authority limits must be replaced by a resource-based planner so 100/100 can be requested. Publication can remain batched and proof-gated; progress is visible.

The bot chooses a low fee expected to confirm, below the approved maximum, rather than spending the maximum by default. The maximum applies to every fee-bearing wallet transaction, including prep, top-ups, cancels and replacement work. If the recommended fee rises above the cap, CATalyst asks whether to raise it and shows the new estimate. While awaiting the answer, it may submit the affected transaction at a lower fee within the approved cap, accepting slower confirmation. It must track that transaction to authoritative completion before retrying or replacing it. If a within-cap submission cannot proceed safely, only that affected action pauses; safe fee-free work continues. Raising the cap is a new user decision that updates the durable run policy without restarting the setup flow.

## Thin markets and pricing

RED market confidence alone does not stop creation or trigger cancellation once the user has approved the disclosed RED reasons. A worsening RED rating produces a visible warning while the approved ladder continues. Offers remain passive under the approved price policy. CATalyst may use current book/trade evidence to propose the initial anchor. If no live price source is available, it proposes its best historical or inferred price for user agreement; the user can edit it. An approved anchor can be used indefinitely while live sources are unavailable, with a persistent warning. New source data can improve pricing without renewed approval while offers remain within the approved range.

The ladder reprices and replaces offers as the market moves inside the approved range. If the market moves beyond that range, CATalyst proposes a new range and waits for approval before placing offers beyond it. Existing live offers remain open while it waits. RED reasons changing within the range do not require reapproval.

If Sage presents a different wallet or CAT from the approved identity, CATalyst stops creating offers and alerts the operator. It must not write to a different wallet under the old approval. Existing-offer cancellation remains a separate, explicit action unless it is ordinary requoting within the approved run. Other genuine wallet, pending-effect and chain-recovery guards remain.

## Stop and restart

Stop halts automatic management and disables automatic restart, but does not cancel live offers. Cancel All remains a separate instruction. A clean or crash restart automatically resumes an approved run that was not manually stopped after verifying the same wallet, CAT, current offers, pending effects and journal. This also applies when zero offers are currently live. The run rebuilds toward its target without duplicate wallet effects. If coin prep was interrupted, CATalyst proves what confirmed and finishes only missing splits under the existing approval.

The RED override has no elapsed-time expiry; it lasts until Stop or a material change requiring a new review. Changing wallet, CAT, target counts, approved price range or per-transaction fee maximum cannot silently inherit the old authority.

## Acceptance

- One screen and one approval take a fresh 24/24 MZ/XCH setup through Smart Settings, coin prep and bot start on each PC.
- A 100/100 request is accepted as a target; the UI shows currently fundable and live counts rather than rejecting it at 50.
- RED reasons and stale price warnings remain visible, but neither alone empties or withdraws an approved ladder.
- A fee below the approved per-transaction maximum never creates a new approval prompt. A fee above it prompts for a revised maximum and pauses only affected actions.
- Restart with zero or nonzero live offers resumes automatically; Stop prevents automatic resume and leaves offers open.
- Tests exercise the full setup and restart state machine with a mock wallet, including pending and unknown effects. Live acceptance checks Sage, database, GUI and offer-book counts on both original PCs without assuming that a successful Start response proves a 24/24 ladder.
