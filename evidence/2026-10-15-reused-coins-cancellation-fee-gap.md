# Reused coins leave campaign cancellation without prior fee consent

## Observed original-profile state

On TEST 7, campaign `bbce5ecd31f92f7deceb02f733ebf4233994423964e78cc59fbfe442dc80dc70` reused prepared coins. The bot subsequently owned six live MZ offers. Its campaign-bound Coin Prep fee approval lookup returned `None`; the authoritative campaign fee spend was zero. During the reboot, Sage became unreachable and the market guard requested protective withdrawal. Cancellation stopped at `FEE_BUDGET_APPROVAL_REQUIRED`, with the six offers unchanged and the bot stopped. Sage later returned synced with zero pending transactions and the same six exact offer identities. No cancellation fee was approved or spent by this path.

## Code path

- `bot_gui.html::checkIfCoinPrepNeeded` marks Coin Prep done as soon as `/api/coin-prep/verify` reports sufficient denominations. This branch never presents `/api/coin-prep/fee-preview` or records `/api/coin-prep/fee-approval`.
- `offer_manager.py` requires the latest campaign-bound approval for Bootstrap cancellation. The missing approval correctly fails closed.
- Cancellation-only recovery can quote a fee once live campaign offers exist (`test_bootstrap_unprepared_campaign_cancel_fee.py`). That repairs an operator-requested cancellation, but does not ensure advance consent for automatic protective cancellation.
- `blueprints/bot.py::api_bot_start` currently verifies campaign coin readiness and wallet identity but does not require campaign-bound cancellation fee consent before creating offers.

## Required release proof

Before general release, a campaign using reusable coins must present a truthful zero-preparation-transaction fee preview, obtain explicit campaign-bound cancellation protection, and keep Start Bot blocked until that consent is current. No fee approval may be inferred from the campaign cap or from a previous campaign. The existing cancellation-only recovery path must remain available for already-live offers. Test a real unsigned Sage fixture with selectable fee coins, native consent UI, stale/changed wallet rejection, backend start rejection without consent, and restart/protective cancellation. The simulated wallet in `approved_bootstrap` cannot prove the zero-prep preview by replacing coin rows alone: its unsigned bundle fixture only recognizes its original executable coin roots and returns `FEE_PROJECTION_PUZZLE_UNSUPPORTED` for synthetic replacement rows.

This remains a public-readiness blocker. The separate `fdcdfa0` market-withdrawal fix prevents known Bootstrap offers from being routed through ordinary Follow cancellation during a wallet-identity outage; it does not authorize or execute cancellation.
