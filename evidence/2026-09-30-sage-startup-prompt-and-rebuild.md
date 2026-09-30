# Sage startup prompt and exact Windows rebuild — 30 September 2026

## Applicable secondary finding

The independent Harvestr acceptance task reproduced a startup change-address
prompt on current main even though `/api/config` returned
`SAGE_SET_CHANGE_ADDRESS=true`. The exact PR #220 source had the same
lowercase-only `sage_set_change_address` check. The correction from PR #229
prefers the canonical uppercase key, retains the lowercase compatibility key,
and accepts boolean or string `true`. Its browser regression passed on this
branch with `--e2e`; the complete Chromium suite passed **178 tests**.

PR #230 corrected four calendar-sensitive tests on current main. This branch
already used `_recent_authority_times()` for its two fill-history cases, so
their cherry-pick conflict was resolved by retaining that existing helper.
The two Bootstrap tests gained a frozen clock. All four affected backend tests
passed. The complete Windows backend suite passed **7,080 tests, one skipped,
422 subtests** in 1,156.40 seconds. Ruff check and format on changed Python
files and `git diff --check` passed. Exact source commit:
`b4a3daf715ff11477329648cb6a37e41e1a18c7d`. Runtime changes from the
prior exact candidate are limited to the Sage startup prompt check. All eleven
PR checks passed on this exact source commit, including unit tests, lint,
CodeQL, Semgrep and secret scanning.

## Detached Windows package

A clean detached worktree at
`C:\catalyst\.superpowers\public-ready-b4a3daf` built the executable from
that source commit. The build verified bundled HTML and CA certificates.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `CF7661D91A56B3A86CFE6535456CAAA06A41419DA6ECC7CA821C6B7C7BBC2137` |
| `CATalyst-b4a3daf-primary-acceptance.zip` | `3B983DFB64969B3B9D6AAA5080AFC0760A5F215212E0D3FC8AC3E9B185186B09` |
| `Output/Catalyst-Setup-1.4.0.exe` (unsigned) | `31CE37CC2E0D5CFB94C0F5080B11E76F4645CA6FFE85EC5F3F47314ED068FDA1` |

The detached executable passed packaged API, synthetic Sage RPC, upgrade and
publication recovery, and native clean/duplicate/persisted/safety smokes.
The 206-file ZIP passed CRC and contained the EXE and `.env.example` but no
profile `.env`, database, log, or Coin Prep status file. The extracted EXE
matched the built hash and passed packaged API smoke. A silent, isolated
current-user installer test installed an EXE matching the built hash; installed
API and native smokes passed. Uninstall removed the installed EXE and its
registration. Neither the isolated package nor installer tests used the
primary CATalyst profile or created a wallet transaction.

The ZIP, installer and checksum sidecars were pushed to the acceptance-artifact
branch at `7f59dd49a9d2d014056034094931c2086e32004e`. Independent HTTP
downloads of both complete artifacts matched the hashes above. These are
acceptance artifacts, not a public release.

- ZIP: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/CATalyst-b4a3daf-primary-acceptance.zip`
- Installer: `https://raw.githubusercontent.com/catalystxch/catalyst-bot/codex/coin-prep-fee-approval-artifacts/acceptance-artifacts/Catalyst-Setup-b4a3daf-1.4.0.exe`

## Live boundary

The exact `b4a3daf` candidate has not run against the primary live profile.
The previous approved PR campaign expired at
`2026-09-30T11:27:42.748405Z` without candidate wallet effects or a campaign
fee approval. The TEST 7 wallet was released by the separate QA task and a
14:51 UTC read-only preflight showed the exact mainnet identity, zero active
offers, zero primary database open offers and no pending transactions.
Automatic approval review previously rejected a command-tool launch of the
predecessor candidate against the live profile before execution, reason
`blocked by policy`; that launch has not been retried through another tool.
No replacement campaign has been approved, and Risk Disclosure must be
personally acknowledged in any new live session. Primary and secondary exact
candidate Coin Prep, offer lifecycle, restart recovery and 24-hour stability
gates remain open. PR #220 remains draft; no main merge, tag, release, or
public-readiness claim follows from this evidence.

## Independent secondary-PC review

The secondary task independently verified the exact source commit and that
the branch's next head changed only these acceptance documents. It downloaded
the ZIP and installer and matched both hashes above, extracted the EXE and
matched its hash, and confirmed bundled `bot_gui.html` was byte-for-byte equal
to the exact source (SHA-256
`8EAEAB212D29F16A4773D516FFBB73BA05941AEADE8FB4D8C845CF4E626EC597`).
The EXE reported version 1.4.0.0, was unsigned as expected, and a Defender
custom scan reported zero detections. Its patch review found no new defect.
Focused checks passed: one saved-setting Chromium regression, four
calendar-sensitive backend cases, and 39 fee approval, public readiness,
navigation, reset and browser-console checks. Ruff, formatting and diff
checks passed. The secondary report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\2026-09-30-b4a3daf-independent-readonly.md`
(SHA-256 `FFEA1D47D88105F63592D2CA2047A752675199DFAD2E8216675394C879B5369B`).

The secondary platform rejected direct startup of the downloaded exact EXE
before process creation with `blocked by policy`; the task did not route
around it. Therefore it could not repeat packaged API/native/Sage runtime on
that PC. Its independent Harvestr profile was preserved, the bot was stopped,
ports 5000/4000/4001 were closed, and it made no wallet transaction or fee
approval. The package has no embedded source commit or acceptance manifest;
exact hashes, source/build records, and bundled UI parity are the available
provenance evidence. Secondary package-runtime and live lifecycle gates remain
open.
