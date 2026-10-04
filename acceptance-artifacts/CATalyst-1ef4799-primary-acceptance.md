# CATalyst 1ef4799 primary acceptance package

Draft PR #220 exact runtime/source: `1ef47998a43ddf9bae9083717bd0ce4e9a6002d5`.
Test-only child: `f4b10861e27c883b6b53cd5e215b7afdc3376c5d`.
This unsigned package is for acceptance testing, not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `BE189E996F28EDC830BBBBDB3179B468C3CD9F316E1FFE9D862A99C1AC0F9105` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-1ef4799-primary-acceptance.zip` | `8467C9C10965C29BBA5291E690D41D7F7A3B5A52F9C703BFD79102C26C5EB6B1` |
| `Catalyst-Setup-1ef4799-1.4.0.exe` | `0D45A4156B083EDAE2199A56ACF9A5CCF913EEB363B91A3038DBCE4C5EA31974` |

The bot start path formerly skipped tier-size drift or Coin Prep state checks
when those checks raised. The drift helper also swallowed tier-target and
designation read errors as an empty finding list. Exact source `1ef4799`
requires complete evidence for this start gate and returns bounded
`tier_size_drift_check_failed` or `coin_prep_gate_check_failed` without
calling `bot.start()` when it cannot verify readiness. The ordinary drift
helper retains its existing best-effort behavior for other callers.

Red/green regressions and adjacent tests passed. The full Windows backend
suite on the exact runtime source with the test-only child passed **7,192
tests**, **431 subtests**, and skipped 212. Ruff check/format and diff checks
passed. The bundled UI is unchanged from the 211-pass Chromium candidate.

The 192-file ZIP passed CRC. The clean detached EXE passed packaged API,
synthetic Sage RPC, interrupted publication recovery and native
clean/duplicate/persisted/safety smokes. A unique-AppId current-user QA
installer passed installation, exact EXE hash and installed API smoke, then
uninstalled with its EXE and registry registration absent. Defender scans
found zero detections attributable to this package.

Original-profile read-only restart for this exact candidate, live offer
lifecycle, both 24-hour windows and final review remain open. PR #220 stays
draft.
