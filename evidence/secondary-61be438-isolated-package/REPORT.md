# CATalyst 61be438 secondary packaged acceptance

Date: 2026-10-06 (Europe/London)

## Identity

- Source candidate: `61be438d67c015c6f49ee4d401c34266cb6e8091`
- Artifact commit: `3792fa66f88f2e679c8a319f458097b7346a4193`
- ZIP: `CATalyst-61be438-primary-acceptance.zip`
- ZIP bytes: `37,355,771`
- ZIP SHA-256: `414DD20D78EC1118FDFB1B948F524521A7BAB3BB9776E98D702E10572D637754`
- Extracted `Catalyst.exe` bytes: `11,285,664`
- Extracted `Catalyst.exe` SHA-256: `78E32799968BC132B4CD3FA39733B45206F1BE08B8DF2354A5B80318B9C71576`
- Executable metadata: CATalyst `1.4.0.0`, product version `1.4.0`, MonkeyZoo
- Installer: `Catalyst-Setup-61be438-1.4.0.exe`
- Installer bytes: `38,407,409`
- Installer SHA-256: `C182FA25F72155C02E7F2FC692A6A60D4E25989ED6685D105D1266147A2FA723`
- Authenticode: executable and installer are unsigned, as expected for this explicitly unsigned acceptance artifact.

All three supplied hashes matched exactly. ZIP extraction completed and the embedded executable matched its required hash.

## Isolated acceptance results

All test processes used temporary data directories, dynamically allocated loopback ports, synthetic certificates, and a local mock Sage identity (`123456789`). External Dexie publication and Splash were disabled. No live wallet transaction, fee approval, offer action, campaign mutation, or original-profile write was performed.

1. `scripts/packaged_sage_rpc_smoke.py --timeout 60`: PASS
   - Packaged worker loaded its dependencies.
   - Mutual TLS client authentication succeeded.
   - Synthetic mainnet identity and fingerprint were read from mock Sage.
2. `scripts/packaged_api_smoke.py --timeout 60`: PASS
   - `/api/health` reported v1.4.0.
   - Sage-running, startup, startup status, config validation, config isolation, diagnostics, self-test, and Doctor endpoints passed.
   - Mock Sage remained authenticated after startup reload.
3. `scripts/packaged_upgrade_publication_recovery_smoke.py --timeout 60`: PASS
   - Undispatched publication work became retryable.
   - Ambiguous dispatch was suppressed.
   - Stale claim authority was cleared.
   - The new isolated process owned the recovered lease with zero publication blockers.
4. `scripts/packaged_desktop_first_launch_smoke.py`: PASS
   - Clean native first launch passed.
   - Duplicate launch restored/foregrounded the owner and exited.
   - Persisted-profile relaunch passed.
   - Malformed identity produced the branded fail-closed native safety window.
5. `packaged_ui_probe.py`: PASS
   - Packaged HTTP status `200`, title `CATalyst`, version `1.4.0`, wallet type Sage, bot stopped.
   - Risk disclosure was visible.
   - Dashboard, Offers, Profit and loss, Market intelligence, Settings, Logs, and Data reset views switched successfully.
   - Help and About opened successfully.
   - Reset P&L displayed the destructive confirmation; the destructive action was not confirmed.
   - Zero JavaScript page errors, console errors, API 5xx responses, or rendered tracebacks.

UI evidence:

- Published `packaged-ui-result.json` SHA-256: `EBF37F16233924C64A3CEBB21A12A7EAFC80003D62CDC5BFB68AE36668829888`
- `packaged-ui-final.png` SHA-256: `FAFA294417F4FCD9132A5FD703B2DBA4FC741A6C5787545CC7D661AFD505F20B`
- `packaged_ui_probe.py` SHA-256: `DF61B7D725BB68B2376057112A03B9F0E8C54EC9D4707C7ADDA33D8D9DCA0FB5`

## Original cbd7d08 monitor impact

The original-profile application was not stopped, restarted, or mutated. PID `5656` retained ownership of port 5000, the correct executable, safety lease, wallet identity, balances, and zero-offer state. Monitor PID `14716` remained alive.

The monitor intentionally counts every process named `Catalyst`. While the isolated packaged tests were running, it recorded `unexpected_catalyst_process_count` at samples `54` and `56` because the temporary acceptance executable was concurrently active. Those records are preserved in `alerts.jsonl`; they are harness-induced and not an application or wallet-state failure. After every isolated process exited, sample `57` returned to one CATalyst process with no sample alerts. PID `5656`, port ownership, balances, offers, locks, holds, reservations, unresolved operations, safety, and lease remained correct throughout the alerted samples.

Because the existing 24-hour trace now contains two alerts, it is not literally an alert-free trace. A fresh uninterrupted 24-hour window from sample 57 (or a separately started exact-candidate monitor after rollover) is required if the release gate demands zero alert records rather than adjudicating the known concurrent-test-process condition.

## Verdict

PASS for bounded artifact identity, packaged API, mock Sage, interrupted-publication recovery, native launch, duplicate launch, persisted relaunch, safety fallback, and read-only packaged UI acceptance.

No CATalyst defect and no wallet effect were observed. The only limitation is the transparently preserved monitor alert caused by intentionally running the isolated packaged executable concurrently with the protected cbd7d08 process.
