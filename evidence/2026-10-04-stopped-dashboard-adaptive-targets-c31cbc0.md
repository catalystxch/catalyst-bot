# Stopped dashboard and status polling (`c31cbc0`, `f6596a5`, `6191cf4`)

Draft PR #220 remains in acceptance. The adaptive-target source correction is
`c31cbc0181e3c714654965d9538bfee0eadc3950`; the subsequent stopped-state
latency correction and current exact runtime source is
`f6596a5fdf30e4e0f3686362786800bc165b26ec`.

## Live finding and cause

The packaged `aa9b09f` app was connected to the original TEST 7 profile with
the bot stopped and no active Bootstrap campaign. Its native Logs view showed
repeated `adaptive_ladder_target_reduced` events for both sides, including
“target reduced to 0/3 while coin inventory catches up (0 usable spare
coin(s))”, roughly every two minutes. No Coin Prep or offer action was running.
Read-only API inspection counted 328 adaptive-target reduction events among
352 current-session log entries.
The same read-only UI traversal showed zero active offers and zero pending
transactions. Doctor passed 9 checks and warned that optional Splash at
localhost:4000 was unreachable; Data Reset, Help, About, and Settings rendered
without mutation.

`GET /api/dashboard` called `BotLoop._get_effective_offer_targets()` even
when the bot was stopped. That method calls the adaptive target calculator,
which writes target bookkeeping and emits the observed reduction event. A
frequent read-only dashboard request therefore changed bot diagnostic state
and produced misleading operator logs.

## Red/green correction

The stopped-dashboard endpoint regression first failed on the preceding
source: it received effective target `3` instead of `0`. The exact source
now reports zero active targets and skips the stateful calculator unless both
the bot's reported state and `is_running()` indicate an active run. The same
regression then passed. The existing active-bot target assertion remained
green. All 30 dashboard endpoint tests passed, as did Ruff check, Ruff format
check, and Git whitespace check.

## Exact Windows package

A clean detached build at `E:\catalyst-dashboard-c31cbc0-build` was checked
out at the exact source commit. The 192-file ZIP passed CRC, extraction,
embedded EXE hash comparison, and extracted API smoke. The detached EXE passed
packaged API, synthetic Sage RPC, publication recovery, and native
clean/duplicate/persisted/safety smokes. A unique-AppId current-user QA
installer passed clean install, installed EXE hash, installed API and Sage
smokes, and uninstall; its EXE and registration were absent afterward.
Defender custom scans of the bundle, ZIP, and unsigned installer reported no
matching detections.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `4534DE6302A3D67C96381B5D07336ED1542309AB37770399023E9EAF1CF9207A` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-c31cbc0-primary-acceptance.zip` | `886B3EE32BD235E13897C52D7828E4C329F88213FDF70B138D9CD0BD95DF3D6D` |
| `Catalyst-Setup-c31cbc0-1.4.0.exe` | `1333D1BD4691E5EE5899EE562D0DDD34B4DEF2ABC1B0C845180F6A5736171D76` |

The full `c31cbc0` Windows backend suite passed 7,163 tests, 210 skipped and
427 subtests. All 11 PR checks passed. An original-profile TEST 7 live restart
with the exact `c31cbc0` package confirmed zero adaptive-target reduction
events after repeated dashboard GETs and several minutes stopped; the endpoint
reported effective targets 0/0. The same live run showed a separate persistent
dashboard latency of about 20.6 seconds per GET after the test load ended.
`/api/health` and `/api/logs` remained fast, and direct read-only Sage RPC
calls returned in milliseconds. A live Python stack sample during the slow
request caught `/api/dashboard` in `_live_wallet_reads_allowed`, through
`bot.get_state()` and `splash_node.get_status()`, waiting on optional Splash
connectivity. The guard called full state before checking the bot's cheap
`is_running()` flag, and the stopped dashboard invokes that guard repeatedly.

A new regression required a stopped bot to avoid `get_state()` entirely. It
failed red on `c31cbc0` and passed after the guard checked `is_running()`
first, returning immediately when stopped. All 31 dashboard endpoint tests and
106 related dashboard/status/Splash tests passed, as did Ruff check/format and
Git whitespace check. The corrected source was committed as `f6596a5`.

## Exact `f6596a5` package and live retest

A new clean detached Windows build at
`E:\catalyst-dashboard-f6596a5-build` passed packaged API, synthetic Sage
RPC, publication recovery, native clean/duplicate/persisted/safety smokes,
192-file ZIP CRC, and ZIP extraction. A unique-AppId current-user QA installer
passed clean install, installed EXE hash, installed API and Sage smokes, and
uninstall; the QA executable and registration were absent afterward. Defender
custom scans of the bundle, ZIP, and installer reported zero matching
detections. Both pinned artifact downloads independently matched their hashes.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `7D4BE62A53BE9CD064657B7B6D4093B83706EAA8EC21A32B8C31755AF4B035AD` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-f6596a5-primary-acceptance.zip` | `89ED40AD07E97DA399BE094F0481C38787EC77E834CE3AE42031733E013F765E` |
| `Catalyst-Setup-f6596a5-1.4.0.exe` | `656F760E45F013F4FAECFCBCD5753B8B711977274550E0BF173CF491B47392D5` |

The package is pinned at artifact commit
`ee1dab6f9eca5751c0da5ce5af9c3d0ec4b04e29` on
`codex/coin-prep-fee-approval-artifacts`. The original TEST 7 app was shut down
through its native UI with cancel-offers unchecked; zero offers existed. The
new exact executable became the sole `Catalyst.exe` and port 5000 owner. The
operator-authorized Risk Disclosure was acknowledged, Sage mainnet fingerprint
736588221 selected, and MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
selected with CAT wallet ID 2. The bot remained stopped. Two consecutive
dashboard requests returned in 0.221 and 0.201 seconds, with effective buy and
sell targets 0/0. XCH remained 138.470301476875 and MZ 780212.284, with zero
open offers, zero adaptive-target reduction events, and safety allowed with
zero blockers.

The full exact `f6596a5` Windows backend suite was superseded by the next
source correction before it completed. All 11 PR checks passed on that commit.

## Stopped optional Splash status polling (`6191cf4`)

Live `/api/status` requests on the `f6596a5` package still took 4.5–4.6
seconds. A live process stack showed `bot.get_state()` calling
`splash_node.get_status()`, which waited on HTTP to the configured but stopped
optional Splash node at `localhost:4000`. A direct read-only request to that
address reproduced the connection timeout. The new source commit
`6191cf48522a42234877a3d9fd73d339083c98b1` checks the loopback port
with a 0.25-second TCP connection timeout when the managed Splash process is
stopped. A dead port returns unavailable without HTTP; a reachable external
Splash listener continues through the existing health check. Two red/green
tests cover those cases, and 100 related tests and four subtests passed.

The exact clean detached build at `E:\catalyst-splash-6191cf4-build` passed
packaged API, synthetic Sage RPC, publication recovery, native
clean/duplicate/persisted/safety smokes, 192-file ZIP CRC, unique-AppId
current-user installer clean install/installed API and Sage/uninstall, and
Defender custom scans with zero matching detections. Independent HTTP
downloads of the pinned ZIP and unsigned installer matched their hashes.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `429440452B05050E80EE204BA16030E6CC850FD14213CC2006CA1DF145622DA6` |
| Bundled `_internal/bot_gui.html` | `11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6` |
| `CATalyst-6191cf4-primary-acceptance.zip` | `E092516652FCF1777A83D2C1426AEF54D1A12E962B1FDF25D6C3D2D246D59547` |
| `Catalyst-Setup-6191cf4-1.4.0.exe` | `BCF02FB8F39DCFA8115D6B7E5495F936E614A7D19E35BA9D06DE76DCA1CD901B` |

Artifacts are pinned at `2fd758a877645487df905c62354266a9c7148829`.
All 11 PR checks passed on exact source `6191cf4`, including unit tests. The
full local Windows backend suite is still running at the time of this note.

The prior app was shut down through its native UI with no offers to cancel.
The exact `6191cf4` EXE became the sole `Catalyst.exe` process and port 5000
owner on original TEST 7. The authorized Risk Disclosure was acknowledged,
Sage fingerprint 736588221 selected, optional Splash skipped, and MZ pair
selected. Two initial live status reads took 1.257 and 1.149 seconds;
dashboard reads took 0.266 and 0.239 seconds. Eight further status requests
returned HTTP 200 with 0.954-second minimum, 1.000-second median, and
1.540-second maximum; eight dashboard requests returned HTTP 200 with
0.199-second minimum, 0.218-second median, and 0.247-second maximum. The bot
remained stopped, XCH was 138.470301476875, MZ was 780212.284, open offers
remained zero, safety allowed with no blocker counts, and the active Bootstrap
status was false for exact mainnet fingerprint 736588221 / wallet ID 2 / MZ
asset. Fifteen current-session logs contained no adaptive-target, Coin Prep,
offer, or campaign events.

No new campaign, fee approval, wallet transaction, or offer was created. The
specific replacement-campaign approval request remains unanswered. Keep PR
#220 draft; live lifecycle, both 24-hour windows, independent secondary
package acceptance, and final review remain open.
