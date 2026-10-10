# API exception and Sage certificate boundary hardening

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) remains open against `main`.
The exact runtime/source commit is `65e496842c6dfd3da1e96077320e72566431ec56`.
Test-only child `8f5179fc423eee1abf6e47c537dd2f19e7ec0355` adds only tests;
its later descendants change only documentation and evidence.

## Corrections

- `/api/full-node/status` now returns a fixed message when the watcher fails.
  Its exception text no longer enters the JSON response.
- Sage certificate discovery accepts only a selected configured or detected
  Sage data root and passes the matching trusted root to discovery. Certificate
  validation rejects network paths before resolving them. A selected pair
  must still match `wallet.crt` and `wallet.key` under a known Sage `ssl` folder.
- Provider diagnostics, Coin Prep tier drift, and `/api/status` risk inventory
  failures now return fixed error text instead of raw exception details.
- Three disabled debug handlers are fixed 404 stubs. In particular, the retired
  Sage single-offer handler contains no offer creation or cancellation path.
  Two legacy tests were updated to assert the disabled behavior and no wallet
  or database calls.

Each behavior change had a focused failing regression before its correction.
The final focused API/security selection passed 76 tests and 4 subtests; the
two updated debug-route tests passed. Ruff, format, and `git diff --check`
passed. The complete serial Windows backend on the final test-only head passed
**7,433 tests, 246 skipped, and 455 subtests** in 22 minutes 8 seconds. All
**11 PR checks** passed on that head, including CodeQL, Semgrep, and unit tests.
The bundled frontend is byte-identical to `7ce8ffa`, whose Chromium suite
passed 245 tests.

## Exact detached Windows package

Built from a clean detached checkout of runtime source `65e4968` at
`E:\catalyst-security-65e4968-build`. Only build-stamped `_version.py` is
modified in that checkout. The package is unsigned and is acceptance evidence,
not a public release.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `5AD6C52854CC3B9D45F08D07D0B3C8F250CCB2E6CCC63BEF9B914DE6520800F0` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `0C50D6D961BADFD22FABA02A5BBD4681A9C6D230DA3E0416EE5300990DECC5BA` |
| Unsigned installer | `C1BA93DDA5B148E02E26E36A83F21BDA078804EEEC27B1D7413C3422712D3435` |

Packaged API, synthetic Sage RPC worker, interrupted-publication recovery, and
native clean/duplicate/persisted/safety launch smokes passed. The ZIP contains
192 files, passed CRC, and its embedded EXE hash matches the detached build;
its extracted app passed the API smoke. A separate current-user QA installer
with unique AppId `2E582B41-0AFA-4E8A-AA2D-AFFF01B645AC` installed the exact
EXE, logged version `1.4.0.0`, passed installed API and Sage smokes, and
uninstalled with its EXE and registration absent. The original TEST 7 process
remained PID `120856` in its separate path. Defender antivirus and real-time
protection were enabled; custom scans of the bundle, ZIP, and installer left
the prior six detection records unchanged.

A second isolated installer run used unique QA AppId
`EE494A15-BA06-4454-9425-8BA9D917D32C` under
`E:\catalyst-security-65e4968-upgrade-qa`. It installed the prior verified
`7ce8ffa` package (EXE SHA-256
`47198CA321C9E36692929D9661EEF99D51037743AB5EAB71D42022DDE3C92B77`),
upgraded in place to the exact `65e4968` package, rolled back to `7ce8ffa`,
and restored `65e4968`. All four installers exited successfully. At each
step the installed EXE hash matched the expected version, and a QA sentinel
in the install directory survived. The restored package passed installed API
and synthetic Sage smokes. QA uninstall removed the EXE and unique current-user
registration while retaining the sentinel. Logs are in that QA directory.
This exercises same-version replacement and rollback; it does not simulate a
crash during installation. The original TEST 7 process was not touched.

The binaries and manifest were pinned at artifact commit
`51560ec34ba40b39c0f1a83a55211ac3b8f2c6ac`:
[ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/51560ec34ba40b39c0f1a83a55211ac3b8f2c6ac/acceptance-artifacts/CATalyst-65e4968-primary-acceptance.zip),
[unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/51560ec34ba40b39c0f1a83a55211ac3b8f2c6ac/acceptance-artifacts/Catalyst-Setup-65e4968-1.4.0.exe),
and [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/51560ec34ba40b39c0f1a83a55211ac3b8f2c6ac/acceptance-artifacts/SHA256SUMS-65e4968.txt).
Independent HTTP downloads of the ZIP and installer matched the hashes;
the downloaded ZIP passed CRC and contained the exact EXE.

## Live boundary and remaining gates

At the package checkpoint the original TEST 7 process was still the older
`eadb82a` build, PID `120856`, executable SHA-256
`8E8EFDD7A175FE50D5BF168AF0EB4D6A4E7FB557BC8C6B68B2111C834356EF02`.
It was stopped with `HEARTBEAT_FAILED` safety. This exact candidate has not
run against that profile, and no wallet effect was attempted here. The
secondary PC's existing `a9fa741` read-only 24-hour monitor is a distinct
historical-candidate gate and cannot prove a `65e4968` stability window.

Original-profile live active-offer lifecycle and recovery, independent
secondary exact-candidate acceptance, full native UI, both final-candidate
24-hour windows, and final review remain open. No new TEST 7 campaign or fee
approval has been received. Keep PR #220 draft; do not merge, tag, release,
or claim public readiness.
