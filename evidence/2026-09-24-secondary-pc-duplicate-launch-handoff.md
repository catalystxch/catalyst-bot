# Secondary-PC duplicate desktop handoff fix

## Provenance

- Authorized acceptance base: `5b54d9465555aaa5bbd7dd43ff51f299cab89ca6`.
- Branch: `codex/fix-duplicate-desktop-handoff`.
- Original transferred executable SHA-256:
  `696BEAD6A79CED2B846E67781F59F73A6EA05FF694BDE649AF43A3B1FFD62A25`.
- Fixed executable SHA-256:
  `24AF3F777373D5F35E5F3A62EDA54AEFF838C76788158483810E8CCB04A77DFD`.

## Reproduction and root cause

The exact transferred executable failed
`scripts/packaged_desktop_first_launch_smoke.py` because the duplicate process
did not exit within ten seconds. A focused native probe showed that the
duplicate found the exact owner HWND and restored it from minimized state, but
Windows retained another process as the foreground window. CATalyst treated
that initial `SetForegroundWindow` denial as a failed handoff and opened a
second read-only Startup Safety desktop instead of exiting.

The fix keeps the existing exact PID/title verification. If the first
activation is denied, the duplicate temporarily attaches its input queue to
both the current foreground thread and the verified owner window thread,
retries restoration/activation, and detaches both queues in reverse order.
Any missing PID/thread evidence or failed attachment remains fail-closed.

## Verification

- Red regression: the new input-thread fallback test failed on the acceptance
  base with `unexpected keyword argument 'kernel32'`.
- Focused handoff tests: **6 passed**.
- Ruff on both changed files: passed.
- Affected regression set (`test_mutation_gate`, packaged desktop smoke unit
  tests, Windows process lifetime and instance lock): **270 passed** in
  135.32 seconds.
- Fresh Windows PyInstaller build: passed.
- Real packaged smoke: passed clean-profile launch, duplicate handoff,
  persisted-profile relaunch and native safety launch.

No wallet action was performed by this defect reproduction or fix.
