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
the changes. The exact-source full serial Windows backend suite and final
PR unit-test check are still running at this checkpoint.

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

The earlier `cfa42f3` process remains in terminal read-only safety after its
failed diagnostic run. This exact `0d1096e` package has not yet replaced it
on original TEST 7. No wallet effect, new campaign, or fee approval occurred
in these isolated checks. Active-offer lifecycle and recovery, secondary
original-profile acceptance, both final-candidate 24-hour windows, final
review, and release authorization remain open. Keep PR #220 draft.
