# Coin Prep status privacy and exact Windows package

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) remains open against `main`.
The exact runtime/source commit is `196caa890ebf97ed08435ac492edd6edd553f9e9`.

## Finding and correction

A pinned security diff review of the prior head `9680f974ec4fade289129868da810058ee4d0a1e` found one low-severity information exposure: unauthenticated `GET /api/coin-prep/status` returned durable fee-approval identity and accounting when present. The route was absent from the private-read allowlist even though comparable status routes required the local API credential. An isolated Flask test-client reproduction returned 200 for that route without a credential while `/api/status` returned 401.

A regression first failed with the unexpected 200. The correction adds `/api/coin-prep/status` to `_PRIVATE_READ_ROUTES`; the test now verifies unauthenticated 401 and credentialed 200. Existing Coin Prep success tests now present the credential. The focused selection passed 84 tests, and the lifecycle/crash selection passed 50. The packaged API was also checked directly: unauthenticated status returned 401 and token-authenticated status returned 200.

The complete serial local Windows backend passed **7,434 tests, 246 skipped, and 455 subtests** in 23 minutes 44 seconds. The isolated Chromium suite passed **245 tests**. Ruff, format, and `git diff --check` passed. All **11 PR checks** passed on the exact source head, including unit tests, CodeQL, Semgrep, and secret scanning.

## Exact detached Windows package

Built from a clean detached checkout at `E:\catalyst-auth-read-196caa8-build`. Only build-stamped `_version.py` was modified by the build. The package is unsigned acceptance evidence, not a public release.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `B350C448350961613A3C57020AC66D992F7FDD319036629CAABA009DD376A8E9` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `676776A0ACF3C9D3DF9077C9497CE9C5A7C6A338EB4B8DFC61291575FA535C02` |
| Unsigned installer | `C1E3550885287EF0BA33C85A0EF5752C6D574F0A4B8BE3CA97AB5FBF5C07CBFF` |

Packaged API, synthetic Sage RPC worker, interrupted-publication recovery, and native clean/duplicate/persisted/safety launch smokes passed. The ZIP has 192 files, passed CRC, contains the exact EXE, and its extracted app passed the API smoke. A unique-AppId current-user installer QA run performed clean install, installed API/Sage checks, and uninstall. The same isolated AppId then installed the prior verified `65e4968` build, upgraded in place to `196caa8`, rolled back to `65e4968`, and restored `196caa8`; EXE hashes matched each step and a QA sentinel persisted. The restored install passed API smoke, and final uninstall removed its EXE and isolated registration. This did not touch the original product registration. Defender and real-time protection were enabled, and custom scans of the bundle, ZIP, and installer left the detection count unchanged.

The ZIP, installer, and manifest were pinned at artifact commit `7e1614c7ced260cddccc0d016d253ba10b9295ff`:
[ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7e1614c7ced260cddccc0d016d253ba10b9295ff/acceptance-artifacts/CATalyst-196caa8-primary-acceptance.zip),
[unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7e1614c7ced260cddccc0d016d253ba10b9295ff/acceptance-artifacts/Catalyst-Setup-196caa8-1.4.0.exe), and
[SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7e1614c7ced260cddccc0d016d253ba10b9295ff/acceptance-artifacts/SHA256SUMS-196caa8.txt).
Independent HTTP downloads of both binaries matched the hashes. The downloaded ZIP passed CRC.

## Live boundary and remaining gates

At the package checkpoint, the original TEST 7 app was still the older `eadb82a` executable, PID `120856`, as the sole port 5000 listener. Exact `196caa8` has not run against that original profile. No wallet effect was attempted in this package verification. The earlier original-profile stopped window failed during Veeam-overlap stalls, and no final-candidate 24-hour window is credited.

Original-profile active-offer lifecycle and recovery, independent secondary-PC exact-candidate acceptance, full native UI, both final-candidate 24-hour windows, and final review remain open. No new TEST 7 campaign or fee approval has been received. Keep PR #220 draft; do not merge, tag, release, or claim public readiness.
