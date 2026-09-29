# Expired Bootstrap recovery UI: candidate `fd16401`

## Defect and correction

The exact `bf1abe2` package was running against the primary mainnet profile
with its bot stopped and its approved Bootstrap campaign expired. Sage and
CATalyst each reported six open offers (three buys and three sells), and Start
was correctly disabled. The restored-session panel nevertheless called the
book "ready to resume" and instructed the operator to press Start Bot. Market
Health called bounded Bootstrap "active." After session load, the recovery
modal also offered **Start Bot Now**. The backend start gate still rejected an
expired campaign; the defect was misleading frontend guidance.

The frontend treated every non-null `_bootstrapActiveCampaign` as usable in
those messages, without consulting the existing expiry/cancellation block.
Commit `e406abbe518c52f74afc8c3720081fcc19f78c2c` uses that block to
describe required cancellation in the restored overview, Market Health, and
post-load modal. The expired modal offers a route back to the dashboard rather
than a Start action; the main Start button is no longer briefly enabled by
session recovery when the start gate denies it. Active, unexpired Bootstrap
messaging is preserved.

Independent secondary review found that the disabled restored-session CTA
still said **Resume Bot Now** when a pair was selected. The focused regression
was extended with a selected MZ pair, failed against `e406abb`, and passed
after commit `fd164015b23e7740c784f0916e5f428fa7772b29` changed that
disabled CTA to **Cancel Offers Before Restart**. The secondary independently
verified this exact follow-up diff and its active/expired behavior: nine
focused Chromium tests and two adjacent recovery tests passed. It found no
further contradictory wording or reportable security finding in the reviewed
surfaces. Its original profile and backup remained intact; no wallet effect
was performed.

Three Chromium regressions first failed against the previous wording/action,
then passed after the correction. The additional selected-pair CTA assertion
also failed before `fd16401` and passed after it. The complete Chromium suite
passed **175** tests against `fd16401`. Ruff check and format check on the
changed Python test file, and `git diff --check`, passed. All eleven PR CI
checks passed on exact source head `fd16401`; the unit job reported 7,061
passed and 190 skipped. The complete local Windows Python suite passed
**7,075** tests, with **176 skipped** and **422 subtests passed**, in
1,108.56 seconds against the final source. The test run used an isolated
`CMM_DATA_DIR` and did not touch the primary profile.

## Exact Windows artifacts

Built cleanly from detached `fd16401` checkout
`C:\catalyst\.superpowers\public-ready-fd16401`. The bundle contains the
source-identical `bot_gui.html` and no profile `.env`; Windows resources report
1.4.0. The artifacts are unsigned acceptance packages, not a public release.

| Artifact | SHA-256 | Bytes |
|---|---|---:|
| `dist\Catalyst\Catalyst.exe` | `4455ABD51C6FE787FD424F2F8D38FF815DDE1A6A2D277A0F649BAD39AAE9C291` | 11,252,534 |
| `Output\CATalyst-fd16401-secondary-acceptance.zip` | `E61643E36C9CB998783E9D4870D21087CE640851717270A018C27498FB26C63C` | 36,569,391 |
| `Output\Catalyst-Setup-1.4.0.exe` | `1FCC71A5AC692202A58AB3BE0D9726C3681C9555FD494091E530685C7F56B19C` | 38,371,462 |

The ZIP has 192 files, passed CRC verification, contains the exact EXE hash,
and has `.env.example` but no `.env`. Both ZIP and installer were downloaded
from the artifact branch over HTTP and their complete byte streams matched
the table. Artifact branch head: `43ba48cf40025a27287dc90cb4c6c58d483b51f8`.
The downloadable files are
`https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/CATalyst-fd16401-secondary-acceptance.zip`
and
`https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/Catalyst-Setup-fd16401-1.4.0.exe`.

## Package and installer acceptance

- Packaged API, synthetic Sage RPC worker, and upgrade/publication recovery
  smokes passed in isolated profiles.
- The acceptance ZIP was extracted into an isolated directory. Its EXE hash
  matched the table and its packaged API smoke passed. The isolated extraction
  remains at `C:\catalyst\.superpowers\zip-fd16401-test` because automatic
  approval review rejected recursive cleanup; no live profile was affected.
- Packaged native clean launch, duplicate launch, persisted-profile relaunch,
  and safety smoke passed.
- The unsigned installer completed a current-user clean install in an isolated
  directory. Its installed EXE hash and registration matched. Installed API
  and native smokes passed; uninstall removed the EXE and registration.
- A separate installer sequence verified `fd16401` clean install, rollback to
  `e406abb`, restoration of `fd16401`, installed API smoke, and final
  uninstall. Each phase's installed EXE hash and success log matched its
  expected candidate. No CATalyst installer registration remains. The earlier
  `bf1abe2` to `e406abb` upgrade/rollback/restore sequence passed before the
  secondary-requested CTA follow-up.
- Microsoft Defender real-time protection was enabled with signature version
  1.459.456.0. A custom scan of the exact `fd16401` installer completed,
  the installer retained its expected hash, and no matching Defender
  detection was reported for that path.

## Live and release gates

The primary live application was **not** replaced during these checks. It
remains the exact `bf1abe2` EXE (PID 64944 at this checkpoint), with the bot
stopped. Its mainnet Sage fingerprint is 736588221, CAT wallet ID 2 and MZ
asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
The expired campaign
`aaf64855aef9e1919d7cdfd4b15c1f589e7acf9321d71787b0b8122df9e16405`
still had six open offers and `/api/offers/cancel_all/status` was idle on the
latest read-only check. A protected Cancel All confirmation is open in the
user's browser. Computer-use policy requires the user to perform the final
consequential wallet action; standing authorization does not waive that
handoff. No cancellation or new campaign was initiated for this change.

The secondary PC completed bounded independent source review and focused UI
tests without wallet actions or package downloads. Primary and secondary live
lifecycle and 24-hour windows for `fd16401` remain unverified. PR #221's CAT
spare-tier fix (`922ae5b`) and PR #222's duplicate-window fix (`54f5f33`)
are both ancestors of this source commit. Four unresolved automated PR review
threads describe `api_server` imports in tests as unused; each import is
annotated `noqa: F401` because it establishes blueprint import order. They
were inspected but not changed during this frontend correction. Draft PR #220
must remain unmerged, untagged and unreleased pending the live gates and final
review.

## Read-only offer expiry checkpoint, 2026-09-29 09:20 UTC

All eleven checks passed on the later evidence-only PR head
`0a45f6140ddb8dbfe35b84a36c471ab2a1743784`; the PR remains draft.
The primary bot was still stopped, and protected Cancel All remained idle.
One of the six offers still marked open in CATalyst's database had reached its
durable `expires_at` of `2026-09-29T09:19:11+00:00`. Direct read-only Sage
`get_offer` returned `expired` for inner buy
`6fe38e0f59c687d4bfd24857725ba25e55eff0ebffda58622be0ec00c89f297f`.
The other five offers returned `active`. `/api/offers/diagnostic` reported two
wallet buys and three wallet sells, three DB buys and three DB sells, and that
exact trade ID in `stale_in_db`, with no `wallet_only` rows or wallet error.
This is an observed wallet expiry, not proof of a fill or completed local
reconciliation. The stopped-bot Cancel All path snapshots only wallet-active
offers; the proof-bound re-prep preflight can examine terminal DB rows later.
Neither cancellation nor re-prep was run at this checkpoint. The operator's
protected Cancel All confirmation remains a required handoff, and all final
wallet and ledger outcomes still need verification.
