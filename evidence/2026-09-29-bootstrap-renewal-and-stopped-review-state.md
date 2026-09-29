# 2026-09-29 Bootstrap renewal and stopped-review-state acceptance

## Operator approval and exact campaign

After the prior protected cancellation and profile handoff, the operator
personally acknowledged the `fd16401` browser session's Risk Disclosure and
connected Sage. The subsequent user instruction to continue approved the
separately previewed same-cap 24-hour MZ/XCH campaign. Before creating it, the
live EXE path and SHA-256, stopped bot, empty and consistent Sage/database
offer books, mainnet fingerprint 736588221, CAT wallet ID 2, exact asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
and fee ledger with zero held/unresolved amounts were checked again.

The operator-approved review was entered in the real packaged browser UI:
anchor `0.000075` XCH/MZ, one day, market budgets `0.9` XCH and `12000` MZ,
fee budget `0.001` XCH, and zero subsidy. The preview showed the exact asset,
fixed corridor `0.0000375`–`0.00015`, 10% initial deployment, and three buys
and three sells. After confirming that exact asset and those caps, the UI
saved campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
at `2026-09-29T11:27:42.748405Z`, expiring exactly 24 hours later at
`2026-09-30T11:27:42.748405Z`. Its durable readback shows revision 0,
mainnet/Sage identity, 5% loss-stop policy from Bootstrap, fee spent zero,
zero confirmed fills and zero open offers. The API's campaign-start operation
reported no financial action; the bot remained stopped. The old Coin Prep
approval is tied to the expired prior campaign and has not been reused for
the new one.

## Stale stopped-campaign UI defect

On the running `fd16401` package, `/api/bootstrap/status` returned no active
campaign and the global header said Follow mode, while Settings still said
the old campaign was active and locked. The source's inactive branch in
`_bootstrapRenderStatus` updated the global/dashboard labels but left
`bootstrapStatusPanel`, the exact-asset checkbox, and a prior preview digest
untouched. The focused Chromium regression reproduced the defect before the
fix: the old active label and confirmation remained, and Start Campaign
became enabled from a stale preview.

Exact source commit `e259f7e8977866114a7ba13ad0be38463ee48c79`
clears the stale panel, preview digest/body, and asset confirmation only on
an active-to-inactive authoritative status transition. The regression passed
after the fix. An independent secondary-PC Chromium probe also confirmed that
an ordinary inactive-to-inactive poll preserves a fresh pending preview and
confirmation. It reviewed the exact two-file diff without a wallet action or
profile change.

## Verification and Windows artifacts

- Complete local Windows Python: **7,075 passed, 177 skipped, 422 subtests
  passed** in 1,243.30 seconds, with isolated test data.
- Complete Chromium E2E: **176 passed**. Affected Bootstrap API/UI tests:
  **24 passed**. Ruff on the changed Python test and `git diff --check` passed.
- All eleven PR checks passed on exact source commit `e259f7e`, including the
  GitHub unit-test job. PR #220 remains draft.
- Clean detached Windows build: `C:\catalyst\.superpowers\public-ready-e259f7e`.
  The packaged HTML SHA-256 matches the source HTML; the bundle has
  `.env.example` and no profile `.env`. PE product version is 1.4.0.
- EXE SHA-256:
  `4739D2F5115535E4EAC4CC438510EE4726B305912AD2DE8A357404602E4B24CB`.
- ZIP SHA-256:
  `006E8AF120D9B4C6E83C8F958F0E6018B62D33BF749A4BEF45F0CCC048692BF2`.
  It has 192 files, passed CRC, and its extracted EXE matched the build.
- Unsigned installer SHA-256:
  `3885D95FE38235985FA719908D7083BBC6E5B977F9B70551FED0F1695B0783C6`.
- Package API, synthetic Sage RPC, publication recovery, native first launch,
  duplicate launch, persisted relaunch, and safety fallback passed. The ZIP's
  extracted EXE passed API smoke. The installer completed a current-user
  isolated install; its installed EXE hash and registration matched. Installed
  API/native smokes passed, and uninstall removed the EXE and registration.
- ZIP and installer were committed to the acceptance artifact branch at
  `6039d367e2b3fb50fadd5af7f54ba4c2570a7104` and downloaded back over
  HTTP with matching complete-file hashes. They are acceptance packages, not
  a public release.

The exact downloadable artifacts are
`https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/CATalyst-e259f7e-secondary-acceptance.zip`
and
`https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/Catalyst-Setup-e259f7e-1.4.0.exe`.

The old `fd16401` app shut down with `cancel_offers=false` while the bot was
stopped and Sage/database had zero open offers. Eight critical profile files,
including the SQLite database and its WAL/SHM companions, were copied to
`C:\catalyst\.superpowers\primary-profile-pre-e259f7e-20260929-1139` and
each backup matched its source hash. The exact `e259f7e` EXE now owns port
5000 as PID 125028; its running hash matches the table. Read-only recovery
checks found the same campaign and expiry, mainnet fingerprint 736588221,
CAT wallet ID 2, exact MZ asset, a stopped bot, zero Sage/database offers,
consistent offer books, and safety allowed with zero blocker counts. The
prior fee approval remains at 62,703,765 mojos spent, zero held, and zero
unresolved operations. No new wallet transaction occurred during the
handoff.

The fresh `e259f7e` browser session shows Risk Disclosure and
`/api/fingerprint` reports `not_started`. The agent has not acknowledged it
or bypassed it via API. The operator was asked to personally acknowledge and
reconnect Sage. Coin Prep and offer creation require consequential wallet
handoff after their exact effects and fee scope are displayed. Primary and
secondary `e259f7e` live lifecycle and 24-hour windows remain unverified;
there is no public-readiness claim, merge, tag, or release.
