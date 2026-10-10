# Secondary-PC exact-196 isolated acceptance

The independent Harvestr secondary tester reported a **pass for isolated
source, package, installer metadata, and read-only native acceptance** of
runtime/source `196caa890ebf97ed08435ac492edd6edd553f9e9`. This does not
complete secondary original-profile live or 24-hour acceptance.

The tester fetched the exact source and pinned artifact commit
`7e1614c7ced260cddccc0d016d253ba10b9295ff` by full SHA into a clean
detached worktree. The downloaded Git blob IDs matched the artifact commit.
The ZIP SHA-256 was
`676776A0ACF3C9D3DF9077C9497CE9C5A7C6A338EB4B8DFC61291575FA535C02`;
the unsigned installer SHA-256 was
`C1E3550885287EF0BA33C85A0EF5752C6D574F0A4B8BE3CA97AB5FBF5C07CBFF`;
the extracted `Catalyst.exe` SHA-256 was
`B350C448350961613A3C57020AC66D992F7FDD319036629CAABA009DD376A8E9`.
Its product version was 1.4.0 and its bundled frontend matched the exact
source hash.

The secondary tester ran 134 changed-source regression tests and 78
package/installer/release/native regression tests: **212 passed, zero failed**.
Ruff on changed files and forced API compilation passed. A packaged Sage worker
smoke used temporary mutual TLS mock endpoints and only read-only Sage calls.
A packaged API smoke used a dynamic loopback port, temporary `CMM_DATA_DIR`,
synthetic Sage identity, and disabled public providers; health, wallet startup,
config, diagnostics, self-test, and Doctor checks passed. A Defender custom
scan of the download and extraction directory found no new detections. The
installer was inspected but not executed on this PC.

The original a9 Harvestr app remained the sole port 5000 owner; its EXE,
profile environment, 24-hour report, and trace hashes were unchanged. Direct
Sage reads retained fingerprint `3702373391` on mainnet, the expected MZ
asset, unchanged XCH/MZ balances, and zero pending or fillable offers. No
wallet effect occurred and the primary TEST 7 wallet was not accessed.
Secondary disk space fluctuated between 1.987 and 2.906 GiB after extraction,
so a second full build was not attempted.

The full secondary report is at
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\acceptance-196caa8-isolated-20261008\REPORT.md`,
SHA-256 `64A9450DEE8568F03A39E4D9D4D07439038692C9D7D3D8E319031E1ED4573184`.
These results are transcribed from the secondary task's direct report; the
primary PC has not independently opened the remote report file. The tester
has been asked to perform a separate original-profile read-only live handoff
and exact-candidate stopped-profile 24-hour monitor, subject to fresh safety
and identity checks.
