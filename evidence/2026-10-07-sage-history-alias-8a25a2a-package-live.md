# Sage historical-offer alias authority: exact package and primary live read-only acceptance

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `8a25a2ad5178b8a17d85ee27819a1d50711e9350`. This is an
intermediate acceptance record, not public-readiness approval.

## Defect and correction

Sage coin asset inference looked up a coin's offer in full local offer history.
It previously used `trade_id or offer_id` on each row. If both aliases were
present but disagreed, or one alias was malformed, a matching first alias
could still supply an asset ID to an offer-locked coin. This was separate from
the filtered open-offer identity gate in source `310dcc3`.

Two red cases reproduced asset inference from conflicting and malformed
aliases on `310dcc3`. Exact `8a25a2a` normalizes both aliases, requires valid
64-character hexadecimal identity and same-row agreement, and treats any
targeted ambiguous history row as disqualifying even beside a valid row.
Compatible case and `0x` encodings remain accepted.

## Source and independent verification

- Primary focused regressions: **5 passed**. The exact full serial Windows
  backend passed **7,336 tests, 241 skipped,
  436 subtests passed** in **1,597.92 seconds**. Related Sage and coin modules
  passed **30 tests and 9 subtests**. Ruff check, Ruff format check and diff
  whitespace check passed. All **11 PR checks** passed on exact source.
- The secondary PC independently reproduced two unsafe parent behaviors and
  found all five targeted cases safe on `8a25a2a`. It passed **329 offer
  reconciliation tests**, **116 wallet/coin tests and 24 subtests**, and **283
  mutation-safety tests**, with Ruff and a clean diff check. Its independent
  Windows build and disposable-profile native clean, duplicate and persisted
  smokes passed without original-wallet effect. Secondary local EXE SHA-256:
  `846892735A590B92AFC4DBF1D9BE3B980C69E01DA535579B94F54F916605851D`.
  The secondary report SHA-256 is
  `20824307152DFC60CA5CF09CBD8EE7C73AE245BC48754657AE4F26CE6386FB75`.
  Its local binary is not the primary immutable artifact.
- A direct read-only Sage alias audit of the current 4,095-offer history found
  4,095 valid rows and no malformed, conflicting or duplicate aliases. The
  synthetic regressions establish fail-closed behavior if this changes.

## Detached primary Windows package

Built from clean detached checkout
`E:\catalyst-sage-asset-8a25a2a-build` at exact source `8a25a2a`.
Generated version metadata was the only tracked build change.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `77BD81AE90634FF9C2564C36F54065DB1804894BA942761FA7082F5980CA7B95` |
| Bundled `bot_gui.html` | `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781` |
| ZIP | `48D0106FFD4304CADC8B98426862A88EA23F3FD38AC60A3ECCAA27D9B5F99AC3` |
| Unsigned installer | `34C1D053E46EB8F4F50E7779F3A804851A74B5D82BA2A256D281A2CA7BA7182B` |

Packaged API, synthetic Sage RPC, publication recovery and native clean,
duplicate, persisted-profile and safety smokes passed. ZIP CRC passed across
206 entries, with embedded EXE/UI hashes matching the detached build. An EXE
extracted from an independently downloaded pinned ZIP passed the packaged API
smoke.

A unique-AppId isolated QA installer installed to a dedicated E: directory.
Its EXE hash matched the detached build; installed API and synthetic Sage
smokes passed. Its silent uninstaller exited zero and removed its EXE and
registry entry. The original current-user installation registration was
absent. Defender real-time protection remained enabled; scans of the bundle,
ZIP and unsigned installer left the six pre-existing detections unchanged.

ZIP, installer and manifest were pinned at artifact commit
`1273c8802e8a3d4867d1e2836f89d40991359ff8`. Independent HTTP downloads
of the ZIP and installer matched local SHA-256. The downloaded manifest's Git
blob ID matched the pinned commit; checkout line endings differ from the raw
blob. Pinned links:

- [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1273c8802e8a3d4867d1e2836f89d40991359ff8/acceptance-artifacts/CATalyst-8a25a2a-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1273c8802e8a3d4867d1e2836f89d40991359ff8/acceptance-artifacts/Catalyst-Setup-8a25a2a-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1273c8802e8a3d4867d1e2836f89d40991359ff8/acceptance-artifacts/SHA256SUMS-8a25a2a.txt)

## Original TEST 7 live read-only acceptance

The stopped `310dcc3` predecessor shut down through the native UI with wallet
cancellation unchecked. It had zero open offers. Exact `8a25a2a` launched as
the sole `Catalyst.exe` process and port-5000 owner, PID `143556`, from
`E:\catalyst-sage-asset-8a25a2a-build\dist\Catalyst\Catalyst.exe`; the running
EXE hash matched the detached artifact. Testing Risk Disclosure was
acknowledged under the operator's standing authorization. The native startup
selected Sage mainnet TEST 7 fingerprint `736588221`, skipped optional Splash,
used Spacescan Free Tier and selected Monkeyzoo Token MZ/XCH.

The app reported CAT wallet ID `2`, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138.470301476875 XCH and 780212.284 MZ, stopped bot, synced Sage, zero open
offers, safety `ALLOWED`, an owned renewing lease and inactive Bootstrap. Direct
Sage mTLS reads before and after native UI traversal found the same balances,
zero pending transactions and 4,095 terminal offers (3,326 cancelled, 231
expired, 538 completed), with zero nonterminal offers. Native read-only
Dashboard, Offers, P&L, Market Intel, Settings, Logs, Data Reset view, Help
and About opened. No setting was saved, data reset, bot started, campaign
created, offer made or fee spent. The app was left on Dashboard.

The prior campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remains stopped and bound to this mainnet wallet and asset. Its authoritative
fee spend is zero and no Coin Prep approval exists. The old `c665...` approval
is invalid for a new campaign. No new campaign was started.

`E:\catalyst-stability-monitor-8a25a2a-clean\monitor.ps1` began a read-only,
exact-PID/hash stopped-profile trace at `2026-10-07T07:05:06.9528201Z` in
`trace-60s-clean.jsonl`. Its initial three samples were clean: process alive,
safety allowed, owned lease, Sage synced, bot stopped and zero open offers.
The 24-hour gate cannot pass before `2026-10-08T07:05:06Z` plus a complete
trace and end-state audit. The preceding candidate's shorter trace is
historical evidence only.

Live active-offer lifecycle and recovery, secondary original-profile live
acceptance, both final-candidate 24-hour windows and final review remain open.
Keep PR #220 draft; no merge, tag, release or public-use claim.
