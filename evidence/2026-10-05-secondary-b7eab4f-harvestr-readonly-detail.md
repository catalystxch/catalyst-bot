# PR #220 secondary-PC Harvestr read-only acceptance follow-up

Date: 2026-10-05 (Europe/London)

## Candidate identity

- Runtime/source candidate: `b7eab4f263409c0b4c846d6a506b21e16335ee37`
- Detached source worktree: `work/catalyst-pr220-b7eab4f`
- Remote PR #220 head at observation time: `d9c980bebfd30df4138464fdc0c1991f7b8ebd52`.
- Remote PR #220 head at evidence-publication time: `536f229cf8896fc86c9d84934daffcf082c86935`.
- The commits after `b7eab4f` through `536f229` are documentation/evidence-only for this runtime check.
- ZIP SHA-256: `D7E5066C33477A60A944EF6E2EB7A8FA4E2E583BC0CA58E44DC83584D533050D`
- Installer SHA-256: `4F68B683BB1FFE0D8495E5A546A29C08E71ED2310DD48C724C9670002C0E871B`
- `Catalyst.exe` SHA-256: `9EB27A8DFCB15B026318F75B797B6FAD628A9D46AB44DFC49C9CE2F9AACF3C8A`
- `bot_gui.html` SHA-256: `1FD778D4CC109562FF69942BD705D6CB107067017445C9B5E65E3514EC50A001`

## Scope and isolation

- No wallet-affecting endpoint or UI control was invoked.
- No campaign was started, stopped, renewed, cancelled, or modified.
- No historical fee approval was resumed or reused.
- The original profile `C:\Users\M920q\AppData\Roaming\Catalyst` was inspected read-only and was not launched.
- A lean copy was created at `profiles/b7eab4f-harvestr-copy-20261005`, excluding backups, build directories, and historical logs.
- Before launch, original and copied `bot.db` both had SHA-256 `9DD7D388E0DDD38733284D051B862939AF2B411380973DF42F6979BB9392DD4D`; `.env` had SHA-256 `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5` in both locations.
- After copied-profile launch, the original hashes remained unchanged. The copied database changed as expected for schema/runtime lease bookkeeping.

## Sage identity and exact read-only wallet state

- Sage executable: `C:\Users\M920q\AppData\Local\Sage\sage-tauri.exe`
- Sage version: `0.13.0`
- Sage executable SHA-256: `568B9CD6771F50333C9AEEF2534298F37AB3FFE52D9874110A6AA38B4E08C5C3`
- Key name: `Harvestr test wallet`
- Fingerprint: `3702373391`
- Network: `mainnet`
- CAT wallet ID: `2`
- Asset ID: `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
- Asset name/ticker: `Monkeyzoo Token` / `MZ`
- Sync: `19425 / 19425` owned coins synced.
- XCH: `240.800676512155` total and spendable; owned equals selectable.
- MZ: `3,381,521.720` total and spendable; owned equals selectable.
- Pending Sage transactions: `0`.
- Sage active/unexpired/fillable offers: `0`.
- Sage history returned 949 terminal offers: 818 cancelled and 131 expired.

## Original-profile durable state (read-only)

- CATalyst active offers: `0`.
- Current offer-operation blockers: `0`.
- Nonterminal reservations: `0`.
- Unresolved wallet-effect claims: `0`.
- The latest campaign `d61791de6807761e4a81c2a3ce58fb7b2ebad2dd012593ba0a37a122198694d5` is expired (`2026-10-03T10:10:57.150098Z`) but remains durably marked `active` / `bootstrap`.
- The prior runtime lease was expired but still marked active in the stopped profile. This is stale metadata, not an economic lock.
- Coin Prep rows: 106 confirmed, 3 failed, 0 unfinalized.
- Three historical fee approvals exist. They were not reused.

## Copied-profile package launch and UI/API result

- Exact packaged EXE launched with `CMM_DATA_DIR` set only for the child process to the lean copy.
- Sage RPC authenticated; startup status reported version `0.13.0`, fingerprint `3702373391`, and `ready`.
- Runtime safety reported `allowed=true`, zero blocker counts, and ownership of the copied profile's fresh runtime lease.
- Bot remained stopped throughout.
- API balances matched Sage exactly: XCH `240.800676512155`, MZ `3381521.72`, with spendable equal to total.
- `/api/offers`, `/api/offers/open_count`, and `/api/offers/diagnostic` all reported zero open offers. The diagnostic explicitly reported that wallet and DB agree and no Dexie row was evaluated.
- `/api/coins` reported zero locked XCH and MZ coins.
- Existing Coin Prep was complete. Its historical approval was visible, but `dispatch_authorized=false`, held fee `0`, pending operation `null`, and unresolved operation count `0`. No automatic reuse occurred.
- After hydration, the GUI selected `Monkeyzoo Token (MZ_XCH)`, showed Sage connected and synced, and displayed a prominent `Bootstrap expired — stop campaign before renewal` warning.
- Start was blocked with: `Bootstrap campaign expired — campaign-owned offers require cancellation before restart or renewal.`
- Market confidence was RED because current attributable market evidence was expired/unavailable and single-provider dependent. No attempt was made to bypass it.
- Fee status remained manual at `0.0000130791 XCH`; the read-only Coinset suggestion was `0.000007473753 XCH` at observation time.
- No browser console errors or warnings were captured during the live local page load.

## Shutdown and cleanup

- CATalyst PID 1116 closed gracefully via its main window; port 5000 released.
- The copied runtime lease was released cleanly: `active=0`, `released_at=2026-10-05T14:04:38.196139Z`.
- Sage PID 9944 closed gracefully; RPC port 9257 released, restoring the stopped state.
- Original `bot.db`, WAL, SHM, and `.env` hashes remained unchanged.

## Evidence and limitations

- Stable hydrated UI: `evidence/2026-10-05-secondary-b7eab4f-harvestr-copy-ui-hydrated.png`
- Initial hydration UI: `evidence/2026-10-05-secondary-b7eab4f-harvestr-copy-ui-initial.png`
- Initial screenshot SHA-256: `3CD84BC8A39E9F967D32E84E5B8A89AB9F3FDB01FCED479BA91D3CC12F315735`
- Hydrated screenshot SHA-256: `5C042E762C546DA94929CECB8F4D6D4982BABE2B4A8F42A718D54892CE42C208`
- Windows native automation could not attach because the local computer-use helper failed before initialization with `failed to write kernel assets: The system cannot find the path specified. (os error 3)`.
- A headless Chromium read-only verification of the same local package was used instead. It loaded HTTP 200, rendered meaningful UI, and produced no console errors.
- No new reproducible CATalyst defect was confirmed in this follow-up. The expired-active campaign and old approval are surfaced and blocked rather than silently resumed.

## Evidence-publication test environment note

- The secondary host uses Python `3.14.3`, pytest `8.4.2`, pluggy `1.6.0`, Playwright `1.63.0`, pytest-playwright `0.9.0`, Flask `3.1.3`, and requests `2.34.2`.
- The repository's safe serial suite command was:
  `py -3 -m pytest tests -q --tb=short --ignore=tests/test_coin_prep.py --ignore=tests/test_coin_prep_v2.py --ignore=tests/test_offer_create.py`.
- The broad run was stopped after it had already exposed multiple failures, to avoid an unnecessary costly rerun. A subsequent `-x` run stopped after `233 passed, 212 skipped` at `tests/test_bootstrap_fee_recovery_policy.py::test_overrun_recovery_requires_stopped_campaign_and_explicit_intent`.
- That exact test also failed alone on the secondary host (`1 failed in 1.64s`): the `approved_bootstrap` fixture expected `preview["available"] is True`, but received `{"available": false, "dispatch_authorized": false, "provider_failures": [], "reason": "FEE_UNSIGNED_COST_UNAVAILABLE"}`.
- The safe collection contained 8,166 output lines; the failing test was collection line 1,200 (one-based).
- The primary PC independently reported that the exact test passes alone on its current PR head. This is therefore recorded as a secondary-environment discrepancy requiring dependency/order analysis, not as a confirmed CATalyst product defect from the live read-only check.

## Result

The secondary Harvestr wallet is economically clean and safe for read-only inspection: no pending transaction, active/fillable offer, lock, unresolved operation, or held fee was found. The exact package safely recognized the stale campaign, kept the bot stopped, blocked renewal/start, and did not reuse the old approval. No wallet effect occurred.
