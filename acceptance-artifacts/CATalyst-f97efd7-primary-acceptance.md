# CATalyst PR #220 Windows acceptance package

- Exact runtime source: `f97efd72b0ee65c98f6e4fd80f72e2c5f877ff7b`
- Detached clean build: `E:\catalyst-f97-primary-build`
- `Catalyst.exe` SHA-256: `68A6B935340A1AB7A4EA8850A8943E78205EB6F0F4AF4769EAF9651449C8404D`
- Bundled `bot_gui.html` SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- ZIP SHA-256: `C196BFF777532663F9BA23CAA694C3B806DCFBCC028045CD17A2352D520D04BE` (192 files; full CRC read passed)
- Unsigned installer SHA-256: `98F960CF84B6ECC78EA2C3897E83D2D0EECFFD98D505D77A8579F4B91B851C14`

An active Bootstrap campaign with malformed or timezone-free expiry now
fails closed in status and bot start. Focused regressions were red before
the fix and passed afterward. The wider Bootstrap and bot lifecycle slice
passed 293 tests and 4 subtests. Chromium passed 204 tests; Ruff/format and
all eleven exact-source PR checks passed. The full primary Windows backend
run passed **7,148 tests, 205 skipped, 427 subtests** in 26m32s.

The exact package passed API, mock Sage RPC, publication recovery, and native
clean/duplicate/persisted/safety smokes. The ZIP passed full CRC and extracted
API smoke. An isolated unique-AppId installer clean-installed, matched the
package EXE/UI hashes, passed installed API and mock Sage checks, then
uninstalled with no QA target or registration remaining. Defender custom
scans of the bundle, ZIP, and installer returned zero matching detections.
The original live profile and wallet were untouched during package acceptance.

Read-only exact-source Sage/SQLite preflight confirmed mainnet TEST 7
fingerprint 736588221, CAT wallet ID 2, exact MZ asset and zero open MZ/XCH
offers or pending transactions. The exact runtime has not run against the
original TEST 7 profile. The earlier campaign has expired and a new campaign
approval has not been received. Live offer lifecycle, restart, both 24-hour
stability windows, full UI acceptance and final review remain open. This is
an acceptance candidate, not a public release. PR #220 remains draft.
