# Coin sizing readiness fails closed — exact 1ef4799 package

Draft PR #220 exact runtime/source is
`1ef47998a43ddf9bae9083717bd0ce4e9a6002d5`. Test-only child
`f4b10861e27c883b6b53cd5e215b7afdc3376c5d` supplies complete tier
inputs to the fresh-price route test. PR #220 remains draft.

## Finding and correction

The bot start route previously continued into `bot.start()` when its legacy
Smart Settings tier-size drift check or Coin Prep state check raised. The
standalone drift helper also interpreted failed tier-target or designation
reads as an empty drift list. That could authorize offers using coin sizes
that the app had not verified. Route regressions reproduced both fail-open
paths as HTTP 200 before the fix.

The start route now requests strict drift evidence and blocks with bounded
`tier_size_drift_check_failed` or `coin_prep_gate_check_failed` if a check
cannot complete. The strict helper raises on unreadable tier targets,
missing target sizes or designation reads. Other callers retain their
existing best-effort behavior. The route does not log injected sensitive
exception text. The original fresh-price route test had no reversed-buy
tier values and had passed only because the earlier helper skipped the
missing target; its test-only correction proves both buy and sell sizes are
computed before asserting a successful start.

Focused tests passed 59 tests and four subtests. The complete local Windows
backend suite on exact runtime source with the test-only child passed
**7,192 tests**, **431 subtests**, with 212 skipped. Ruff check/format and
diff checks passed. The bundled UI is unchanged from the 211-pass Chromium
candidate.

## Clean detached Windows package

The build worktree `E:\catalyst-start-gates-1ef4799-build` was detached at
exact source `1ef4799`. `python build.py` and ISCC with the explicit 1.4.0
version produced:

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `BE189E996F28EDC830BBBBDB3179B468C3CD9F316E1FFE9D862A99C1AC0F9105` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-1ef4799-primary-acceptance.zip` | `8467C9C10965C29BBA5291E690D41D7F7A3B5A52F9C703BFD79102C26C5EB6B1` |
| Unsigned `Catalyst-Setup-1.4.0.exe` | `0D45A4156B083EDAE2199A56ACF9A5CCF913EEB363B91A3038DBCE4C5EA31974` |

The 192-file ZIP passed CRC. Packaged API, synthetic Sage RPC, interrupted
publication recovery, and native clean/duplicate/persisted/safety smokes
passed. Unique-AppId QA installer
`{AD2A2245-91CB-424D-B28C-C4BB91E5CF17}` installed to an isolated E:
directory with exact EXE hash; the installed EXE passed packaged API smoke.
Uninstall returned 0 and removed the QA EXE and unique registration. The
existing production installer registration was untouched. Defender scans
found zero detections attributable to this package.

The ZIP and installer are pinned on
`codex/coin-prep-fee-approval-artifacts` at
`d4f8e81066ca951e6b98fb79dbcf23f27ae4d056`. Independent HTTP downloads
of both pinned files matched the hashes above.

## Original TEST 7 read-only restart

Before replacement, the exact `00f2bfb` package was the sole CATalyst
process and port 5000 owner with bot stopped, zero open offers, inactive
Bootstrap, ALLOWED safety, and unchanged 138.470301476875 XCH and
780212.284 MZ balances. The native shutdown dialog's cancel-offers checkbox
remained unchecked; the app closed gracefully. Process and port listener
counts reached zero before launching the exact `1ef4799` EXE.

The native Risk Disclosure was acknowledged under the operator's existing
testing authorization. The visible Sage picker selected TEST 7 fingerprint
`736588221`, stopped optional Splash was skipped, configured Spacescan
continued, and the Dashboard selected Monkeyzoo Token `MZ_XCH`. The resulting
sole PID `141824` and port 5000 owner used the exact EXE path/hash above.
Read-only API and direct Sage checks found mainnet, fingerprint `736588221`,
CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
the same XCH/MZ balances, zero open offers, zero pending transactions,
inactive Bootstrap, stopped bot and ALLOWED runtime safety. No campaign,
fee approval, offer, transaction or data reset was made. The injected
readiness failures were verified in isolated tests, not induced on this
original wallet profile.

Live offer lifecycle, both 24-hour stability windows and final review remain
open; this package does not establish public readiness.
