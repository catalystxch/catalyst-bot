# Private loopback reads and public safety binding — 8cd81e4

This is acceptance evidence for draft PR #220. It does not authorize a beta release or replace live wallet and stability acceptance.

## Independent finding and correction

The secondary PC's isolated probe of the preceding `558e912` package found that uncredentialed loopback GETs could read wallet, trade, and configuration data. `GET /api/coins` could also reap Coin Prep state and persist inventory; Flask dispatched HEAD to the same GET handlers. The independent red baseline had 52 passing and 339 failing checks, with no original-profile wallet effect.

Exact runtime/source `8cd81e4213c884b694d4e880e0f179cbcf3448bc` requires the local header or bound browser cookie for private wallet, trade, configuration, and operational GET/HEAD routes, including `/api/offers/open_count`. Uncredentialed GET/HEAD is denied before the handler, authenticated HEAD is denied before handler dispatch, and a cross-site browser fetch cannot use a bound cookie to trigger private read maintenance. The public safety-status exception retains its bounded fail-closed diagnostic contract for startup and external monitoring.

Independent secondary acceptance on a fresh detached exact-source checkout passed 367/367 private-read checks and 15/15 startup-cookie checks. The browser bootstrap flow established an HttpOnly SameSite=Lax cookie before credentialed startup polling. Focused security/API/offers/safety/UI tests passed 150 tests and 11 subtests; the browser bootstrap test passed. The secondary did not touch its original wallet profile.

The same review found that the former public safety-status wallet hash prefix was reversible from the small fingerprint domain. The public `identity.wallet_fingerprint` value now uses an independent per-process HMAC key and `run:<12 hex>…` display form. A red/green regression verifies that the label changes with the process key and does not expose the raw hash prefix. The native UI accepts the new form; 27 affected safety/UI tests passed. The secondary verified in two isolated processes that the labels differ across runs and that raw fingerprint, asset ID, offer ID, amount, injected secret, owner run ID/PID, and full wallet hash are absent. Exact 245-test Chromium suite passed.

The source branch has test-only child `cd726e45d0e3f0e9914cb120437fd9d5df93358a`, which updates older endpoint-contract clients to authenticate. Its 124 affected tests passed. The complete serial Windows backend suite passed 7,448 tests with 246 skipped and 455 subtests passed in 1,351.14 seconds; process exit code was zero. All 11 exact-head CI checks passed.

## Clean Windows package

Detached clean build: `E:\catalyst-private-get-8cd81e4-build`. It contains the exact runtime commit above. PyInstaller completed successfully. Artifact branch commit `c5964c8d3eb40a4e22d5c4c8042b605cc852261a` pins the following files:

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `142BC2014765AE5E4F54B3E51B91FD4679109EB4D9376529C24490FDBD30C781` |
| bundled `bot_gui.html` | `7001176B04758A5079D1460BBB23FCB51677BDDDD66F92AE03A56F4269AE578C` |
| `CATalyst-8cd81e4-primary-acceptance.zip` | `F5D72031B0B5B7E161130918CE4E43503736DC1AB44647BA8BDA2EAF7FC6A606` |
| unsigned `Catalyst-Setup-8cd81e4-1.4.0.exe` | `AD21690DD7A689311761A9AF6565D86C8DEB44D6C8851C22A387899154F8CF49` |

Packaged API, synthetic Sage RPC, interrupted-publication recovery, and native clean/duplicate/persisted/safety smokes passed. The ZIP has 192 entries, passed CRC, contained the exact EXE, and passed extracted API smoke. An isolated unique-AppId installer clean-installed an identical EXE, passed installed API/Sage smokes, upgraded from the earlier exact `558e912` EXE, rolled back, restored `8cd81e4`, preserved a QA sentinel, and uninstalled without leaving its EXE or QA registration. The ordinary product registration was untouched. The installer reports product version 1.4.0 and `NotSigned`, consistent with the proposed explicit unsigned beta path. Defender real-time protection was on; custom EXE/ZIP/installer scans left the detection count at six. Independent HTTP downloads of the pinned ZIP and installer matched their SHA-256 values.

The secondary PC independently downloaded the pinned ZIP, installer, and manifest over HTTP and matched their SHA-256 values. It verified all 192 ZIP members' CRCs, found no duplicate or unsafe path, and matched the extracted EXE and UI hashes above. Two runs of the extracted binary passed 148/148 private-route, startup, public-safety, and synthetic Sage checks each. The packaged public `run:` wallet labels differed between processes, and the mock Sage observed only read-only RPC calls. This work left the secondary original wallet profile and its existing monitor untouched. Its report is at `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\next-pr220-private-read-acceptance\PACKAGED-8CD81E4-RESULT.md`.

Exact `8cd81e4` has not run against the original TEST 7 live profile. The new campaign has not been approved or started; no new wallet effect or fee approval occurred. Active-offer lifecycle/recovery, both final-candidate 24-hour windows, full original-profile UI, secondary live acceptance, and final review remain open. Bot PR #220 and website PR #89 remain draft; no merge, tag, release, website deployment, or public-readiness claim was made.

Subsequent to this package checkpoint, exact `8cd81e4` was launched on the original TEST 7 profile and began a fresh read-only stopped-bot monitor. See [live start evidence](2026-10-08-primary-8cd81e4-live-readonly-start-and-monitor.md). The complete 24-hour result remains open.
