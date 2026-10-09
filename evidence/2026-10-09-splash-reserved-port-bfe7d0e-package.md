# Optional Splash receive port — exact Windows candidate

## Scope

Runtime/source commit: `bfe7d0ea159b0111d1b1551662faf2334e20f1cc`
on draft PR #220. Splash remains an opt-in way to broadcast offers; new
installs default it off. Outbound broadcast and inbound receive are separate
settings. A local submission is not proof that a remote peer received an
offer.

The preceding build used a nonexistent `cfg.PORT` value for the inbound
Splash `--offer-hook`, silently choosing port 5000 even if CATalyst had
reserved another Flask port. The fix reads the reserved
`CATALYST_FLASK_PORT` set before runtime services start and validates the
port range. The regression failed at port 5123 before the fix and passes
afterward. The four receive-on/off and port-5000/5123 cases passed, along
with 30 related Splash/runtime tests and changed-file Ruff.

## Exact verification

The complete serial Windows backend passed **7,509 tests, 259 skipped, and
455 subtests passed** in 1465.60 seconds. Complete local Chromium passed
**258 tests** in 170.80 seconds, and the secondary PC independently passed
the same 258 tests in 163.84 seconds. All 11 exact-head PR checks passed,
including unit tests. A clean detached Windows build succeeded.
Repository-wide Ruff check and format check passed.

The exact package passed packaged API, synthetic Sage RPC, publication
recovery, clean/duplicate/persisted native startup, ZIP CRC and safe-path
checks, extracted-ZIP API, and a unique-AppId current-user QA installer
clean install, installed API/Sage, exact 192-file bundle comparison, and
uninstall. The QA install used an isolated destination and did not launch
the saved TEST 7 profile. The isolated QA uninstall key and directory were
absent after uninstall. Windows Defender custom scans of the executable,
ZIP and installer returned clean. ZIP, installer and manifest were pinned
at artifact commit `5151e9dd02f99664dd6172dbe07f1273d15a39b7`.
Independent HTTP downloads of the ZIP and installer matched local lengths
and SHA-256 hashes. The downloaded manifest matched after normalizing Git
line endings.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-splash-bfe7d0e-build\dist\Catalyst\Catalyst.exe` | `7C9A180E39E3D398377AD80C2F8AC490DB923D158E445779465DD0E35D478ACC` |
| Bundled `bot_gui.html` | `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5151e9dd02f99664dd6172dbe07f1273d15a39b7/acceptance-artifacts/CATalyst-bfe7d0e-primary-acceptance.zip) | `207F80EBBF8C50F306FE34EFA6FCD78DCD074DA4C48825F0EEF74D0B4F2B2730` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5151e9dd02f99664dd6172dbe07f1273d15a39b7/acceptance-artifacts/Catalyst-Setup-bfe7d0e-1.4.0.exe) | `04AC3DE68FB1AA27C908C6FE11EAE7EEBBDC49067ECEA68649F65295BA30A941` |

The secondary PC independently verified the exact source and startup port
flow, ran 20 focused tests, all 258 Chromium tests, and changed-file Ruff,
and left its source checkout clean. It also downloaded the immutable ZIP,
installer and manifest in memory over HTTP. The ZIP and installer hashes,
embedded EXE/UI hashes and manifest matched. The ZIP contained 242 safe,
unique entries, passed complete CRC testing, and had no symlink or encrypted
entries. The installer had no embedded Authenticode certificate. Its limited
C: space precluded extraction, installation or live acceptance; C: free
remained 1,315,758,080 bytes (~1.225 GiB). The secondary original profile,
wallet and Splash daemon were untouched.

## Live gates

The original TEST 7 process is still the historical `515b41c` executable,
with a stopped bot and no open offers. That monitor cannot count toward the
`bfe7d0e` endurance gate. An exact-PID/hash read-only monitor and auditors
are prepared but have **not** started; their negative guard rejected the old
PID/path before writing any trace. An earlier automatic approval review rejected
an isolated Splash daemon launch. Do not route around that rejection by
automatically starting the new package under the saved Splash-enabled
profile. After final package verification, the operator must close the old
app and manually start the exact new executable. Recheck process/hash,
Sage identity, balances, pending transactions, offers, safety, campaign
and ledger before any live action.

Remote Splash peer delivery, active-offer lifecycle/recovery, full native
UI, independent secondary original-profile acceptance, both exact-candidate
24-hour windows, and final review remain open. A new campaign and fee scope
have not been specifically approved. PR #220 and website PR #89 remain
draft; no beta has been deployed and no public-readiness claim is made.
