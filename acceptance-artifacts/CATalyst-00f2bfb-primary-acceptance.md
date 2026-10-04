# CATalyst 00f2bfb primary acceptance package

Draft PR #220 exact source/runtime: `00f2bfb3416fbcf2fb68743fc48b09adbb1c6ce0`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `7152FB6C1EEAA2B05728048246810787F11859A349DCF31A974192D9AA67EC00` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-00f2bfb-primary-acceptance.zip` | `280E7C2B17708A46B3173314CB984517B1407F324CCA6538C3200092D267BAD6` |
| `Catalyst-Setup-00f2bfb-1.4.0.exe` | `35D1D6F8ADD20BAF6B56F1E1A9846D2C7F3FD43DE1DB93EFDD2E1BAFA9FD3FA6` |

The bot start route formerly continued after an unexpected pending Setup
configuration check or reload failure. Red/green regressions confirm that
both errors now return bounded `CONFIG_RELOAD_FAILED` without starting the
bot. The full local Windows backend suite passed 7,187 tests and 431
subtests, with 212 skipped. Ruff check, format and diff checks passed. The
bundled UI is unchanged from the 211-pass Chromium candidate.

The 192-entry ZIP passed CRC and exact EXE/UI presence checks. The detached
EXE passed packaged API, synthetic Sage RPC, interrupted publication recovery,
and native clean/duplicate/persisted/safety smokes. A unique-AppId current
user QA installer passed installation, installed EXE hash and packaged API
smoke, and uninstall. Its EXE and QA registration were absent afterward.

The original TEST 7 profile is still running the previous `b78ce49` package
with a stopped bot. Exact `00f2bfb` live restart, mainnet offer lifecycle,
both 24-hour windows, and final review remain open. PR #220 stays draft.
