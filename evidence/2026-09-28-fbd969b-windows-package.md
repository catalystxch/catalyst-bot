# Windows package checkpoint for source fbd969b — 28 September 2026

**Superseded checkpoint.** A later startup-wallet-choice keyboard test showed
that focus could still escape after the risk screen. The source correction
requires a fresh package and acceptance; the results below apply only to
`fbd969b`.

## Exact identity

- Source commit: `fbd969b9fcb27e79e292860ec4dbe5777534def7`.
- Branch: `codex/coin-prep-fee-approval`; PR #220 remains draft.
- Built in a fresh detached checkout at
  `C:\catalyst\.superpowers\public-ready-fbd969b` on 28 September 2026
  around 11:40 UTC. `build.py` passed. Its version stamp changed only line
  endings in `_version.py`; the semantic diff was empty and the checkout was
  restored clean after building.

| Artifact | Location | SHA-256 | Bytes |
| --- | --- | --- | ---: |
| EXE | `C:\catalyst\.superpowers\public-ready-fbd969b\dist\Catalyst\Catalyst.exe` | `AC484416AC82062D063F54FA5F060ED871103AD28582B4DD04C6E585ADD6CD43` | 11,247,841 |
| ZIP | `C:\catalyst\.superpowers\public-ready-fbd969b\CATalyst-fbd969b-public-ready.zip` | `C514902EB76BBA6529587A87FE8599F2A736DF6005939E1C849F41099ABE47E3` | 37,309,917 |
| Test installer | `C:\catalyst\.superpowers\public-ready-fbd969b\Output\Catalyst-Setup-1.4.0.exe` | `9C4FE335C1F379CFA6D30376E24B2A319AFEE83E430215ADE05B6A508E38D261` | 38,365,486 |

The ZIP contains 206 entries and no bundled `.env`, SQLite database, log or
Coin Prep runtime-state file. Its extracted EXE hash matches the build. EXE
and installer Windows product versions are 1.4.0. Both are unsigned, as
allowed for an explicitly labelled beta by `docs/CODE_SIGNING_POLICY.md`.
These are local test artifacts, not published downloads.

## Verification passed

- Four focused UI regressions passed after each was shown failing for the
  intended reason before its correction. The complete Chromium E2E suite
  passed **169 tests in 98.18 seconds**.
- Ruff check passed repository-wide, Ruff formatting verification passed
  **479 tracked Python files**, and `git diff --check` passed.
- Packaged API, synthetic Sage RPC, interrupted-publication/upgrade recovery,
  and native clean-launch, duplicate-launch, persisted-profile relaunch and
  safety smokes passed. API smoke also passed from the extracted ZIP.
- Inno Setup 6.7.3 compiled the exact test installer. A clean current-user
  installation in an isolated directory installed the exact EXE hash;
  registration and version were correct. Native smoke passed from that
  installed directory. The locally compiled prior `d048f44` installer then
  replaced it with the exact prior EXE hash; this candidate's installer
  reinstalled the exact new hash and native smoke passed again. Uninstall
  removed the isolated EXE and its current-user registration. This verifies
  same-version replacement and rollback mechanics, not a real version-number
  upgrade or official website download.
- A byte-identical installer copy marked with Internet-origin ZoneId=3 kept
  the exact installer hash. Defender real-time protection was enabled; its
  custom scan completed with zero detections. This is a simulated download.

Build, smoke and installer logs are in the detached checkout as
`public-readiness-build.log` and `.tmp-*.log` files.

## Outstanding at this checkpoint

The complete serial Python suite and PR unit CI were still running when this
file was drafted. The secondary PC is independently building and testing this
exact source commit while preserving its old `d048f44` monitor. The primary
live bot remains on verified `d048f44`, not this package. Both original
24-hour windows, new-candidate live lifecycle and 24-hour evidence, real
wallet confirmation/recovery checks, independent secondary acceptance,
actual website download/update evidence and final code review remain open.
No merge, tag, upload or public release occurred.
