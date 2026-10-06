# Escape Doctor Report duration in the HTML modal

Draft PR #220 exact source `15047c86f9b705cbf3a8c01957fa3e45c629771e`.

The Doctor Report modal placed `report.duration_ms` from an API response into
`innerHTML` without escaping it. A Chromium regression supplied markup in that
field and reproduced an injected element before the fix. The modal now passes
the value through `escapeHtml()`. The regression and complete opt-in Chromium
suite passed **228 tests in 161.99 seconds**. Ruff check and format passed for
the modified test. The complete exact-source serial Windows backend passed
**7,277 tests, 229 skipped, and 433 subtests in 1259.06 seconds**.

The clean detached checkout at
`E:\catalyst-doctor-xss-15047c8-package` built the Windows EXE with
PyInstaller 6.21.0 and release version 1.4.0. The bundled HTML hash equals the
source HTML hash. The 192-file ZIP passed CRC and contains one EXE with the
same hash as the clean build. Inno Setup 6.7.3 compiled the unsigned installer.
The packaged synthetic Sage mTLS worker passed with mock fingerprint 123456789.
Defender custom scans of the bundle, ZIP and installer added zero detections
(six historical detections before and after).

A unique-AppId QA installer (`{EDD6C8DA-8E45-4E5C-A25C-E17C12AB35B5}`)
installed to an isolated E: directory, registered version 1.4.0, and installed
an EXE identical to the clean build. Silent uninstall exited 0 and removed the
QA EXE and registration. The original TEST 7 app remained running. An earlier
automatic approval review rejected launching a second isolated packaged EXE
before execution; that specific packaged API/recovery route was not retried
through another tool.

A second unique-AppId QA sequence (`{D3C51EAB-8DDA-44CA-9FED-F634DF4A931C}`)
installed the prior `2028c84` bundle, verified its EXE hash, then performed a
same-version upgrade to this exact bundle and verified the new EXE hash.
Both installer runs exited 0. Final silent uninstall exited 0 and removed the
QA EXE and registration. The original TEST 7 process and port owner remained
unchanged.

The ZIP, unsigned installer and checksum manifest are pinned at artifact commit
`acdf255b6ed1d79694a4b8f2d0071ca136ad8f3d` on
`codex/coin-prep-fee-approval-artifacts`. Independent HTTP
downloads of both pinned binaries matched these local SHA-256 hashes:

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/acdf255b6ed1d79694a4b8f2d0071ca136ad8f3d/acceptance-artifacts/CATalyst-15047c8-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/acdf255b6ed1d79694a4b8f2d0071ca136ad8f3d/acceptance-artifacts/Catalyst-Setup-15047c8-1.4.0.exe)

| Artifact | SHA-256 |
| --- | --- |
| Clean `Catalyst.exe` | `D2C9AD43F4F7D47E9FCFED4A1C13DE7D22BE92CE45CF086E366530A4EFC6D6C8` |
| Bundled `bot_gui.html` | `C6D2A4E7653606CA367410D97118D3985D01A4B1B9832D98763D69C5048071F3` |
| `CATalyst-15047c8-primary-acceptance.zip` | `BDFEDDA6352B91C4217D2274D988792C48213CE924B8DE13C7069CCE46FD0A7A` |
| Unsigned `Catalyst-Setup-15047c8-1.4.0.exe` | `3E1F07702AB3AD365BEC5948FE8674E292C88CC045A8F877809FE4CAE4E4E283` |

All eleven exact-source PR checks passed. At packaging, PR #220 remains draft. Exact-source original-profile rollover,
active-offer lifecycle and recovery, secondary original-profile acceptance,
both final-candidate 24-hour windows, and final review remain open. No new
campaign or wallet effect was started.
