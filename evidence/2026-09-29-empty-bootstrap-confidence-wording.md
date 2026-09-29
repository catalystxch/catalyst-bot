# Empty Bootstrap book confidence wording — 29 September 2026

## Defect and correction

The exact `e259f7e8977866114a7ba13ad0be38463ee48c79` primary runtime
was stopped with an active, unexpired Bootstrap campaign and zero Sage and
database open offers. Both books agreed. The dashboard's RED-confidence
next-step text nevertheless said, “Follow exposure withdrawn; bounded
Bootstrap offers remain active.”

`renderMarketConfidence` selected that phrase solely from the presence of
`_bootstrapActiveCampaign`. Campaign authorization does not prove offer
existence. The authoritative Bootstrap status carries `open_offer_count`,
which was zero in this state. The source commit
`3cb506de5defb41e8772d0460e0467c7acf5133a` changes the non-expired
fallback to “Follow exposure withdrawn; bounded Bootstrap campaign remains
authorized.” The existing expired-campaign block still takes precedence.
The wording is truthful with zero, positive, or temporarily unknown offer
counts, without assuming that an active campaign has live wallet offers.

The focused Chromium regression explicitly set `open_offer_count: 0`. It
failed against the old phrase and passed after the one-line change, along
with the adjacent expired-campaign test. The full Chromium suite passed
**176 tests** in 89.94 seconds. Ruff check and format verification on the
changed Python test passed, as did `git diff --check`. The complete local
Windows Python suite passed **7,075 tests, 177 skipped, 422 subtests** in
1,147.01 seconds. Repository-wide Ruff lint passed and all **480 tracked
Python files** passed Ruff format verification. All eleven PR checks passed
on exact source commit `3cb506d`, including the unit-test job. The independent
secondary PC reviewed the exact pushed commit and found no issue. It did
not touch its profile or wallet.

## Exact Windows package checkpoint

The clean detached checkout at
`C:\catalyst\.superpowers\public-ready-3cb506d` built from exact source
commit `3cb506de5defb41e8772d0460e0467c7acf5133a`. Its packaged HTML
SHA-256 equals the source HTML SHA-256:
`0DFDF28B2CE39EE2911950E341AF8E0B7B00FF79A941E1423BFC66FDAF12F15B`.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `44573CD86B02AA383459AD274E601BE514C765778AC39DC60A0297B0173441BE` |
| `CATalyst-3cb506d-primary-acceptance.zip` | `06C5C96944A38FB854772AB8A5EAD52C0F9BBB51A8ED0BFEBE80EE6179836A83` |
| `Output/Catalyst-Setup-1.4.0.exe` (unsigned) | `F9B552BB5DA3C741DB7E9994CF66946399401DF865C97870CA9D38C0E6ED4611` |

The ZIP has 192 entries and passed its CRC check. Its extracted EXE hash
matched the built EXE; the extracted package passed API smoke. The built
package passed isolated API, synthetic Sage RPC, and publication/upgrade
recovery smokes. An initial native duplicate-launch smoke timed out after
10 seconds while full backend tests and ZIP/installer compression were
running concurrently. A subsequent isolated native run passed clean first
launch, duplicate handoff, persisted relaunch, and safety fallback. No
runtime/source defect was identified from the timed-out run.

Inno Setup 6.7.3 compiled the unsigned installer. It installed in an
isolated current-user directory; the installed EXE hash matched the build,
the registration reported v1.4.0 and the isolated directory, and installed
API and native smokes passed. Silent uninstall returned zero and removed
both the installed EXE and current-user registration. The primary live
runtime and profile were not changed by package tests.

The exact prior `e259f7e` installer was then installed into a separate
isolated directory. The new `3cb506d` installer replaced it, the prior
installer rolled it back, and the new installer restored the current
candidate. At each step the installed EXE hash matched the selected
package (`4739D2F5…` prior, `44573CD8…` current). Final uninstall again
removed the executable and current-user registration. This is a
same-version replacement/rollback check, not a public update.

The ZIP, installer, and their SHA-256 sidecars were pushed to the
acceptance-artifact branch at
`87cfb45e113512e47be330c33a0e8bec2143d29d`. Independent HTTP
downloads of both complete artifacts matched the local hashes above.
Neither artifact is a public release. The ZIP contains `.env.example`
but no profile `.env`, database, or runtime logs.

- ZIP: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/CATalyst-3cb506d-secondary-acceptance.zip`
- Installer: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/Catalyst-Setup-3cb506d-1.4.0.exe`

The exact `e259f7e` live app remained PID
125028 with its prior verified executable hash, bot stopped, and zero
authoritative Sage/database offers. Therefore this new source/package has
**no live wallet acceptance yet**. PR #220 remains draft; no main merge,
tag, or public release has occurred.
