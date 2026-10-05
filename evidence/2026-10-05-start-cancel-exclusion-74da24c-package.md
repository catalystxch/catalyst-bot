# Exact 74da24c combined cancellation package

The exact runtime/source is `74da24c34c0e107ff4c4bf9be7a719e8ae3777d0`.
The feature-branch head `4915c301dedd0fa392965d59f7fe653a2f20393f`
changes only tests/evidence after that runtime. PR #220 remains draft.

The wallet-wide Cancel All route now holds the same lifecycle lock as the
final bot-start transition while it verifies a stopped bot and reserves its
worker. Start fails closed with `CANCEL_ALL_IN_PROGRESS` if cancellation is
active or its status cannot be read. Shutdown cancellation waits for settled
bot stop; a settled blocked state with `running: false` can proceed to the
wallet-wide recovery step while diagnostic errors remain visible. Unknown or
still-running states remain blocked.

Windows exact-source validation: `python -m pytest -q tests` completed with
**7,218 passed, 224 skipped, and 431 subtests passed** in 1,442.87 seconds.
The complete Chromium suite passed **223** tests. Repo-wide Ruff check and
format checks passed. The 74da package passed packaged API, synthetic Sage
RPC, interrupted-publication recovery, and native clean/duplicate/persisted/
safety startup smokes. ZIP CRC and extracted API passed. A unique-AppId QA
installer clean install, installed API smoke, and uninstall passed without
touching the existing installation. Defender scans found no new detection.

| Exact artifact | SHA-256 |
| --- | --- |
| Clean Windows `Catalyst.exe` | `C03A78147CDAA3532F6F103E46328DEA53F6FF3B41F51F3FEA1E8134709B4664` |
| Bundled `bot_gui.html` | `2778E110E3E358D05E6E84E9EE8645AD71233FCDCB9D396BD219D62D4774D6F5` |
| Acceptance ZIP | `7120A8B1490D8EE551210F57372FF8BA65637A9CA1698796559758C0215334AB` |
| Unsigned installer | `DBC2F3BE0710F5749A99A86D134FD73C938C87D4381438244853FCC37A3C469A` |

The ZIP and installer are pinned at artifact commit
`7b90d6dca999eec6a3e28083037b581484255b01`; independent HTTP downloads
of both matched the SHA-256 values above:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7b90d6dca999eec6a3e28083037b581484255b01/acceptance-artifacts/CATalyst-74da24c-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7b90d6dca999eec6a3e28083037b581484255b01/acceptance-artifacts/Catalyst-Setup-74da24c-1.4.0.exe)

This exact package has not run against the original TEST 7 profile. The
older exact `b7eab4f` package completed a 24.0129-hour stopped-profile
observation with 1,419 clean samples and unchanged wallet balances, described
in `evidence/2026-10-04-safety-status-lock-b7eab4f-package.md`. That does not
certify the `74da24c` runtime or an active-offer window. Primary and secondary
active-offer lifecycle/recovery, the exact final-package stability windows,
and final release review remain open. No new campaign, fee approval, offer,
or wallet transaction was made for this package acceptance.
