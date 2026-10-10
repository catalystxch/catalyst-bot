# Exact-source Windows package checkpoint — 28 September 2026

**Superseded checkpoint.** A narrow-window regression was found after this
build: initial focus on Continue scrolled past the risk disclosure. The
subsequent source correction requires a new package and fresh verification.
All results below apply only to `4be34ae`; they do not pass the final candidate.

## Candidate and automated checks

- Source commit: `4be34ae9f5de592751c87db4db2a37b3f1162bbc` on
  `codex/coin-prep-fee-approval`, PR #220. The PR remains draft.
- The clean detached Windows build at
  `C:\catalyst\.superpowers\public-ready-4be34ae` succeeded from that commit.
  `build.py` normalized only line endings in `_version.py` while stamping
  1.4.0; `git diff --ignore-space-at-eol` was empty. The generated change was
  restored after the build, leaving the detached checkout clean.
- The complete Chromium E2E suite passed **168 tests in 92.99 seconds**. The
  three new UI regressions each failed on the prior behavior and passed after
  correction. Ruff check passed repository-wide; format verification passed
  all **479 tracked Python files**; `git diff --check` passed.
- The complete Python suite and final PR unit CI were still running at this
  checkpoint. Their outcomes must be added before final review.

## Windows artifacts

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| Executable | `C:\catalyst\.superpowers\public-ready-4be34ae\dist\Catalyst\Catalyst.exe` | `775E1B41F687CC341C6C1136FAAEE7E4BF624C5C265B950EA7E1AA2A5F3A608A` |
| ZIP | `C:\catalyst\.superpowers\public-ready-4be34ae\CATalyst-4be34ae-public-ready.zip` | `64B452D7E340F7ACAB283D4F68A1AF993B982353B812F6B3AAE6AF9D29BDF048` |
| Test installer | `C:\catalyst\.superpowers\public-ready-4be34ae\Output\Catalyst-Setup-1.4.0.exe` | `2E669500DD71CEBFC26CE0D00288E7D62CA102EB26FFAEA9C9DF0ACD5B936F02` |

The ZIP has 206 entries and is 37,310,088 bytes. It contains no `.env`,
database, log or Coin Prep runtime state file. Its extracted executable hash
matches the built executable. The executable is 11,247,841 bytes; the test
installer is 38,366,503 bytes. Both Windows version resources say 1.4.0.
They are unsigned, consistent with `docs/CODE_SIGNING_POLICY.md`'s current
unsigned-beta process. These are local test artifacts, not a public release.

## Packaged and installer checks

- Packaged API, synthetic Sage RPC, interrupted publication/upgrade recovery,
  and native clean launch, duplicate launch, persisted relaunch and safety
  smokes passed from the build directory.
- The ZIP was extracted to a new directory; packaged API smoke passed again
  from the extracted executable.
- Inno Setup 6.7.3 compiled the test installer with 1.4.0 metadata.
- The installer completed a clean current-user installation in an isolated
  directory. The installed executable hash matched the built package;
  registry version and Start Menu shortcuts matched the installer. Native
  clean/duplicate/persisted/safety smoke passed from the installed location.
- A locally compiled installer from the prior `d048f44` package replaced that
  isolated installation and installed the exact prior executable hash. The
  `4be34ae` installer then replaced it with the exact new executable hash;
  native smoke passed again. This checks same-version replacement and rollback
  mechanics, not an actual version-number upgrade or public download.
- The isolated installation was uninstalled successfully; its executable and
  current-user uninstall registration were removed. The live CATalyst process
  and user profile were not touched by these package checks.
- Microsoft Defender real-time protection was enabled (signature version
  1.459.440.0). A custom scan of the exact installer and a byte-identical
  copy marked with Internet-origin ZoneId=3 completed with zero detections.
  The marked copy retained the installer SHA-256 above. This simulates an
  Internet-origin download; it is not an actual website download.

Logs are in the detached build directory as `public-readiness-build.log`,
`.tmp-packaged-*-smoke.log`, `.tmp-extracted-zip-api-smoke.log`,
`.tmp-installed-desktop-smoke.log`, `.tmp-upgraded-desktop-smoke.log`, and
`.tmp-*-installer-*.log`.

## Live and remaining gates

At 11:32 UTC, the prior exact `d048f44` live process remained PID 19568 at
its verified executable path and SHA-256. `/api/health` reported a running bot,
reachable and synced Sage wallet, zero consecutive failures. The active
Bootstrap campaign still bound mainnet Sage fingerprint 736588221, wallet 2,
the exact MZ asset, revision 0, the 0.0000375–0.00015 XCH/MZ corridor,
0.9 XCH/12000 MZ budgets, 10% deployment and 5% loss stop. Its six offers
remained three buys and three sells, with unique nonreserve coins, no wallet
only or stale rows, and an allowed safety lease with every blocker count zero.
Coin Prep remained complete with six confirmed fee operations, 60,190,086
mojos spent, zero held, zero unresolved operations and 501,670,604 mojos
remaining of the displayed 561,860,690-mojo cap. The active log contained
no ERROR/CRITICAL, traceback, signature failure or duplicate-spend hit.
The old package is intentionally preserved for its original stability window.

The `4be34ae` package has **not** yet replaced that live process or completed
its own live lifecycle or 24-hour window. The secondary PC is independently
building and testing this exact commit while its original `d048f44` monitor
continues. Actual website download, final update path, new-candidate primary
and secondary live acceptance, 24-hour stability, and final review remain
open. No merge, tag, upload or release was performed.

An attempted isolated background launcher for additional primary interactive
UI inspection was rejected by automatic command approval review with only
"blocked by policy" as the stated reason. Packaged smokes and the complete
Chromium suite passed; independent secondary packaged UI review is underway.
