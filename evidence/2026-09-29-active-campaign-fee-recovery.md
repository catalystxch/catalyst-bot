# Active-campaign Coin Prep fee recovery — 29 September 2026

## Live read-only reproduction

The primary `3cb506de5defb41e8772d0460e0467c7acf5133a` Windows EXE was
running with its bot stopped. Active mainnet Bootstrap campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
had zero Sage and database open offers. No new Coin Prep had run for it.
Nevertheless, read-only `GET /api/coin-prep/status` returned that active
campaign ID together with fee approval
`c6651480f6044dbbd2833926d3809380c248943f7f507991ff132d7e885e6bdc`
from expired prior campaign
`aaf64855aef9e1919d7cdfd4b15c1f589e7acf9321d71787b0b8122df9e16405`.
It also returned `overlapping_coin_prep_blocked=true` and
`fee_resume_required=true`. The old approval was `approved`, with
62,703,765 mojos spent, zero held, and zero unresolved operations. No wallet
action was taken during reproduction.

The independently reviewing secondary PC traced the stale ID to the
persistent worker status file. The backend resolved the latest approval for
the active campaign, but retained the worker ID when that lookup returned
none. The browser evaluated fee recovery before checking campaign identity,
so a reload could offer the prior campaign's recovery controls. Durable
dispatch validation remained campaign-bound; this was an availability and
misleading-recovery defect, not proof of unauthorized spending.

## Correction and regression

Exact source commit `1db16bd3bed145334fe9463664b7d633426709cb`
clears a worker-file approval whenever an active Bootstrap campaign exists,
then uses only that campaign's durable approval lookup. If the lookup fails,
status blocks overlapping Coin Prep and reports
`fee_approval_lookup_unavailable`, without exposing the old approval ID.
The browser also rejects a blocking approval whose campaign ID differs from
the active campaign before it opens recovery UI or starts polling.

Two backend regressions and one Chromium regression were written first.
Each failed against the prior behavior for the expected mismatch or missing
block, then passed after the correction. The complete Chromium suite passed
**177 tests**. The affected Coin Prep status class passed **16 tests**.
The complete local Windows Python suite passed **7,077 tests, 178 skipped,
422 subtests** in 1,132.16 seconds. Ruff lint, Ruff formatting of changed
Python files, and `git diff --check` passed. All eleven PR checks passed on
the exact source commit, including unit tests and security scans. The
secondary PC independently approved the exact four-file source/test diff
and did not touch its profile or wallet.

## Exact Windows package checkpoint

Clean detached checkout `C:\catalyst\.superpowers\public-ready-1db16bd`
was built from the exact source commit above. PyInstaller succeeded and
verified bundled HTML and CA certificates. Source and packaged HTML each
have SHA-256
`303DC06F277C6375410E33D1120315B14577D997963B44B1968F67874C237322`.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `15F6F4AAA205EF3CF4A91C85434E0C793779A06B03908F497339B32BFBE30ECF` |
| `CATalyst-1db16bd-primary-acceptance.zip` | `E1168D16F6EFA706D2E50DBE478042FD9F661E3FC524C1281F96EE690C5C0237` |
| `Output/Catalyst-Setup-1.4.0.exe` (unsigned) | `873FFD92F2DC5B13BE7951F846A8C45D48F7B9B709BD7644E44F7B9992EB02F6` |

The ZIP contains 192 files, passed CRC, includes `.env.example`, and
contains no profile `.env`, SQLite database, or Coin Prep status file. Its
extracted EXE hash matched the built EXE and passed isolated API smoke.
The built EXE passed isolated API, synthetic Sage RPC, and
upgrade/publication recovery smokes. Inno Setup 6.7.3 built the unsigned
installer. Isolated current-user clean install placed the exact EXE hash
under `C:\catalyst\.superpowers\install-1db16bd-acceptance`; registration
reported v1.4.0 and the isolated directory. Installed API and native
clean/duplicate/persisted/safety smokes passed. Uninstall returned zero
and removed the EXE and current-user registration. A separate isolated
same-version sequence installed prior `3cb506d`, replaced it with `1db16bd`,
rolled back to `3cb506d`, and restored `1db16bd`. Each installed EXE hash
matched its selected package; final uninstall again removed EXE and
registration. No primary live profile or wallet effect occurred.

The ZIP, installer, and checksum sidecars were pushed to the separate
acceptance-artifact branch at
`934eaae25eebd7ba21912113317d0c0563e0c97a`. Independent HTTP
downloads of both complete artifacts matched the local hashes above.
These are acceptance artifacts, not a public release.

- ZIP: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/CATalyst-1db16bd-secondary-acceptance.zip`
- Installer: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/Catalyst-Setup-1db16bd-1.4.0.exe`

## Primary handoff status

Before handoff, PID 87740 still owned port 5000 with the verified old
`3cb506d` EXE hash. It reported bot stopped, the exact unexpired mainnet
campaign and wallet identity, zero Sage/database offers with a consistent
book, safety allowed with all blocker counts zero, and no active browser
fingerprint. The stale cross-campaign Coin Prep status above remained
reproducible in this old runtime.

The old stopped process was then closed with zero open offers. Port 5000
closed. All eight critical original-profile files, including SQLite WAL and
SHM, were copied and SHA-256 matched into
`C:\catalyst\.superpowers\primary-profile-pre-1db16bd-20260929-1856`.
The source and backup `bot.db` SHA-256 was
`60438F12AF5AB858E4DEDA9C0C2F28DBC7A11E714ED8F987B46F6FC6FBD8867B`.

The attempt to start the new exact EXE through the command tool was
**rejected by automatic approval review before execution**, with reason
`blocked by policy`. A subsequent read-only check verified no CATalyst
candidate process, no listener on port 5000, the intact eight-file backup,
and the new EXE's unchanged SHA-256. Therefore there is **no live `1db16bd`
verification** yet. The operator must start the exact EXE; the app's Risk
Disclosure must still be personally acknowledged before Sage connection.
No wallet action occurred during this handoff. The active campaign's trading
lifecycle and 24-hour stability gates remain unverified. PR #220 remains
draft; no main merge, tag, release, or public-readiness claim has occurred.
