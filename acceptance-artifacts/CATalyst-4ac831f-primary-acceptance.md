# CATalyst 4ac831f primary acceptance package

- Draft PR: https://github.com/catalystxch/catalyst-bot/pull/220
- Exact source/runtime commit: `4ac831fbca007c9ebd7ca4000149d13bc9f3532d`
- Detached clean build: `E:\catalyst-4ac-primary-build`
- Windows EXE SHA-256: `89A29B4CA31050CEDFA657364A5905C302121FC1E288D0DAE8519A6A1FE1461C`
- Bundled `bot_gui.html` SHA-256: `25B8033FF77E8AD35A9A9A50066F7B837FDDEF0C6BD590D95874D541A6C4893C`
- Acceptance ZIP SHA-256: `1A096E69FE7790109D919A90AA18D1F477456E5199312D41BCAF7BAAB2CBE27F` (192 files; complete CRC read passed)
- Unsigned test installer SHA-256: `68D1D12CBF605E26BBEC9AA2B2E7E57205822B27348398A37B4CEE629DA106F1`

The zero-offer expired-campaign UI regression was red before the correction
and green afterward. The full Chromium suite passed 205 tests. All 11 PR CI
checks passed on the exact source commit. The unchanged backend had passed
7,148 Windows tests, 205 expected skips and 427 subtests at source `f97efd7`;
the later test/evidence child and this UI commit do not alter backend runtime.

Packaged API, mock Sage RPC, publication recovery and native
clean/duplicate/persisted/safety smokes passed. The ZIP-contained executable
matches the detached build. An isolated unique-AppId same-version sequence
installed exact `f97efd7`, upgraded to `4ac831f`, rolled back to `f97efd7`,
and restored `4ac831f`; installed EXE hashes matched after every completed
installer log. Installed API and mock Sage checks passed, as did restored API.
Final uninstall removed the QA directory and uninstall registration. Defender
custom scans of the bundle, ZIP and installer returned zero matching
detections. All package and installer checks used isolated data with no
original TEST 7 profile or wallet effect.

This package is an acceptance artifact, not a public release. The exact
`4ac831f` build has not run against the original TEST 7 profile. The prior
MZ/XCH campaign expired without a reusable fee approval; a new campaign
requires separate operator approval. Live lifecycle, restart/recovery,
interactive UI, both 24-hour windows and final review remain open. Keep PR
#220 draft with no main merge, tag, release or public-readiness claim.
