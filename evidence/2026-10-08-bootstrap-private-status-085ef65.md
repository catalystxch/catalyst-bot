# Bootstrap status local-credential correction and exact Windows package

The exact runtime/source is `085ef6522fc5b4989f8d9a7380cbd08da1696e43` on draft PR #220. An independent read-only check on the Harvestr secondary PC confirmed that unauthenticated loopback `GET /api/bootstrap/status` returned HTTP 200 with wallet identity and campaign fields, while `GET /api/coin-prep/status` returned HTTP 401. The primary PC reproduced the same behavior on the original TEST 7 `196caa8` process. This was a loopback-local disclosure to another process on the same machine, not evidence of a remote-network listener.

The new red regression asserted unauthenticated Bootstrap status returns HTTP 401 and failed against `196caa8` because it returned 200. `085ef65` added `/api/bootstrap/status` to the existing private-read route set. The regression then passed, including an authenticated HTTP 200 check. The existing native bridge calls the Bootstrap getter directly; browser mode carries the local session cookie. The focused CodeQL-hardening and Bootstrap API suites passed **76 tests**; API local-guard and Bootstrap UI contract passed **39 tests and 11 subtests**. Ruff check and format passed. The complete serial local Windows backend passed **7,435 tests, 246 skipped, and 455 subtests** in 26 minutes 27 seconds. All **11** PR checks on `085ef65` completed successfully. The bundled UI SHA-256 is byte-identical to the prior `196caa8` candidate, whose isolated Chromium suite passed 245 tests.

Clean detached checkout `E:\catalyst-bootstrap-private-085ef65-build` was built from exact `085ef65`. Its SHA-256 values are:

| Artifact | SHA-256 |
| --- | --- |
| `dist\Catalyst\Catalyst.exe` | `7F90AACFF53054856CFE06DCDA71031F191B9F7BB73A74CF8128E506D904C8CA` |
| bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| `CATalyst-085ef65-primary-acceptance.zip` | `BEA6C15E19A184AE14AE92999F4FF609F2B4F3CE65FB09DB558EC900DCA9CB2F` |
| unsigned `Catalyst-Setup-085ef65-1.4.0.exe` | `E2D37FD68B3BF363796C74092118F8379F681D75F547977F658BC008904FB8BA` |

Packaged API and mock Sage RPC smokes passed. A separate packaged probe confirmed unauthenticated Bootstrap status returns 401 and credentialed Bootstrap status returns 200. Publication recovery and native clean/duplicate/persisted/safety smokes passed. ZIP CRC and embedded EXE hash passed. A unique-AppId isolated installer clean install, installed API/Sage smokes, same-version upgrade from `196caa8`, rollback, restore, and uninstall passed without touching the ordinary registration. Defender scanned the EXE and installer successfully. The copied `Catalyst-Setup-v1.4.0.exe` release-file staging matched the exact installer hash, `NotSigned` Authenticode status, `1.4.0` product version, and required SHA-256 sidecar format. This was a local release-file preflight only.

The ZIP, installer, and manifest were pinned at artifact commit `50aeb6a968c58c23a361b9b6bf3d78aadb77303e`:

- [Windows ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/50aeb6a968c58c23a361b9b6bf3d78aadb77303e/acceptance-artifacts/CATalyst-085ef65-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/50aeb6a968c58c23a361b9b6bf3d78aadb77303e/acceptance-artifacts/Catalyst-Setup-085ef65-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/50aeb6a968c58c23a361b9b6bf3d78aadb77303e/acceptance-artifacts/SHA256SUMS-085ef65.txt)

Fresh independent HTTP downloads of all three matched their hashes, including manifest SHA-256 `E5D41E2D6D17FA717D25D1E7B64B7AC404B0AC66CC7F49B2FF9A7344525A84DF`.

The older original TEST 7 `196caa8` process PID 91988 and its monitor PID 32852 were retired after a fresh read-only preflight: one exact process and listener, stopped bot, allowed safety and owned lease, zero DB open offers, Sage mainnet fingerprint 736588221 and exact MZ asset, unchanged XCH 138470301476875 mojos and MZ 780212284 atomic units, zero pending, 4,095 terminal Sage offers, synced wallet, inactive Bootstrap, and prior campaign stopped with zero authoritative fee spend and no approval. Its monitor had 166 clean samples through 2026-10-08T09:49:52Z. That partial window is historical and cannot count for `085ef65`. The old app closed normally, leaving no port-5000 listener.

An attempted command-tool launch of the exact `085ef65` EXE was rejected **before execution** by automatic approval review with reason `blocked by policy`. The operator was asked to start that exact EXE manually; this rejection must not be bypassed through another tool. Exact `085ef65` has not yet run against the original TEST 7 profile. The Harvestr PC was given the pinned package for independent acceptance and safe original-profile rollover. Both exact-candidate 24-hour windows, live active-offer lifecycle/recovery, full native UI, final review, and beta publication remain open. PR #220 and website PR #89 remain draft; no merge, tag, release, or public-readiness claim was made.
