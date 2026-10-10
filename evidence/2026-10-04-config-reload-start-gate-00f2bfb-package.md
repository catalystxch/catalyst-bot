# Pending Setup reload failure blocks bot start — exact 00f2bfb package

Draft PR #220 remains open and draft. The exact runtime/source commit is
`00f2bfb3416fbcf2fb68743fc48b09adbb1c6ce0`. This candidate has not yet
run against the original TEST 7 profile.

## Finding and fix

`/api/bot/start` checked for pending restart settings and reloaded config
before starting the trading loop. Unexpected errors from either operation
were only logged; execution then continued to `bot.start()`. A stale
configuration could therefore trade even though a pending Setup change had
not been applied. Logging the raw exception could also expose sensitive
configuration text.

Two parameterized route regressions reproduced the fail-open behavior before
the fix. The route now returns HTTP 503 with bounded reason
`CONFIG_RELOAD_FAILED` and does not call `bot.start()` if the pending check or
reload throws. The new regressions passed after the change. The focused test
file passed 14 tests; adjacent bot lifecycle and config reload tests passed
58 tests and four subtests. The complete local Windows backend run passed
**7,187 tests**, **431 subtests**, and skipped 212. Ruff check, format and
diff checks passed. The bundled UI is unchanged from the 211-pass Chromium
candidate.

## Clean detached build and isolated verification

The clean detached worktree is `E:\catalyst-config-reload-00f2bfb-build` at
exact source `00f2bfb`. `python build.py` and ISCC compiled the EXE and
unsigned production installer. Hashes:

| File | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `7152FB6C1EEAA2B05728048246810787F11859A349DCF31A974192D9AA67EC00` |
| `dist/Catalyst/_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-00f2bfb-primary-acceptance.zip` | `280E7C2B17708A46B3173314CB984517B1407F324CCA6538C3200092D267BAD6` |
| `Catalyst-Setup-1.4.0.exe` | `35D1D6F8ADD20BAF6B56F1E1A9846D2C7F3FD43DE1DB93EFDD2E1BAFA9FD3FA6` |

The 192-entry ZIP passed CRC and included the exact EXE and bundled UI.
Packaged API, synthetic Sage RPC, interrupted publication recovery, and
native clean/duplicate/persisted/safety smokes passed. A QA installer with
unique AppId `{3DE66A81-9EAC-415A-BD54-9CF130AC6038}` installed under
`E:\catalyst-config-reload-00f2bfb-build\QAInstall`, with an EXE matching
the clean build hash. The installed EXE passed packaged API smoke. Silent
uninstall returned 0, and the QA EXE and unique registry registration were
absent afterward. The existing production installation was untouched.

Defender custom scans of the bundle, ZIP and installer completed with zero
detections attributable to this build. The ZIP and installer were pinned on
`codex/coin-prep-fee-approval-artifacts` at
`4b6a4c064a0a51a8acabd47a35eb92d36b9f8082`; independent HTTP downloads
of both pinned files matched the hashes above.

At the preflight check, the original TEST 7 process was still the earlier
`b78ce49` EXE, PID `115676`, with the bot stopped. No new campaign, offer,
fee approval, or wallet transaction was made by this package verification.
The exact-candidate original-profile restart is recorded below. Live offer
lifecycle, both 24-hour windows and final review remain open. PR #220 stays
draft.

## Original TEST 7 read-only restart

The previous stopped `b78ce49` process was the sole CATalyst process and
port 5000 owner before shutdown. Its UI showed no active Bootstrap campaign;
the shutdown dialog's offer-cancellation checkbox stayed unchecked. It
closed through the native Shutdown App action, after which CATalyst process
and port 5000 listener counts both reached zero.

The exact `00f2bfb` EXE was launched from the clean detached build. Its
native Risk Disclosure was acknowledged under the operator's existing
testing authorization. Sage detected an open wallet. The native picker
displayed TEST 7 fingerprint `736588221`, which was selected. The stopped
optional Splash node was skipped and the configured Spacescan key was used.
The fresh Dashboard required explicit pair selection; the native UI selected
Monkeyzoo Token `MZ_XCH`.

The resulting sole PID was `144664`, with the exact EXE path and SHA-256 above
and one port 5000 listener owned by the same PID. Read-only API checks showed
Sage phase `ready`, fingerprint `736588221`, healthy synced wallet, mainnet,
CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138.470301476875 XCH and 780212.284 MZ, bot stopped, zero open offers,
inactive Bootstrap, and runtime safety allowed with zero blockers. An
independent read-only wallet facade call found zero pending Sage transactions
and the same fingerprint. The
previous package's balances were identical. No campaign, fee approval,
offer, transaction, or other wallet financial effect was made by this
restart. The injected config-reload failure path was verified in isolated
tests, not induced on the original wallet profile. Live offer lifecycle,
both 24-hour windows and final review remain open.
