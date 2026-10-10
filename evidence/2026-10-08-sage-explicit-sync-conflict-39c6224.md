# Sage explicit-sync contradiction: red/green correction

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `39c6224adf49b4ad9176737c8d2cd8c0b32b2667`. This is interim
defect evidence, not public-readiness approval.

`get_wallet_sync_status()` treated an explicit Sage `synced: true` as ready
even when the same response said only 9 of 10 coins were synced. It also
ignored over-total, malformed, or incomplete count fields in that branch.
The focused regression failed against the preceding source with actual
`sync_state='synced'` versus required `unknown`. The correction accepts the
legacy boolean-only form, but a response that supplies any count must supply
both exact nonnegative integer counts with `synced_coins == total_coins` before
explicit `true` can establish readiness. Contradictory responses remain
reachable but unready. Explicit `false` remains unready.

The focused node-sync file passed 25 tests and four subtests. Adjacent Sage
startup readiness and wallet-identity tests raised the result to 193 tests
and 17 subtests passed. Ruff check, Ruff format check, and `git diff --check`
passed. A separate read-only compatibility probe confirmed `synced: true`
without counts and with matching 10/10 counts still reports synced, while a
9/10 contradiction reports unknown. The complete serial local Windows backend
passed **7,416 tests, 246 skipped, 455 subtests**. All 11 exact-source PR
checks passed, including unit tests and CodeQL.

No frontend file changed. The bundled `bot_gui.html` SHA-256 remains
`A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609`,
the same bytes on which the previous exact candidate passed 245 isolated
Chromium tests.

## Exact detached Windows package

Built from detached exact-source checkout
`E:\catalyst-sync-explicit-39c6224-build`. The build-generated version file
is the only tracked change in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `640B1FE86D18B456F5544C44EE11C98F5C45E0FA333D3470CA65E9852F83F00A` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `ADA0A582971CFCFE8DA8A17DF72DA53659D3F3B9985076C163E4238602F0107D` |
| Unsigned installer | `643FDEC6887715E804C980E6124CBA90A1E7693EF2A7C7EE1E2A81BF0E83B808` |

The ZIP has 192 files, passed CRC, and contains the exact EXE hash. Packaged
API, synthetic Sage RPC, interrupted-publication recovery, and extracted-ZIP
API smokes passed. A unique-AppId QA installer
(`42D2B198-0A6F-4B75-9C61-755A7245D885`) installed the exact EXE to an
isolated E: directory, passed installed API and synthetic Sage smokes, and
uninstalled with its EXE and registration absent. An isolated native first
launch on port 55007 opened the CATalyst window and healthy API with the bot
stopped, then closed normally; its PID and port were absent afterward. The
original TEST 7 process and port 5000 were untouched. Defender antivirus and
real-time protection were enabled; custom scans of the bundle, ZIP and
installer completed with the six existing detection records unchanged.

The binaries and manifest were pinned at artifact commit
`ab82d704617d1a78f89f81916d26616a132e3db1`:
[ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/ab82d704617d1a78f89f81916d26616a132e3db1/acceptance-artifacts/CATalyst-39c6224-primary-acceptance.zip),
[unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/ab82d704617d1a78f89f81916d26616a132e3db1/acceptance-artifacts/Catalyst-Setup-39c6224-1.4.0.exe),
and [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/ab82d704617d1a78f89f81916d26616a132e3db1/acceptance-artifacts/SHA256SUMS-39c6224.txt).
Independent HTTP downloads of ZIP and installer matched the hashes above;
the downloaded ZIP passed CRC with 192 files.

The original TEST 7 process remains the older `eadb82a` build, stopped and
read-only after `HEARTBEAT_FAILED` during a Veeam-overlap snapshot. It has not
run the new source. Live offer lifecycle/recovery, full native UI,
independent secondary exact-candidate acceptance, both final-candidate
24-hour windows, and final review remain open. PR #220 stays draft; no merge,
tag, release, or public-readiness claim.
