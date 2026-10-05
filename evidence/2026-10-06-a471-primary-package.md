# Exact a471 Sage evidence package

PR #220 remains draft. The clean Windows build worktree
`E:\catalyst-a471-primary-build` was detached at
`a471bd0b332726e77ca38719e377f480af36909e`. `python build.py` used
PyInstaller 6.21.0 and Python 3.12.6, passed bundled HTML and CA checks, and
reported only the accepted optional `importlib_resources.trees` hidden-import
warning.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `8EDBD77054CE734DD766D982104F6AFD45A993BDCC9EA481CE0D7BA92CEC6BE2` |
| Bundled `_internal/bot_gui.html` | `2778E110E3E358D05E6E84E9EE8645AD71233FCDCB9D396BD219D62D4774D6F5` |
| `CATalyst-a471-primary-acceptance.zip` | `3DC14E9E823441337D15D2FD8263483D292816FFB85B7E2BEA12179B7080B973` |
| Unsigned `Catalyst-Setup-1.4.0.exe` | `07D532C1B53E9758978E7A6A28CB7C7F0A57AA4EEB84E645D048F98481BA97DA` |

The 192-file ZIP passed CRC and extracted to an isolated E: directory with
the same EXE hash. Packaged API, synthetic Sage mTLS worker, interrupted
publication recovery, and native clean/duplicate/persisted/safety launches
passed. The extracted EXE passed the packaged API smoke. Inno Setup 6.7.3
compiled the unsigned installer with explicit 1.4.0 metadata.

A separate unique-AppId QA installer
`{F7A62470-5805-44CE-88F6-AB110005F7EB}` installed to
`E:\catalyst-a471-qa-install`; the installed EXE hash matched and its
packaged API smoke passed. Silent uninstall returned zero and removed the QA
EXE and its unique HKCU registration. The production registration was not
targeted. Defender custom scans of the bundle, ZIP and installer left zero
detections matching this build directory; historical unrelated detections
remain in Defender's database.

All 11 PR checks passed on exact source `a471bd0`, including the full CI
unit-test job, lint and security checks.

Artifact commit `174fc37063de0b0efb250925218c46220eb1808d` pins the
[acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/174fc37063de0b0efb250925218c46220eb1808d/acceptance-artifacts/CATalyst-a471-primary-acceptance.zip)
and [unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/174fc37063de0b0efb250925218c46220eb1808d/acceptance-artifacts/Catalyst-Setup-a471-1.4.0.exe).
Independent HTTP downloads of both immutable URLs reproduced the local hashes
above.

Read-only calls to the original-profile Sage RPC confirmed both the exact
missing-offer 404 discriminator and one existing `get_offer` response shape
from a 4,095-offer history, as recorded in the related Sage evidence files.
The still-running original TEST 7 app is the earlier `74da24c` executable,
stopped under its own monitor. No live wallet effect or quarantine resolution
was performed with this package. Exact-candidate live lifecycle, secondary
acceptance, both 24-hour windows and final review remain open.
