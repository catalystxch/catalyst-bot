# CATalyst PR #220 Windows acceptance package

- Exact runtime source: `f937a0c2024d119a44949928edaa69e9d588e723`
- Detached clean build: `E:\catalyst-f937-primary-build`
- `Catalyst.exe` SHA-256: `08BEEB94C1D7EA978440AD95E40C71BB89E2066C201D9D88215A8D3971B4F1CF`
- Bundled `bot_gui.html` SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- ZIP SHA-256: `A8248ACB917D14FD68307EA3CDCF6FF0A14FCE8965329BAEDF17395AC56E8355` (192 files; full CRC read passed)
- Unsigned installer SHA-256: `81E5EF7A0A25D578D32F28CE1CB93D5639574B630D3DD84A1CB727B3575FF7C8`

This source adds a fixed public-code boundary for Bootstrap cancellation errors. A case-variation regression was red before the correction; 35 targeted Bootstrap tests passed afterward. CodeQL marked the stack-trace exposure alert fixed on this source. Other exact-source PR checks were still running at publication. The previous source passed its exact-source wallet and endpoint selection of 231 tests and 25 subtests; the preceding full primary backend run passed 7,143 tests, with 205 skipped and 424 subtests.

The exact package passed API, mock Sage RPC, publication recovery, and native clean/duplicate/persisted/safety smokes. An isolated unique-AppId installer clean-installed, matched the package EXE and UI hashes, passed installed API and mock Sage RPC smokes, then uninstalled with no remaining QA registration. Defender custom scans of the package directory, ZIP, and installer completed with zero matching detections. The original live profile and wallet were untouched during package acceptance.

The exact runtime has not run against the original TEST 7 live profile. Its previous campaign has expired, and a new campaign approval has not been received. Live offer lifecycle, restart, 24-hour stability, and final UI review remain open. This is an acceptance candidate, not a public release.
