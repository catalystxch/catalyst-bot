# CATalyst PR #220 Windows acceptance package

- Exact runtime and draft PR source: `b320dfe0335bbe6a1de101a6fbdf79ef455f2d06`
- Detached clean build: `E:\catalyst-b320-primary-build`
- `Catalyst.exe` SHA-256: `C28C740DA900B48543D1BB33C018196D4CDE62017096A8D7DBA528BB6B6D64FD`
- Bundled `bot_gui.html` SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- ZIP SHA-256: `B4DC216A6F95A6D85ED2C49A32E9D2956424EE927F18339E59370CA6DBBBEFF8` (192 files; full CRC read passed)
- Unsigned installer SHA-256: `04F41799295A54173E7AC7EEBB2493F88BF4549BF70F6D3F15632495E82C6987`

The source corrects Sage `get_offers` failure handling: `success: false` without error text now fails closed instead of proving an empty offer book. The regression was red before the fix; the exact-source wallet and endpoint selection passed 231 tests and 25 subtests afterward. The full primary backend suite on the immediately preceding source passed 7,143 tests, with 205 skipped and 424 subtests. Exact-source PR checks were still running at publication.

The exact package passed API, mock Sage RPC, publication recovery, and native clean/duplicate/persisted/safety smokes. An isolated unique-AppId installer clean-installed, matched the package EXE and UI hashes, passed installed API and mock Sage RPC smokes, then uninstalled with no remaining QA registration. Defender custom scans of the package, ZIP, and installer completed with zero matching detections. The original live profile and wallet were untouched during package acceptance.

The exact runtime has not run against the original TEST 7 live profile. Live offer lifecycle, restart recovery, 24-hour stability, and final UI review remain open. This is an acceptance candidate, not a public release.
