# CATalyst PR #220 Windows acceptance package

- Runtime source: `68f99c1f9b3369c49ded2e32e16d848976a31bed`
- Draft PR #220 head: `fd838d7761cbcc2731cd708e13165ecea9b70015` (test formatting only after runtime source)
- Detached clean build: `E:\catalyst-pr239-primary-build`
- `Catalyst.exe` SHA-256: `21E2192734A5CAB966ED732716A703411B24A2532286337E7D89B20A4AFA16A6`
- Bundled `bot_gui.html` SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- ZIP SHA-256: `C3DE2EB2EC68027CA335B987D837BD58B20DEBE94FFBFAA8A8AC0B13D9C17BE3` (192 files; full CRC read passed)
- Unsigned installer SHA-256: `0E6FE83A43E3C9189B3C7CE6C3E4C01A9E76198D153B3A9C54EEA51EEA92C187`

Exact package smokes passed for API, mock Sage RPC, publication recovery, and native clean/duplicate/persisted/safety launch. The isolated unique-AppId installer clean-installed, matched the source package EXE and UI hashes, passed installed API and mock Sage RPC smokes, and uninstalled without remaining QA registration. Defender custom scans of the package directory, ZIP, and installer completed with no matching detections.

At publication, 257 affected backend tests, 204 Chromium tests, Ruff, formatting, and all 11 PR #220 CI checks had passed. A separate full primary backend run was still in progress; live TEST 7 runtime, restart, 24-hour stability, and financial lifecycle gates were not complete. This is an acceptance candidate, not a public release.
