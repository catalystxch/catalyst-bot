# Exact-candidate Windows desktop check

This check is for the locally built candidate from commit
`0ad637e84a47db7d94aeb936a895b734f5df7ec8`. It is not an installation, release,
or a claim that live trading acceptance is complete. Its full regression run
subsequently passed, but the whole-feature review found uncovered defects.

**This candidate is superseded for readiness.** The isolated command below
can provide native diagnostic evidence only. Do not use this build for a new
live campaign or fee spend. A later corrected candidate needs its own final
native result; there is no urgent operator action while software fixes proceed.

The automated package API, synthetic Sage connection, fee-approval rejection
and interrupted-publication recovery checks passed. The native desktop launch
check could not be performed through the assistant's current controls. No
alternate launch route was used to bypass that restriction.

## Optional baseline diagnostic

Run the following in PowerShell and return the final output (or the error).
The helper uses temporary application data and its own localhost port. It
checks clean first launch, duplicate-window handoff, persisted-profile relaunch
and malformed-identity safety display. It does not ask you to start trading,
approve a fee budget or replace the installed application.

```powershell
& 'C:\Python312\python.exe' 'C:\catalyst\.superpowers\post-tibetswap-v1-4\.superpowers\sdd\2026-09-16-coin-prep-fee-approval\candidate-0ad637e\scripts\packaged_desktop_first_launch_smoke.py' --exe 'C:\catalyst\.superpowers\post-tibetswap-v1-4\.superpowers\sdd\2026-09-16-coin-prep-fee-approval\candidate-0ad637e\dist\Catalyst\Catalyst.exe'
```

Expected terminal result:

```text
Packaged clean, duplicate, persisted, and native safety launches passed
```

If it fails, return the failure text rather than accepting a different wallet,
starting a campaign or changing safety settings. This result verifies the
native-launch gate only; it does not verify live Coin Prep or trading.

## Artifact identity

- Version: v1.4.0, local test candidate, not a published release.
- Executable SHA-256:
  `3C5FC6155D3B1BA0E0CD46FDE09D0CBFD8DB79267F3A3D3F665C4E7AFE2EFD1F`.
- Source and bundled HTML SHA-256:
  `DB933827F5BF55BC51EB798DB601F71A9BB4A8AA6EBE69C76A6A55509AB7B23D`.

The existing live source runtime and original browser Bootstrap draft have
not been restarted or refreshed to this candidate. A future live test needs
that version/identity check plus the operator's actual final campaign and
fee-budget confirmations. The saved, unaffordable pre-fee strategy remains
preserved and must not be silently activated or resized.
