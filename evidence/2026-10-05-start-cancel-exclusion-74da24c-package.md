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

The older exact `b7eab4f` package completed a 24.0129-hour stopped-profile
observation with 1,419 clean samples and unchanged wallet balances, described
in `evidence/2026-10-04-safety-status-lock-b7eab4f-package.md`. That does not
certify the `74da24c` runtime or an active-offer window.

## Original TEST 7 read-only startup

After the completed older-build 24-hour snapshot, its stopped native window
closed without wallet cancellation. The exact `74da24c` EXE launched as sole
PID `161628` from
`E:\catalyst-74da24c-final-build\dist\Catalyst\Catalyst.exe`; its running
file still matched the EXE hash above and owned the only port 5000 listener.
The operator's prior testing authorization covered native Risk Disclosure;
the visible UI acknowledged it, selected Sage fingerprint `736588221`
(`TEST 7`), skipped starting Splash, preserved the existing configured
Spacescan key without changing it, and selected Monkeyzoo Token / XCH.
The bot remained stopped throughout.

Read-only API and direct Sage wallet-facade checks confirmed mainnet,
fingerprint `736588221`, CAT wallet ID `2`, exact asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
`138470301476875` confirmed/spendable XCH mojos, `780212284` confirmed/
spendable MZ atomic units, zero pending transactions, and a complete 4,095
record Sage offer history containing 3,326 cancelled, 231 expired, 538
completed, and zero fillable offers. The primary database had zero open MZ
offers and zero unresolved offer operations. Safety was ALLOWED with an owned
renewing lease, and `/api/bootstrap/status` showed no active campaign. The
prior campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remained stopped with zero authoritative fee spend and no Coin Prep fee
approval. The native dashboard showed the matching fingerprint and balances,
zero offers, RED market confidence due to expired/single-provider evidence,
and a disabled Start path.

An exact-PID/hash read-only monitor started at
`2026-10-05T21:43:05.4076486Z` with 60-second samples in
`E:\catalyst-stability-monitor-74da24c\trace-60s.jsonl`. Early samples had
ALLOWED safety, owned renewing lease, synced Sage, stopped bot, and zero open
offers. The exact-candidate 24-hour window cannot be counted until the full
trace is captured and audited.

The primary native window then completed a read-only traversal. Offers showed
zero active buy/sell offers and three historical confirmed buys. P&L showed
three confirmed buy legs, zero sells, zero realized P&L, and an unrealized
mark based on the displayed mid price. Market Intelligence showed Dexie ready,
Splash unavailable, Sage ready, and RED confidence. Settings Setup retained
the selected fingerprint and MZ/XCH pair; runtime safety was ALLOWED with zero
unresolved operations, reservations, or publications and an owned renewing
lease. Settings Live kept its controls disabled while the bot was stopped.
Logs backfilled Sage login, pair selection, and order-book refresh. Data Reset
described its confirmation-protected choices; no reset control was pressed.
Help and About rendered in the native window. Doctor passed nine checks with
one warning for the deliberately stopped optional Splash daemon. No settings
were saved and no trading control was activated.

The secondary PC independently completed exact pinned-EXE original Harvestr
read-only restart/UI traversal with mainnet fingerprint `3702373391`, CAT
wallet ID 2, the same MZ asset, unchanged balances, zero pending/fillable
offers, stopped bot, and ALLOWED safety. Its immutable report and JSON are
`evidence/2026-10-05-secondary-74da24c-original-profile-readonly.md` and
`.json`. Native computer-use was unavailable there, so UI traversal used
Playwright Chromium against the exact sole localhost package process.

Primary and secondary active-offer lifecycle/recovery, the exact final-package
stability windows, and final release review remain open. No new campaign,
fee approval, offer, or wallet transaction was made for this package
acceptance.
