# Beta channel and loopback security preflight

An independent secondary-PC review of exact source `085ef6522fc5b4989f8d9a7380cbd08da1696e43` identified three release blockers. This follow-up remains on draft PR #220; it does not authorize publication or replace exact-candidate live acceptance.

## Runtime diagnostic and private reads

- An unauthenticated loopback `GET /api/health/runtime?repair=true` could call `run_runtime_checks(auto_repair=True)`, which can mutate durable offer publication and budget state. The new regression reproduced the uncredentialed path and the authenticated query path before the fix. The GET route now requires the local credential, rejects repair requests with HTTP 400 before running checks, and passes `auto_repair=False` for allowed reads. The internal bot cycle retains its controlled auto-repair call.
- Wallet fingerprints, Sage certificate candidates, offer diagnostics, and reservation reads could return HTTP 200 without the local credential. They now join the existing private-read route set. A negative test checks all five diagnostic routes return HTTP 401 without the credential; their existing authorized endpoint tests continue to exercise successful reads.

## Explicit unsigned beta channel

- The manual unsigned Windows beta workflow requires a public **prerelease** source tag. It signs a `channel: beta` update manifest and stages/publishes the channel release as a prerelease with `--latest=false`. The tag-triggered signed stable-release workflow skips `v1.4.0`, reserving that exact tag for the beta path.
- The desktop stable updater accepts only a signed `channel: stable` manifest. Its feed remains GitHub `releases/latest`, so it cannot treat the beta as a normal stable update even if channel metadata is mispublished.
- Website draft PR #89 pins the sync to `v1.4.0`, requires the unsigned release to be a GitHub prerelease with a signed `channel: beta` manifest, and does not require unpublished Linux assets. Its Windows download panel already labels the installer unsigned and explains the SmartScreen warning.

Red/green focused tests passed for the private reads, blocked repair query, stable updater beta rejection, beta release workflow and website verifier. Website PR #89 `validate` CI passed on exact `fe6d7151b37a9b92a18fe18dc7ae6f413ca7942d`. Bot PR #220 completed all 11 exact-source checks. The complete serial local Windows backend passed **7,441 tests, 246 skipped, and 455 subtests** in 21 minutes.

## Exact Windows candidate

The clean detached exact source is `558e9122f3e5d66c027e803dcc6dbc7480592440` at `C:\catalyst\.superpowers\beta-security-558e912-build`. Build succeeded. The compiled bundle and staging hashes are:

| File | SHA-256 |
| --- | --- |
| `dist\Catalyst\Catalyst.exe` | `E8768123B751798FB6EEC6B39ED0A5FD351DCF58EDB7DB0304F4EE55A85AF6B7` |
| bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| `CATalyst-558e912-primary-acceptance.zip` | `1B92FCEB2051B19F9C49C501EAFF531DEBE474C3596D6674D22CD0915CBBC5CB` |
| unsigned `Catalyst-Setup-558e912-1.4.0.exe` | `EE3208215DE35220329E32ED1307E3010240036CC3F0A89911A540FB31BCBE18` |

The packaged API, synthetic Sage RPC, publication recovery, and native clean/duplicate/persisted/safety startup smokes passed. An additional packaged probe confirmed all five private diagnostic GET routes return HTTP 401 without the local credential and authenticated `GET /api/health/runtime?repair=true` returns HTTP 400. ZIP CRC and embedded EXE hash passed. A separately compiled unique-AppId installer installed into an isolated directory; installed API/Sage smokes passed, and its uninstaller removed the installed EXE. Defender custom scans of the clean EXE and staged installer completed without a new detection. The distributable installer is `NotSigned` with product/file version `1.4.0`, as intended for the explicit unsigned beta. This is package verification only: the exact candidate has not run on the original TEST 7 profile, and neither 24-hour gate has begun.

The package was pinned at artifact commit `cf3abf90504d0c03414270ca640adf951c56d310`:

- [Windows ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cf3abf90504d0c03414270ca640adf951c56d310/acceptance-artifacts/CATalyst-558e912-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cf3abf90504d0c03414270ca640adf951c56d310/acceptance-artifacts/Catalyst-Setup-558e912-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/cf3abf90504d0c03414270ca640adf951c56d310/acceptance-artifacts/SHA256SUMS-558e912.txt)

Independent HTTP downloads of the ZIP and installer matched the table hashes. The downloaded manifest contained the same source and artifact hashes; its Git-normalized remote SHA-256 is `90D36A65BE726D85994666DEFBD1F611B90260ADE2DAB4CFCA9E23D8071DB4CB`.

The secondary PC independently checked exact bot `558e912` and website `fe6d715` in clean detached worktrees. It marked all three original findings fixed: seven exploit/channel regressions passed, 189 broader relevant tests and 10 subtests passed, and website CI-equivalent validators passed. Its original Harvestr process and monitor were left untouched. This closes the three specific review findings; it does not satisfy live lifecycle or stability acceptance.

Both PRs remain draft. No merge, tag, release, website deployment, or public-readiness claim was made.
