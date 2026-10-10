# Bootstrap authority start gate and exact 244da2e acceptance

Draft PR #220 remains open against `main`. Exact runtime/source is
`244da2eb49cd89351647b999a8996fd9a6bc07ff`.

## Defect and fix

`/api/bot/start` could fall through to the legacy start gate when the durable
active Bootstrap campaign read failed or returned two active campaigns. The
route then reported success and called `bot.start()` without authoritative
campaign selection. Two isolated red regressions reproduced HTTP 200 before
the fix. The route now returns bounded `BOOTSTRAP_AUTHORITY_UNAVAILABLE` (503)
for a failed read or campaign identity parse and
`BOOTSTRAP_AUTHORITY_AMBIGUOUS` (409) for multiple active campaigns. Both
responses occur before `bot.start()`; an empty active set retains the ordinary
start path. Neither response discloses exception details.

The affected route file passed 45 tests and four subtests; Ruff check,
format, and diff check passed. All 11 exact-source PR checks passed, including
unit tests. An independent two-worker full local Windows backend run found
7,192 passed, one skipped, 431 subtests and two failed tests. Those two
existing CodeQL start tests assumed an empty campaign set without isolating
the durable campaign read; they therefore encountered the new fail-closed
503 before reaching their warning and Coin Prep assertions. Test-only child
`c7915af` explicitly supplies an empty campaign set in both fixtures. The
two focused tests then passed. The fresh four-worker full local Windows
backend suite on child `c7915af` passed **7,194 tests, one skipped, 431
subtests** in 12m46s. The packaged runtime source remains `244da2e`.

## Exact Windows package

Built from a clean detached worktree at the source commit. No live wallet
profile was used for package tests.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-bootstrap-authority-244da2e-build\dist\Catalyst\Catalyst.exe` | `DC9D916C1BC574A32E5B42C63AE713C864C3E6C2151D9078EAA33C7F87F65BB4` |
| Bundled `_internal\bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-244da2e-primary-acceptance.zip` | `9D4002CE178C7343FC9B96EBDE548BED46E971E785FCF409E9C5AA45EE1A8280` |
| Unsigned `Catalyst-Setup-244da2e-1.4.0.exe` | `1B68682B2C3D5DB8FEE6CCE85CCEDD7A04FE7BEAD8BADFA15FE9139CF7B372DC` |

Packaged API, synthetic Sage RPC, interrupted publication recovery, native
clean/duplicate/persisted/safety smokes, 192-file ZIP CRC, extracted EXE hash
and API smoke passed. A unique-AppId QA installer passed clean install,
installed EXE hash and API smoke, and uninstall without touching the existing
production registration. Defender custom scans found zero attributable
detections. Independent HTTP downloads of the pinned ZIP and installer
matched the hashes. Acceptance artifacts are pinned at
`codex/coin-prep-fee-approval-artifacts` commit
`944ba711e897325c8a2133b1d177a6a981b2fd49`.

## Original TEST 7 profile, read-only restart

The stopped `1ef4799` app shut down through its native UI with cancel offers
unchecked. The exact new EXE started as the sole verified Catalyst process
(PID 109832 at inspection) and sole port 5000 owner. Its process file hash
matched the build. Risk Disclosure was acknowledged under the operator's
existing testing authorization. The native startup selected TEST 7 Sage
fingerprint `736588221`, skipped the stopped Splash node, continued with the
configured Spacescan key, and selected the MZ/XCH pair.

Read-only API and UI checks found mainnet, CAT wallet ID `2`, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138.470301476875 spendable XCH, 780212.284 spendable MZ, a synced Sage
wallet, stopped bot, inactive Bootstrap campaign, zero open offers, ALLOWED
runtime safety and zero blockers. The UI showed offer-book confidence RED
because attributable market depth was insufficient; no trade was attempted.
Balances and offer count matched the prior candidate. No campaign, fee
approval, offer, or wallet transaction was created.

## Stopped-profile heartbeat failure and fresh restart

Later read-only monitoring of the same stopped process found runtime safety
blocked with `HEARTBEAT_FAILED`, zero durable blockers, zero open offers, the
same balances and inactive Bootstrap. Its last durable heartbeat was
`2026-10-04T18:01:30.749034Z` and its stored expiry was
`2026-10-04T18:02:00.749034Z`: the full intended 30-second lease had been
stored, but no renewal succeeded before expiry. Sage logged three connection
timeouts at 18:01:56 UTC. The proximity is evidence of a host or service
interruption, not proof of its cause. The native UI correctly displayed
"Start blocked by safety: Lease heartbeat failed". This **fails the live
stability window** and is not counted as a safety pass beyond fail-closed
containment.

With the bot stopped and offer cancellation unchecked, the fenced app closed
through its native UI. It left zero Catalyst processes and zero port 5000
listeners. The same exact-hash EXE restarted as sole process PID `145356`.
Native startup again acknowledged Risk Disclosure under the operator's
existing testing authorization, selected TEST 7 fingerprint `736588221`,
skipped stopped Splash, continued with the configured Spacescan key, and
selected MZ/XCH. Fresh read-only checks found unchanged balances, zero open
offers, inactive Bootstrap, stopped bot and ALLOWED safety with a renewing
lease. This begins a new observation window; recurrence under ordinary load
requires investigation before public readiness.

The route failure cases were injected only in isolated tests, never into the
original TEST 7 profile. Live offer lifecycle, active-offer recovery, both
24-hour stability windows, independent secondary live acceptance, and final
review remain open. PR #220 stays draft; this is not a public-readiness claim.
