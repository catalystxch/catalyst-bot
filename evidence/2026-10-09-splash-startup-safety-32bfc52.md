# Optional Splash startup: ownership and loopback binding

Exact source `32bfc526d37e5599bf9612a60ccfcca4c8c90902` on draft PR #220
retains Splash as an opt-in offer broadcaster. The Dexie path and wallet
mutation rules are unchanged.

## Findings and corrections

The preceding `SplashNode._kill_stale_process()` treated a process name
containing `splash` and an occupied submission port as proof of CATalyst
ownership. On Windows it used `taskkill /F`; on Unix, `os.kill`. A standalone
operator-managed Splash process could be terminated. The replacement fails
closed when that port is occupied, both before the manager thread starts and
again before launch. It never kills a process solely by name and port.

A custom `SPLASH_SUBMIT_URL` with a LAN host also flowed into the managed
daemon's `--listen-offer-submission` argument. The old loopback comment was
inaccurate for addresses other than `localhost` or `0.0.0.0`. Managed startup
now requires an explicit HTTP URL on `localhost` or `127.0.0.1` with a valid
port, no userinfo, non-root path, query or fragment. The daemon binds
`127.0.0.1` at that port. Invalid URLs fail before the manager thread starts.
The local submission interface stays private while opted-in Splash can still
broadcast offers to peers.

## Red/green and independent evidence

- A Windows regression simulated an independent `splash.exe` listener on port
  4000. Before the fix, launch did not raise and could reach `taskkill`; after
  it, neither termination nor a new `Popen` occurs.
- A synchronous start regression previously returned true and started a
  manager thread despite the occupied port. It now returns false.
- LAN and wildcard URL regressions previously reached `Popen` with nonloopback
  bind arguments. They now raise before launch; synchronous start returns
  false without a thread.
- The focused Splash suites passed **144 tests and four subtests** on the exact
  source. The independent secondary PC reviewed that source, found no further
  defect, and passed the same focused tests and changed-file Ruff.
- Repository-wide Ruff check/format, all **11** exact-source PR checks, and
  the complete isolated Chromium suite (**258 passed**) succeeded. The full
  serial Windows backend passed **7,514 tests, 259 skipped, and 455 subtests**
  in 2,385.67 seconds, with exit code 0.

## Exact Windows package

A clean detached build produced the following files. Package API, synthetic
Sage, publication recovery, native clean/duplicate/persisted/safety, ZIP CRC,
extracted ZIP API, isolated unique-AppId installer clean install, installed
API/Sage, byte-identical 192-file comparison, same-AppId update/rollback/
restore, and uninstall passed. Defender custom scans of EXE, ZIP and installer
returned no matching detection. The original TEST 7 profile was untouched.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-splash-32b-build\dist\Catalyst\Catalyst.exe` | `4EB01C744766E7A277F6B50646A53BD55FA0BAE993D1E76DAC541EA9224BB3C7` |
| Bundled `bot_gui.html` | `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f8c2e6227a439c248a7305e21b9a8f9bf3003236/acceptance-artifacts/CATalyst-32bfc52-primary-acceptance.zip) | `38907A1DF2B4397A90AB81F756B99866369E22FDCA323DB1F8AE47A45DAF968E` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/f8c2e6227a439c248a7305e21b9a8f9bf3003236/acceptance-artifacts/Catalyst-Setup-32bfc52-1.4.0.exe) | `0C06B87BE8229EC199664868D59FE86107A75377490D8B11E77653468540C84A` |

The ZIP, installer and checksum manifest were pinned at artifact commit
`f8c2e6227a439c248a7305e21b9a8f9bf3003236`. Independent primary HTTP
downloads of both binaries matched their local byte counts and hashes.
The secondary PC independently streamed both pinned HTTP files without writing
the packages to its space-constrained C: drive. It matched both byte counts and
hashes, confirmed 242 unique safe ZIP paths, 192 files, no encryption, a
complete CRC pass, and the embedded EXE and UI hashes. The ZIP has no internal
`ACCEPTANCE_BUILD.txt`; provenance is the separately pinned checksum manifest
and source commit, not an inferred embedded manifest. The canonical installer
remains unsigned; the separate unique-AppId QA variant was used for install
and rollback tests so the original registration was not touched.

Remote peer delivery, active-offer lifecycle/recovery, independent secondary
original-profile acceptance, both exact-source 24-hour windows and final
review remain open. The current original TEST 7 app is a historical binary;
there was no wallet or original-profile mutation from this source change.
Prior packages, including `bfe7d0e`, are superseded.
