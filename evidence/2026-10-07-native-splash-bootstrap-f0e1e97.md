# Native splash bootstrap correction: exact `f0e1e97`

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) remains targeted at `main`. Exact runtime/source `f0e1e97d2d4c55a38b371b1e7b754011d160cd08` repairs the packaged Windows splash navigation and removes its private bootstrap credential from the startup log. This is an unsigned acceptance candidate, not release approval.

## Reproduction and correction

The preceding `0f6706c` package was launched against original TEST 7 after its earlier package checks. The native WebView displayed `ERR_FILE_NOT_FOUND` because Edge WebView2 encoded `?bootstrap=...` into the local `splash.html` filename. The process was closed without connecting Sage, starting a campaign, or making a wallet offer. A minimal real PyWebView/Edge WebView2 probe reproduced the failure with a dummy credential; the same file navigated successfully when the credential was placed in a `#bootstrap=` fragment. The splash script now reads that fragment and redirects to loopback, where the server consumes the one-time credential and lands at a clean `/` URL.

A regression was first changed to require fragment transport and failed before the splash script change; it then passed in real Chromium. The Windows URL test also expects a fragment. A further native run of the initial `45f835a` correction exposed a second issue: the existing startup log redacted only URL queries, so it printed the fragment credential. That process and its separate fail-closed duplicate diagnostics process were closed. A new red regression for both file-fragment and HTTP-query URL logging failed before `f0e1e97`, then passed after `_redacted_desktop_url` removed both query and fragment. The prior logged token expired with its process and is not reused.

## Exact-source verification

- Focused Windows URL and log-redaction regressions: **2 passed** on `f0e1e97`.
- Full Chromium suite: **243 passed** on direct parent `45f835a`; `f0e1e97` changes only the Python startup log and its unit test. The isolated Chromium splash regression passed red/green after fragment transport.
- Ruff check/format and `git diff --check` passed. A concurrent optional local backend run on `45f835a` was interrupted at 38% to remove resource contention during native acceptance; it is **not** counted as a full-suite pass. Exact-source CI unit tests are pending at this checkpoint.
- Clean detached `python build.py` from `f0e1e97` succeeded. `E:\catalyst-native-splash-f0e1e97-build\dist\Catalyst\Catalyst.exe` SHA-256 is `9D1FC8FF842E27E2BD73DE0B7F2D3FB9E3B23720DF85D36CCF97939CA6E43644`.
- Bundled `_internal/splash.html` and exact-source `splash.html` both hash to `74AFFA3DD51146590B0AEB131C2DDCC5E284F1887E81D5B56B510273110733F2`.
- The exact package passed isolated packaged API, synthetic Sage RPC worker, and publication recovery smokes.

## Original TEST 7 read-only startup

The exact EXE was started with no other CATalyst process or port-5000 listener. The launcher initially returned before the native window became targetable; the single PID `172852` later owned port 5000 and displayed the real Risk Disclosure page at `http://127.0.0.1:5000/`, with the bot stopped. The exact startup log `bot_superlog_20261007_113405.log` had one `Desktop window URL: file:///.../splash.html` entry and **zero** `bootstrap=` entries. The EXE path and SHA-256 matched the clean detached package. Risk Disclosure remained on screen at this checkpoint; no Sage wallet connection, pair selection, campaign, offer, or fee action occurred in this exact run.

The prior `45f835a` run did reach the clean dashboard and Sage wallet chooser, proving the fragment navigation through native WebView2, but its log included the private fragment, so it is superseded. A duplicate launch during that run failed closed with a read-only `LEASE_OWNED_BY_OTHER` safety window and no offer or coin-prep action. Both predecessor processes exited. Its duplicate handoff did not complete promptly under concurrent full-suite load, so no duplicate-handoff pass is claimed here.

## Open gates

Exact-source CI unit tests, complete package/archive/installer acceptance, full original-profile Sage and UI traversal, independent secondary original-profile acceptance, final-candidate stopped and active 24-hour windows, and live active-offer lifecycle/recovery remain open. The specific new TEST 7 campaign and fee scope has not been approved; the older `c665` approval is invalid. Keep PR #220 draft. Do not merge, tag, release, or claim public readiness.
