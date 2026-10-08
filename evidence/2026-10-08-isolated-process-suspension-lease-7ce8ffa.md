# Isolated process-suspension check for the 90-second mutation lease

This is an additional, wallet-free acceptance probe for draft PR #220. It is
not original-profile live acceptance or a 24-hour stability result.

The executable runtime/source is `7ce8ffafef3ac8e14c269348c5285a2e268e2734`;
the reviewed PR head was `96d771029335aa57e3f07965b2d9bb3dbeef9d89`, whose
later changes are installer and evidence only. The detached EXE still hashes
to `47198CA321C9E36692929D9661EEF99D51037743AB5EAB71D42022DDE3C92B77`.

On Windows with Python 3.12.6 and psutil 7.0.0, a separate Python child loaded
the exact mutation-gate source, initialized a new SQLite database under
`E:\catalyst-lease-suspend-qa`, acquired a 90-second lease using a synthetic
wallet hash, and started its normal heartbeat thread. The parent used
`psutil.Process.suspend()` and `resume()` on that child alone. No Sage RPC,
real wallet identity, offer, or campaign was used. The one-off harness is
`E:\catalyst-lease-suspend-qa\probe.py`, SHA-256
`190D3C37ED463736F6DD0A371EE51FB4CAC23FDEE64C177C38237A6F4F84E9CC`.

| Deliberate suspension | Elapsed | Child result after resume | Expected |
| --- | ---: | --- | --- |
| 45 seconds | 45.0 seconds | `allowed=true` | In-window authority retained |
| 95 seconds | 95.0 seconds | `allowed=false`, `LEASE_EXPIRED` | Expired authority denied |

Both probe commands exited zero. Afterward no probe child remained. The only
`Catalyst.exe` process remained the older original-profile PID 120856 from
`E:\catalyst-sage-tls-eadb82a-build\dist\Catalyst\Catalyst.exe`; the harness
did not restart or touch it.

This checks real Windows process suspension and the gate's post-resume
decision. Existing deterministic regressions separately cover a pause during
SQLite UPDATE/COMMIT and delayed delegated-worker authorization. It does not
replicate the Veeam snapshot, establish its precise blocked operation, exercise
the packaged EXE's live Sage startup, or satisfy a final-candidate 24-hour
window. The older original-profile app remains in its read-only
`HEARTBEAT_FAILED` fence. Keep PR #220 draft; live wallet lifecycle, secondary
acceptance, both 24-hour windows, and final review remain open.
