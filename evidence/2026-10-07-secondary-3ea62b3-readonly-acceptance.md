# CATalyst `3ea62b3` secondary-PC read-only acceptance

Date: 2026-10-07 (Europe/London)

Scope: exact-source, immutable-package, and native startup checks only. No wallet write, fee approval, campaign start, offer creation, cancellation, or primary TEST 7 profile access was performed.

## Identity and PR state

- Repository: `https://github.com/catalystxch/catalyst-bot.git`
- Requested source/runtime: `3ea62b34abaa8b4616e3294ec9f373d4ab8941b2`
- Detached checkout: exact match; clean working tree.
- `origin/pr/220` fetched at `6e005d90807b43212e5a51aefb66ef772fbc9773`.
- Git ancestry check: requested `3ea62b3` is an ancestor of the current PR head.
- GitHub API at 2026-10-07 05:09 BST: PR #220 open, draft, base `main`, head branch `codex/coin-prep-fee-approval`, mergeable `true`, mergeable state `unstable`.
- Commits after `3ea62b3` at inspection time were evidence-only (`2ad6e23`, `6e005d9`); the requested source/runtime remained `3ea62b3`.
- Exact commit check runs: 11 completed successfully (unit tests, lint/syntax, security scan, Semgrep, Gitleaks, CodeQL and language analyses).

## Exact-source verification

Canonical environment: Python 3.12.14 with repository-pinned `chia_rs 0.30.0`.

- `pytest -q tests/test_wallet_chia_authoritative_offer_history.py`: **18 passed** in 2.37 seconds.
- Ruff check: passed.
- Ruff format check: 2 files already formatted.
- `git diff --check HEAD^..HEAD`: passed.
- Related wallet/offer safety selection: **1006 passed, 374 subtests passed** in 255.46 seconds.
- Final checkout status remained clean and detached at the exact required commit.

An initial diagnostic run used the global Python 3.14 environment and produced 5 failures with 1001 passes. All five failures were reproduced alone and traced to the machine environment: global `chia_rs 0.38.2` rejects the repository's serialized consensus constants (`ConsensusConstants.from_bytes`: `ValueError: input buffer too large`). `requirements.txt` pins `chia_rs>=0.30,<0.31`. The same five tests passed under the canonical Python 3.12 / `chia_rs 0.30.0` environment, and the complete selection then passed. This is an attributable local environment mismatch, not a `3ea62b3` candidate failure.

## Immutable package verification

Artifact provenance commit: `406e6d77ad5c26ff549c839dd2eaab9e251f9b84`.

- ZIP: `CATalyst-3ea62b3-primary-acceptance.zip`
- Downloaded ZIP SHA-256: `DC633FF98BB94F3D0D90B898D229901B728A6E120335FCF44C1226F1352D9A71` — matches manifest.
- ZIP integrity: 192 entries, no CRC failure.
- Extracted `Catalyst.exe` SHA-256: `49A3DC1402FB6920702BAFD0A3338182AAF1F1E3ED9BAD6465F99699B6A42809` — matches manifest.
- Bundled `bot_gui.html` SHA-256: `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781` — matches manifest.
- File metadata: CATalyst 1.4.0; package is intentionally unsigned (`AuthenticodeStatus=NotSigned`).

## Isolated native checks

Isolated profile: `profile-native` under this evidence directory. The superseded idle e9 process PID 17760 was first verified by exact path/hash and closed gracefully to prevent singleton or port overlap.

Clean launch:

- Exact process PID 1156 launched from the extracted immutable package.
- It became the sole `Catalyst.exe` and sole `127.0.0.1:5000` listener.
- Main window title `CATalyst`; process remained responding.
- `/` returned HTTP 200 with the packaged CATalyst HTML.
- `/api/health` returned HTTP 200, version `1.4.0`, wallet type `sage`, bot stopped.
- `/api/status` returned bot stopped, no offers, zero balances, wallet not started, and runtime safety blocked with `WALLET_IDENTITY_BINDING_INVALID` rather than allowing effects.
- `/api/sage/startup-status` remained `idle` / wallet not started.
- Fresh-profile database counts were zero for offers, fills, fee approvals, approved fee reservations, Coin Prep operations, offer operations, publication outbox, reservations, Bootstrap campaigns, wallet-effect claims and wallet-effect dispatches.

Duplicate launch:

- Second PID 6908 exited normally with code 0 after 498 ms.
- Original PID 1156 remained responding and retained sole ownership of port 5000.

Persisted-profile relaunch:

- PID 1156 closed gracefully after more than three minutes without an unexplained exit.
- Exact package relaunched against the same isolated profile as PID 9192.
- PID 9192 became sole port 5000 owner, remained responding, retained the exact executable hash, and returned healthy local API responses.
- Persisted-profile runtime remained fail-closed: bot stopped, zero offers, no lease, and `WALLET_IDENTITY_BINDING_INVALID` until a wallet identity is visibly selected.
- PID 9192 remained alive and responding for 178.2 seconds, then closed gracefully. Its shutdown log completed normally.
- Both native-run logs contain zero matches for error, critical, traceback, unhandled, or exception indicators.
- Final process state: no `Catalyst.exe` and no port 5000 listener.
- Final isolated database state remained zero for every wallet-effect, offer, fill, fee, reservation, Bootstrap, publication, and operation table checked.

## Limitations and primary-PC observation

- Windows UI automation failed before exposing any window state on two attempts: `failed to write kernel assets: The system cannot find the path specified. (os error 3)`. No stale coordinates, guessed clicks, API bypass, or alternative custom UI automation was used.
- Therefore this run did not acknowledge Risk Disclosure, choose a Sage fingerprint, or traverse the visual pages. It did not reproduce the primary PC's specific first-process exit after successful Sage login because the comparable visible login sequence could not safely be performed.
- No local Application Error or Windows Error Reporting event for the exact package was observed during the isolated native checks.
- The primary PC's reported first-launch exit remains an open attributable limitation for final review; this secondary run neither reproduced nor disproved it.
- A full secondary original-profile wallet traversal, active-offer lifecycle, and long-duration stability trace were outside this delegated read-only isolated scope.

## Result

No defect was reproduced in the `3ea62b3` Chia pagination change or immutable package during the completed isolated checks. Source pagination and wallet/offer regressions pass in the pinned dependency environment; package identity, CRC, startup safety, duplicate handoff, graceful shutdown, and persisted-profile relaunch pass. Acceptance remains limited by unavailable Windows UI automation and the unresolved primary first-login exit observation.
