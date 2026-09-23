# Current candidate: isolated Windows window check

Run this in PowerShell and return its final result or error. It opens temporary
CATalyst windows to check first launch, duplicate-window handoff, profile relaunch
and the startup safety screen. **Do not click trading or wallet approval buttons.**
The script uses disposable application data and separate localhost ports. It
does not install an update, replace your saved settings or start trading.

```powershell
$candidate = 'C:\catalyst\.superpowers\post-tibetswap-v1-4\.superpowers\sdd\2026-09-16-coin-prep-fee-approval\candidate-review-fixes-dns-20260923'
& 'C:\Python312\python.exe' "$candidate\scripts\packaged_desktop_first_launch_smoke.py" --exe "$candidate\dist\Catalyst\Catalyst.exe"
```

Expected final line:

```text
Packaged clean, duplicate, persisted, and native safety launches passed
```

If it fails, return the error text. Do not change the wallet, weaken safety
settings or substitute another build to make the check pass. This result covers
native launch only, not Coin Prep, live trading or full acceptance.

## Exact artifact

- Local v1.4.0 test snapshot, runtime-equivalent to code commit `bc7203d`,
  not a release. The final backend run passed 6,981 tests, with 157 skipped.
  Native launch and live trading are still separate open acceptance gates.
- Executable SHA-256:
  `703E707F74977FEE071C93B0940FBEE665446C3620782B393A72DF229C990223`.
- UI SHA-256:
  `D70A871D6E58D24751092B80A9CE2AB40B58A63B44A6841A9CE77FF093BE2432`.
- Build 58429 exited 0 after a complete byte-verified snapshot; the new local
  hostname helper is present in the executable's Python archive.

The assistant's controls previously blocked the native-launch check, so this
is an operator handoff, not an alternative automated launch route. Existing
source runtime, installed app, saved strategy and live wallet remain unchanged.
