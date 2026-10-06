# Delayed-heartbeat fail-closed correction: exact `0d1096e` package

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) remains
targeted at `main`. Exact runtime/source commit:
`0d1096ea356a008cbf29930df1cd63c053cecd83`. The later documentation
commit does not change the runtime.

## Correction and verification scope

The `cfa42f3` original TEST 7 diagnostic run returned a successful heartbeat
after its stored lease had expired during a 49-second database attempt. A
subsequent attempt failed closed. `0d1096e` checks expiry before and after
durable commit and again when the gate receives the result; an unexpected
heartbeat-worker exception now fences the process. The affected suites passed
482 tests, with focused regressions demonstrated red before and green after
the changes. The exact-source full serial Windows backend suite passed
**7,305 tests**, with **232 skipped** and **433 subtests passed** in
30m 48s. All 11 PR checks passed on evidence-only head
`8fdb310aa7d7ca8ba35a9bfb76a5961e1f9e4269`, including `unit-tests`.

The correction does not keep a 30-second lease alive through the observed
42–45-second Windows Update snapshot stalls. Those diagnostic runs failed the
24-hour acceptance gate. A fresh exact-source original-profile run and both
full stability windows remain required.

## Clean detached Windows package

`E:\catalyst-heartbeat-0d1096e-build` was detached at exact source
`0d1096e` before `python build.py`. Build and Inno Setup compilation returned
zero. The generated `_version.py` modification is confined to the detached
build worktree.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `F68A0A8678FBACABA2CECCA66B0ECA8433837C4509175407B6A02B042EFF1023` |
| Bundled `_internal/bot_gui.html` | `0BC6A450C08D48BA77C2700A4F7DF8EEE54215A83259462CB07CF0CC47C6D574` |
| `E:\CATalyst-0d1096e-primary-acceptance.zip` | `7BD3A1B14F72B822D48F33967B3D38570D6F2C094D22953B18C6F75EEF692AB6` |
| Unsigned `Output/Catalyst-Setup-1.4.0.exe` | `01BDBFBFD6498CF835EFD4596FC3223FE38CED05A248F398B5ADCCB6DC8EE949` |

The ZIP, unsigned installer and `SHA256SUMS-0d1096e.txt` are pinned at
artifact commit `68cbbb332c0b11dbc40d34c450bb37ae639d54e5`:

- [Exact-source Windows acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/68cbbb332c0b11dbc40d34c450bb37ae639d54e5/acceptance-artifacts/CATalyst-0d1096e-primary-acceptance.zip)
- [Unsigned acceptance installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/68cbbb332c0b11dbc40d34c450bb37ae639d54e5/acceptance-artifacts/Catalyst-Setup-0d1096e-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/68cbbb332c0b11dbc40d34c450bb37ae639d54e5/acceptance-artifacts/SHA256SUMS-0d1096e.txt)

Independent HTTP downloads of the pinned ZIP and installer matched the
table's hashes. These are acceptance artifacts for the draft PR, not a public
release.

The 206-entry ZIP passed full CRC readback; it contains one exact EXE and no
`.env`, `bot.db`, WAL/SHM, or crash-log file. Its extracted EXE matched the
build hash and passed packaged API smoke. The original bundle passed packaged
API, synthetic Sage mTLS RPC, interrupted-publication recovery, and native
clean/duplicate/persisted/safety launches.

A separate-name, unique-AppId QA installer used
`{4565A0C6-A692-49EE-87E2-9ABB99804A7E}` and installed to
`E:\catalyst-heartbeat-0d1096e-qa-install`. Its installed EXE matched the
clean-build hash and passed packaged API and synthetic Sage checks. Silent
uninstall returned zero; the QA directory, registration, and processes were
absent afterward. The production installer was compiled but not installed.

Microsoft Defender engine `1.1.26080.3`, signatures `1.459.576.0`, scanned
the bundle, ZIP, and production installer. The threat-detection count remained
six before and after, with no new detection attributable to this package.

## Original TEST 7 read-only rollover

The prior `cfa42f3` process shut down through the local UI control plane with
cancel-all unchecked, while the bot was stopped and no offers were open. The
exact clean `0d1096e` executable then started as the sole `Catalyst.exe` and
port 5000 owner. At the initial checkpoint its PID was `118100`, path was
`E:\catalyst-heartbeat-0d1096e-build\dist\Catalyst\Catalyst.exe`, and the
on-disk SHA-256 matched the package table above.

The operator-authorized native startup acknowledged the testing Risk
Disclosure, connected Sage, selected TEST 7 fingerprint `736588221`, skipped
optional Splash, used the previously configured Spacescan key, and selected
Monkeyzoo Token. It did not start the bot or a Bootstrap campaign. Read-only
API checks reported mainnet, Sage fingerprint `736588221`, CAT wallet ID `2`,
exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced Sage, XCH `138.470301476875`, MZ `780212.284`, bot stopped, inactive
Bootstrap, zero wallet and DB open offers, and safety `ALLOWED` with an owned
renewing lease and zero blockers. An independent read-only Sage RPC returned
zero pending transactions and `get_key` returned the expected fingerprint.
An independent complete Sage `get_offers` read returned 4,095 terminal
records: 3,326 cancelled, 231 expired and 538 completed; none was fillable.
The original database still held prior campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
as stopped with zero authoritative fee spend. No new campaign was active.

The clean exact-PID/hash stopped-profile monitor is
`E:\catalyst-stability-monitor-0d1096e-clean\monitor.ps1` (SHA-256
`DFFC1AF5977F2461828669B09EEB52AF8BEC945982974A57FA0E2484F7B58795`), writing
`trace-60s-clean.jsonl`. It began at `2026-10-06T22:27:32Z`; its first sample
had an owned lease, synced wallet, stopped bot, zero offers and safety
allowed. This is the start of observation, not a completed 24-hour gate.
An independent read-only audit script at
`E:\catalyst-stability-monitor-0d1096e-clean\audit.ps1` (SHA-256
`23BE8C7ADA53B365CCB123FBBD63596F9B62E4CE2CF7E198ACC6B9E81A2B7043`)
checks every sample's identity, safety, lease, wallet sync, stopped bot, offer
count and observation gap, plus the current executable hash and port owner.
The [auditor is pinned for independent review](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d20acaa4990c291a88215cf5b45739bd09e99a2f/acceptance-artifacts/heartbeat-trace-audit-0d1096e.ps1);
an independent HTTP download matched that hash.
With the duration threshold set to zero solely for verifier testing, a
synthetic clean row returned pass (`0`); an otherwise identical row with
safety blocked returned failure (`1`). The live trace correctly returned
incomplete (`2`), with no sample errors at that checkpoint. This verifier
does not shorten the required 24-hour observation.

The exact native UI's read-only Dashboard, Offers, P&L, Market Intelligence,
Settings, Logs, Data Reset, Help and About traversal passed with MZ selected.
Offers showed zero active buy/sell offers; the historic P&L page showed three
previously verified buy fills, and the market page showed RED confidence with
no tradable depth. No settings were saved and no reset action was used.

No wallet effect, new campaign, or fee approval occurred. Active-offer
lifecycle and recovery, secondary original-profile acceptance, both
final-candidate 24-hour windows, final review, and release authorization
remain open. Keep PR #220 draft.
