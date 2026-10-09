# Coin Prep terminal stop proof (`aba6667`)

## Defect and correction

`/api/coin-prep/trigger` called `bot.stop(wait=True)` but tested only
`bot.is_running()` afterward. `BotLoop.stop()` can clear `_running` while its
cycle and Splash shutdown are still in progress, then return `False` if the
wait expires. The route could therefore begin a wallet mutation with the bot
still in `stopping`. Manual `/api/coins/topup` and `/api/coins/prep` used the
same insufficient `is_running()` guard.

The routes now require `BotLoop.is_stopped()`, a lifecycle-only predicate that
holds `_state_lock` and checks both `_running == False` and
`_bot_state.status == "stopped"`. A trigger that interrupted a running bot also
requires `stop(wait=True) is True`. The manual routes reject `stopping` with
409; the trigger rejects an incomplete stop with 503. The predicate avoids the
full dashboard `get_state()` collector, whose unrelated statistics reads can
fail or block even when the lifecycle state is valid.

Source commit: `aba66676628e364ca25cc6529999fcd1c34a93b8` on
`codex/coin-prep-stop-proof`. The preceding correction `84c86f1` used
`get_state()` for this proof; independent secondary review found that
unnecessary reliability coupling, so it is not the final candidate.

## Verification

- Red regressions observed HTTP 200 for incomplete/already-stopping trigger
  and manual top-up/prep during `stopping`. The same tests passed after the fix.
- Additional red regression observed HTTP 500 after an unrelated GUI statistics
  failure in the first fix; `is_stopped()` passed without reading those stats.
- Primary affected suite: 385 passed. Positive manual-route cases and focused
  lifecycle proof passed. Ruff check, Ruff format and Git diff check passed.
- Full serial primary Windows backend: **7,570 passed, 261 skipped, 457
  subtests passed** in 1,270.74 seconds, exit code 0.
- Secondary independent review: no findings on `aba6667`; 16 focused tests,
  Ruff/format/diff check passed. Review evidence remains on the secondary PC.
- Secondary isolated exact-source package acceptance passed: independent
  Windows build, synthetic Sage, packaged API, native first launch and
  duplicate/persisted/safety states, and a black-box negative Coin Prep route
  check with zero mutating mock-Sage calls. Its separate EXE hash is
  `E3F3E36895E8A2FFEE9C3AB21C2B5E18382F708FF0063A2EE8F8F1B29BD16389`;
  no reproducible-build claim is made. Secondary report:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\acceptance-aba6667-package-20261009T2120BST\REPORT.md`,
  SHA-256 `5D5A95F9F4D7077400780E9DD27E33BFC6DD67F614E2A1A4AC8FC268B6951F65`.

## Clean detached Windows package

Built from exact `aba6667` in
`C:\catalyst\.superpowers\coin-prep-stop-aba-build`.

| File | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `F57F93F17B3E6981DDE1178A7C42798A019FC1C5CF24C2888F98CBDDE44E8E25` |
| bundled `bot_gui.html` | `125FCB4CE9B68B4363C8E227ED29FDD6604CE6559A0950ABF16783AB03DBCA4B` |
| `CATalyst-aba6667-primary-acceptance.zip` | `EEDB6CF353E5B44B19CAE3449961DFA5F316EC83CA580A9B45B61AEE2ED72407` |
| unsigned `Catalyst-Setup-1.4.0.exe` | `69FC6E34F579444725567D47602643793E658838A083B22FBE1083F3FD07944A` |

The ZIP has 192 unique safe entries and a clean CRC check. Directory-package
API, synthetic Sage RPC worker and upgrade publication recovery smokes passed.
The extracted ZIP's packaged API and synthetic Sage RPC worker also passed
against an alternate port and temporary profile. Isolated unique-AppId
current-user installer install/uninstall passed, with 192 installed source
bundle files hash-matched and the isolated registration removed. Defender
custom scans of the EXE, ZIP and installer completed without candidate-tied
detections. Manifest `SHA256SUMS-aba6667.txt` SHA-256:
`294C7A4FF37E0FD7A858D111CF1564BEAB71259347E8E6B5E8927A5BF9319AEA`.

This package is not yet the PR #220 candidate. PR integration and CI,
immutable artifact publication and HTTP hash audit remain open.
Original-profile live testing remains on prior source
`0534103`; no wallet effect was made for this fix. No 24-hour credit transfers
between source candidates. PR #220 stays draft.
