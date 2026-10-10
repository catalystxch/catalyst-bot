# Secondary-PC live acceptance — 2 October 2026

## Verdict

**READY** for primary-PC review and merge decision. Do not merge automatically.

The accepted runtime source is commit
`794e3412b16cc837a58cf270f3cc2d4af427f9a1` on
`codex/fix-bootstrap-cancel-fee-renewal`. Pull request:
<https://github.com/catalystxch/catalyst-bot/pull/237>.

PR #237 targets `codex/coin-prep-fee-approval` at accepted base
`364c49f3279f144b786ff0306ce2881be6e5a887`. The primary PC retains review and
merge responsibility; this secondary PC did not merge the PR.

## Build and package identity

- Windows build command: `.venv\Scripts\python.exe build.py`
- Runtime source commit: `794e3412b16cc837a58cf270f3cc2d4af427f9a1`
- `Catalyst.exe` SHA-256:
  `0A41CAD8508D06938291EF7DD8160D07F58B172E2E348823C70282B629BF6B79`
- Acceptance ZIP SHA-256:
  `AA5E05B1497EF49C6D94C1FA07C69520123A7086DFE6E6B200F8E878A0A78CB1`
- ZIP size: 35,844,136 bytes
- Local ZIP:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\acceptance-artifacts\794e341\CATalyst-794e341-secondary-acceptance.zip`
- The ZIP was extracted to a new directory. The extracted executable had the
  same SHA-256 and passed both packaged smokes.
- The last wallet-affecting cancellation used the packaged `b28601f` build,
  executable SHA-256
  `2EC9318240B461A356E318E7DE9594C4E673B1426158322D293479DE14930E15`.
  The only later runtime commit, `9080b60`, is formatting-only in the already
  reviewed resume code and its lifecycle tests.

## Machine and wallet identity

- Network: Chia mainnet
- Wallet: Sage 0.13.0, `Harvestr test wallet`
- Fingerprint: `3702373391`
- CAT wallet ID: `2`
- Pair/ticker: MZ/XCH, `MZ_XCH`
- Asset: Monkeyzoo Token, 3 decimals
- Asset ID:
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
- Authoritative pre-test backup (never deleted):
  `C:\Users\M920q\AppData\Roaming\Catalyst\backups\bot_backup_20261002_071124.db`

This identity was re-proved immediately before wallet mutations. No second
CATalyst process controlled this wallet concurrently.

## Fee approval and Coin Prep

Campaign:
`d61791de6807761e4a81c2a3ce58fb7b2ebad2dd012593ba0a37a122198694d5`.
The authoritative market-confidence result constrained the live campaign to a
safe three-offer sell bootstrap; RED protections were not bypassed.

- Exact plan SHA-256:
  `e20a47c19e267d027248a12ff994e467d984090bcede4d47d6e80581bb3c49f5`
- Scope SHA-256:
  `736d321cb2be6704945b25a03206fc676beb498bee756d3d83f578d6b70f9307`
- Approval v1:
  `dfd3317daccb039c97c897be0292ff0904ffb7a45055ecee92f92061fefe3184`
- Approval v2 renewal:
  `1b8f1d017baa03ce2b83b3cfb877d9e93f7de4fa20c5db7534af589b6e7c588f`
- Displayed cap: 100,000,000,000 mojos = 0.1 XCH
- Latest cancellation reserve: 61,386,840 mojos
- Coin Prep operation:
  `coin-prep:3899717f9567ac7172748d3b376e8a1b159b8ea2ac2a35813dffc655ea53fd9c`
- Coin Prep exact paid fee: 37,339,821 mojos = 0.000037339821 XCH
- Coin Prep ran from 11:29:39 to 11:31:52 local time (2m13s).
- Authoritative operation window: prepared 10:30:03.774846Z, finalized
  10:31:32.331620Z.
- Result: 30 exact 5,000 MZ replacement coins, one 70,000.002 MZ top-up,
  one 0.920231266 XCH fee reserve output, and three pre-existing 0.001 XCH
  fee coins recognized. Fee scope closed from 33 targets and one operation.
- Campaign fees confirmed spent across the approval renewal: 82,338,193
  mojos = 0.000082338193 XCH. This includes Coin Prep and two confirmed
  cancellation cohorts.
- All confirmed fee-approved outcomes currently visible in the acceptance DB,
  including the earlier acceptance cycle, total 109,929,257 mojos =
  0.000109929257 XCH, far below the operator's 0.9 XCH cumulative cap.
- Final held fee: 0. Pending fee operation: none. Unresolved fee operations: 0.

## Published offer ladder and external reconciliation

All three offers were genuine Sage offers and were published to Dexie. Each was
a **sell of MZ for XCH**:

| Sage trade ID | Dexie offer ID | MZ offered | XCH requested | XCH/MZ |
| --- | --- | ---: | ---: | ---: |
| `f8473ef1cb78c068062c0b03c4580bd4b5b554ddde252e0d17eafef997b3d297` | [`3xGWhnmU82H1bz6uTfveGAdeqMtPn7yD1oxGYmPVgN6T`](https://dexie.space/offers/3xGWhnmU82H1bz6uTfveGAdeqMtPn7yD1oxGYmPVgN6T) | 5,000 | 0.55 | 0.00011 |
| `51ac84c081163a17e63cabab32981af69b0b9a312d7560a9fae3e03b70b13bfc` | [`DKGTR7cgq19nmCcVoUB8sBcrLLvUnRgPfUkU6aqMams5`](https://dexie.space/offers/DKGTR7cgq19nmCcVoUB8sBcrLLvUnRgPfUkU6aqMams5) | 5,000 | 0.56125 | 0.00011225 |
| `61ef6d26d66619ebb34d78a54b72f5e191cf93c331caa74ea0cbbc08e8baa80c` | [`FTNeo5gjJqTRYtUqVy27jqpFYme2NTycEcfouq2fQJMx`](https://dexie.space/offers/FTNeo5gjJqTRYtUqVy27jqpFYme2NTycEcfouq2fQJMx) | 5,000 | 0.58 | 0.000116 |

CATalyst reload detected the existing three-offer campaign and resumed it
without repeating Coin Prep. Stop retained cancellation authority. A protected
Cancel All then canceled all three in one cohort.

Final cancellation proof:

- Cohort:
  `cancel-cohort:c2c77a1b41c00681d8bd76ed0d21af5b8b35c7bb797dbf5581537a30890af39b`
- Manifest SHA-256:
  `826b76f777dc40293c968355a124569c1fb76f4cbc84c1c8f3022fcd36097a2f`
- Transaction:
  `b16e7ce663ec0055690650f6e387c5600f87af179bc670cd67b336262e74f9ce`
- Spend identity:
  `sha256:e07f41c1c3775e1229f4fd48853d153b91d164060d583d615b4353e83e002a01`
- Confirmed block: `9,374,966`
- Exact fee: 39,876,994 mojos = 0.000039876994 XCH
- Classification: `CANCELLED_PROVEN`
- Reason: `EXACT_CANCEL_RETURN_PROOF`
- Result: canceled 3/3, pending 0, failed 0, no duplicate spend.

A final fresh Dexie API read returned status `3` for all three offers, with
`date_completed=2026-10-02T15:10:47Z` and exact amounts matching Sage and
CATalyst.

## Final authoritative state

- CATalyst open offers: 0 buy / 0 sell
- Sage open offers: 0 buy / 0 sell
- Sage cancel-pending: none
- Sage canceled-but-still-visible: none
- CATalyst locked XCH: 0
- CATalyst locked CAT: 0
- Contradictory history blockers: 0
- Unresolved operation blockers: 0
- Prepared creations: 0
- Publication claims: 0
- Fee reservations/holds: 0
- Submitted cancels: 0
- Local offer book consistent: true
- Runtime: stopped; no unexplained bot stop

The final redacted debug bundle confirms MZ/XCH wallet ID 2, bot stopped, zero
open offers, zero XCH/CAT locks, 216 free XCH coins and 140 free CAT coins.

## Confirmed defects and fixes

Every confirmed defect was reproduced and fixed test-first on PR #237. The
branch contains these fix commits after accepted base `364c49f`:

- `c917d09` — renew Bootstrap cancellation fee authority.
- `9013760` — recover cancellation funding shortfalls.
- `275f51f` — allow stopped-campaign cancellation after session restore.
- `1469e6b` — report authoritative terminal cancellation correctly.
- `8c9bb26` — support fee-only XCH prep for a sell-only Bootstrap campaign.
- `9afc722` — preserve Bootstrap tiers and cancellation renewal.
- `f5f0add` — complete active Bootstrap cancellation recovery.
- `7132116` — hide the fee-recovery overlay while the bot is already running.
- `af44299` — resume only the exact recovered offer set.
- `d931414` — fail closed on unresolved current-revision authority.
- `ea735f0` — keep campaign cancellation accessible after Stop.
- `b28601f` — cover campaign cancellation recovery's negative fail-closed
  matrix.
- `9080b60` — formatting-only final gate cleanup.
- `794e341` — bind cancellation fee recovery approvals to an explicit
  `cancel_all` or `bootstrap_stop` action, reject pre-marker legacy campaign
  approvals, and prevent recovery-only consent from entering ordinary Coin Prep
  dispatch.

The final P1 review found that the previous recovery path inferred
cancellation-only authority from campaign state and reused the same request
shape for ordinary preparation and recovery. An approval could therefore be
ambiguous after restart or policy stop. The fix adds a server-owned immutable
approval-authority marker, propagates the exact recovery action through quote,
reserve, recheck and wallet-effect boundaries, rejects mismatched or legacy
approval scope, and sends users back through the displayed fee-review flow.
Ordinary campaign consent remains usable only for its original cancellation
allowance; a policy-materialized recovery requires fresh action-bound consent.
No additional wallet action or fee was used to verify this P1 fix.

The final user-visible defect was a stale Coin Prep recovery overlay after
Stop. The fee approval correctly remained approved to preserve the
cancellation reserve, but the frontend interpreted that state as unfinished
Coin Prep. The fix suppresses only that stale overlay when campaign identity,
live offers, cancellation reserve, zero held fee, zero unresolved operations,
and no pending operation all agree. The underlying mutation gate remains
fail-closed. Negative tests cover held fee, unresolved operations, campaign
mismatch, zero reserve, and zero live offers.

## Verification commands and exact results

- `.venv\Scripts\python.exe -m pytest -q --basetemp C:\Users\M920q\AppData\Local\Temp\pytest-p1-final-clean`
  — **7,133 passed, 199 skipped, 424 subtests passed**, one known
  `PytestRemovedIn10Warning`, 3,664.31s.
- `.venv\Scripts\python.exe -m pytest tests\e2e --e2e -q --basetemp C:\Users\M920q\AppData\Local\Temp\pytest-e2e-p1-clean`
  — **198 passed** in 454.02s.
- Focused affected backend matrix — **245 passed** in 633.64s.
- The E2E startup-race regression was made deterministic and passed three
  consecutive isolated runs before the clean 198-test suite.
- `.venv\Scripts\python.exe -m ruff check .` — passed.
- `.venv\Scripts\python.exe -m ruff format --check .` — 555 files already
  formatted.
- `.venv\Scripts\python.exe -m vulture src/catalyst scripts desktop_app.py build.py scripts/vulture_whitelist.py --min-confidence 90`
  — passed.
- `.venv\Scripts\python.exe scripts/check_tracked_secrets.py` — passed.
- `.venv\Scripts\python.exe -m bandit -r src --ini .bandit -ll` — zero
  medium/high issues (595 low informational findings).
- `.venv\Scripts\python.exe -m pip_audit -r requirements.txt -r requirements-dev.txt`
  — no known vulnerabilities.
- `git diff --check` — passed.
- `scripts\packaged_api_smoke.py --exe <extracted Catalyst.exe>` — passed;
  v1.4.0 health, startup, config, diagnostics, self-test and Doctor endpoints.
- `scripts\packaged_sage_rpc_smoke.py --exe <extracted Catalyst.exe>` —
  passed; client certificate observed, required read-only RPC calls present,
  no initialize/login/resync calls.

One attempted final pytest run exhausted the C: drive at 89%, causing a
filesystem-error cascade. This run is invalid evidence, not an application
failure. The verified disposable pytest cache (5.04 GiB) was removed, the
suite was rerun in a bounded temp directory, and the exact clean result above
crossed the prior point and finished 100% with exit code 0.

## Evidence locations on the secondary PC

- Final debug bundle:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\fifth-fix-live\bot_debug_bundle_final_9080b60_20261002_165445.zip`
- Debug bundle SHA-256:
  `13953023CB956F9B466F659C0D0D39E37EA482FC68C78BC693F76B63A1328216`
- Debug bundle entries: 29
- Final cancellation screenshot:
  `evidence/fifth-fix-live/cancel-all-complete-b28601f.png`
- Original stale-overlay defect screenshot:
  `evidence/fifth-fix-live/stale-coinprep-overlay-blocks-cancel-after-stop-d931414.png`
- P1 action-bound recovery package:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\acceptance-artifacts\794e341\CATalyst-794e341-secondary-acceptance.zip`
- P1 package SHA-256:
  `AA5E05B1497EF49C6D94C1FA07C69520123A7086DFE6E6B200F8E878A0A78CB1`

No wallet action, offer, fee hold, or unresolved mutation remains active.
