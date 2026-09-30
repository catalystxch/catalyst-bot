# Coin Prep mode-switch provenance and Windows acceptance — 30 September 2026

## Defect and correction

A separate TEST 7 Sage QA task, using isolated v1.3.21 source/profile, observed
that a confirmed, wallet-owned XCH `replacement` output remained free and
classified as an inner tier spare, but its database `purpose` became null after
a sell-only preparation. A subsequent two-sided start made one sell and no buy.
That QA task repaired only its isolated database after proving coin ownership,
then made and securely cancelled one buy and one sell. Those wallet effects and
fees are not PR #220 candidate or campaign evidence.

Review of the exact PR #220 source found two paths to the same provenance loss:
`run_full_preparation()` parked all free database coins before direct-batch
pricing, hiding still-owned reusable coins, and the final designation sweep
temporarily parked coins while clearing their validated output purpose.
The gone-to-free upsert also cleared that purpose. Commit
`f41e4d49008b5f8106058f3bfd5a1c9d9e83ac63` moves the pre-run full park
behind terminal direct-batch handling, so it applies only to the legacy
consolidation path. The final sweep still parks free coins before an
authoritative wallet rescan, but this preparation-specific park retains their
validated purpose. A returning exact coin ID keeps that purpose while its
designation and tier reset for classification. Ordinary disappearance and
permanent spending continue to clear purpose; absent coins remain gone.

Three isolated regressions cover ordinary disappearance, direct-batch timing,
and sell-only final-sweep reappearance. The latter also proves that a retained
replacement purpose can count after tier-spare reclassification. Two new tests
failed against the old source for the observed reasons, then all three passed
after the correction. The wider affected set passed 171 tests. The complete
local Windows Python suite passed **7,080 tests, 178 skipped, 422 subtests** in
1,086.05 seconds. Chromium E2E passed **177 tests**. Ruff lint, Ruff format,
and `git diff --check` passed. All eleven PR checks passed on the exact source
commit, including unit, lint, CodeQL, Semgrep and secret scanning.

The independent secondary acceptance task reviewed the immutable
`27788cb..f41e4d4` patch and found no source-visible correctness or security
defect. Its review confirmed that the purpose-retention flag is keyword-only
and false for ordinary callers, terminal/spent protections remain, and direct
dispatch has no accidental path into the relocated legacy park. The reviewer
flagged live persistent-state mode-switch acceptance as still desirable. The
secondary profile and wallet were not modified for this review.

## Detached Windows package

A clean detached checkout at
`C:\catalyst\.superpowers\public-ready-f41e4d4` was built from the exact
source commit. PyInstaller succeeded and verified bundled HTML and CA
certificates. The ZIP contains 192 files, passed CRC, contains `.env.example`,
and contains no profile `.env`, `bot.db`, or Coin Prep status file. Its
extracted EXE matched the built EXE and passed isolated API smoke.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `CB4B35F86FCA5C722FEE0F9CC4DA2FB29E98BE96B71510CD11E90FCD2CB46522` |
| `CATalyst-f41e4d4-primary-acceptance.zip` | `0AE3EDA475DA71D1D74974A4388582FF737A6BE0709C58389F50F2B2A30DF7A7` |
| `Output/Catalyst-Setup-1.4.0.exe` (unsigned) | `5FE86583622A14A4D7F9F7E945A7392B8E1976329924E44EB19CC72B57563142` |

The detached EXE passed isolated packaged API, synthetic Sage RPC, upgrade and
publication recovery, and native clean/duplicate/persisted/safety smokes. The
installer passed an isolated current-user clean install: the installed EXE
matched the built hash, version and path registration were correct, and
installed API/native smokes passed. Uninstall returned zero and removed the
EXE and registration. A separate same-version sequence installed prior
`1db16bd`, upgraded to `f41e4d4`, rolled back to `1db16bd`, and restored
`f41e4d4`; every installed EXE matched its expected source-package hash.
Final uninstall removed its EXE and registration. All these smokes used
isolated data; none touched the primary profile or TEST 7 wallet.

The ZIP, installer and checksum sidecars were pushed to the separate
acceptance-artifact branch at `81ca655`. Independent HTTP downloads of the
complete ZIP and installer matched the local hashes above. These are
acceptance artifacts, not a public release.

- ZIP: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/CATalyst-f41e4d4-primary-acceptance.zip`
- Installer: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/Catalyst-Setup-f41e4d4-1.4.0.exe`

## Live acceptance boundary

At 14:51 UTC, the other TEST 7 task had authoritatively cancelled its 48
offers and released that wallet. Secondary acceptance was using an independent
Harvestr wallet, not TEST 7. A new read-only check through the exact source
wallet facade found Sage `mainnet`, fingerprint `736588221`, CAT wallet ID 2
with the exact MZ asset, and a complete 4,095-record offer history with zero
active offers. The primary database also had zero open MZ offers. Sage reported
138,470,301,476,875 confirmed and spendable XCH mojos and 780,212,284 MZ
atomic units, with no pending transactions. There was no CATalyst process or
port 5000 listener. This establishes a free wallet for future preflight, not
an exact-candidate live lifecycle result.

The approved PR #220 Bootstrap campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
expired at `2026-09-30T11:27:42.748405Z` without exact-candidate wallet
effect or fee approval. Its prior-campaign approval must not be reused.
The campaign remains persisted as `active` but is past its exact expiry, with
zero authoritative campaign fee spend and no campaign fee approval. No new
campaign has been approved. Automatic approval review previously rejected a
command-tool launch of the predecessor exact EXE against the primary profile before execution,
with reason `blocked by policy`; this task has not retried that live launch
through another tool. The exact `f41e4d4` package has **not** run against the
primary live profile. Its Coin Prep, offer lifecycle, restart recovery and 24-hour live
windows remain unverified. PR #220 stays draft; no main merge, tag, release,
or public-readiness conclusion follows from the passing isolated checks.
