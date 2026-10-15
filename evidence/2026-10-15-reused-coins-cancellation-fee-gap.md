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

## Candidate correction and remaining live gate

Draft PR #268 commit `9f6ca215db36bce787cd0b39d82a7ca8adfee2d6` adds a zero-preparation fee review for a campaign that reuses coins. Start Bot requires current ordinary campaign-bound approval with a remaining cancellation reserve. New Bootstrap offer creation repeats that check before the wallet effect and rechecks campaign revision immediately afterward. Recovery-only consent cannot authorize trading. A missing, stale, superseded, or exhausted approval fails closed.

The exact commit passed 7,781 backend tests (307 skipped, 457 subtests), six opt-in browser tests, lint and formatting checks, independent code review, and all 11 PR CI checks. A clean detached checkout built a Windows package with EXE SHA-256 `99C62C8ACF17E2E37F19A68D19C2EEC1D32169F82EF2096C6408FF55BE9A95AD`; its bundled GUI hash matches the source GUI. Windows Defender custom scan found no matching threat. The exact EXE passed `scripts/packaged_api_smoke.py` with a temporary profile and mock Sage server, including health, startup, config, diagnostics, self-test, and doctor endpoints. It passed `scripts/packaged_sage_rpc_smoke.py` against a separate mock Sage mTLS endpoint. It also passed `scripts/packaged_desktop_first_launch_smoke.py` with a temporary profile and random port, covering clean native launch, duplicate handoff, persisted-profile relaunch, and fail-closed native startup. These checks left only the older original-profile CATalyst process running. The candidate package has not been launched against TEST 7, and the real reused-coin protective cancellation remains unproven. General public readiness is therefore still blocked.

## Read-only original-profile recheck, 2026-10-15 21:30Z

The older installed CATalyst process remained stopped at its native wallet selector, with a renewing lease owned by PID `41932`. Its executable SHA-256 was `94FE45BD2F0EAFE1487D1275C6F97F8A696631DF5ADA80D85414C1B8BBECEC29`; the candidate EXE above was not launched. A read-only Sage RPC check identified mainnet TEST 7 fingerprint `736588221`, zero pending transactions, and the same six active exact-MZ offers (three buys and three sells). The latest active campaign was `bbce5ecd31f92f7deceb02f733ebf4233994423964e78cc59fbfe442dc80dc70`, revision 0, fee cap `0.05 XCH`, spent `0`, expiring `2026-10-17T16:24:54Z`. The safety latch was resolved at generation 668. A read-only join of campaign fee previews, consents, and approvals found no approval bound to this campaign. This confirms the existing six-offer campaign still needs explicit cancellation protection before a safe bot resume; it does not prove the candidate's live behavior.
