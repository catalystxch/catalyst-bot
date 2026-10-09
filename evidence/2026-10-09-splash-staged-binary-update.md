# Preserve an installed Splash node during a failed update

Status: source regressions, complete serial backend, 11 PR checks, focused
tests, clean package, isolated installer, independent artifact HTTP audit and
original-profile read-only rollover passed. A new exact-candidate 25-hour
monitor is in progress; live and final acceptance remain open.

## Defect and correction

- The prior `download_splash()` wrote a new download directly to the installed
  `splash.exe` path. A partial transfer or checksum mismatch then removed that
  path, deleting a previously working node. A manual reinstall or update
  attempt could therefore disable optional Splash broadcasting.
- A two-case regression was red on the prior source: both an interrupted body
  stream and a mismatched checksum left the installed binary missing.
- The fix downloads to a unique temporary file in the destination directory,
  verifies its checksum there, and uses `os.replace()` only after verification.
  Download, verification, or replacement failure cleans up the staged file
  while preserving the installed binary.
- Independent secondary static review found another availability failure:
  a checksum-valid but non-runnable candidate was promoted before its
  `--version` probe; a failed probe was logged while installation still
  reported success. The red regressions covered a nonzero exit, launch error,
  and probe timeout. The follow-up fix probes the staged executable first,
  using a `.exe` staging suffix on Windows; any failed probe preserves the
  installed bytes. A successful probe promotes atomically. The replacement-
  refusal test now reaches `os.replace()` after a successful probe.
- The official Splash latest-release API returned tag `0.2.0` with
  `splash-amd64.exe` and `splash-amd64.exe.sha256`, matching the current
  Windows asset naming and required sidecar path. This checks the current
  upstream distribution contract; it does not prove peer receipt.

## Verification

- Red: two focused preservation tests failed with `FileNotFoundError` for the
  previously installed binary.
- Green: interrupted stream, checksum mismatch, failed executable probe, and
  denied atomic replace preserve the prior bytes and remove staging files. A
  verified, runnable update replaces the prior bytes. All **32** tests in
  `test_splash_runtime_paths.py` and the broader **101-test** focused Splash
  set passed.
- Changed-file Ruff, format, and `git diff --check` passed.
- The complete serial local Windows backend passed **7,528 tests, 259 skipped,
  and 455 subtests** in 26m59s. Repository-wide Ruff passed. All **11** PR
  checks passed on the evidence-only head `cf8289a7e52665b9ab45b4451dcaf32f709551ec`.
- Exact runtime/source commit: `ce3ba7abacfb76fc327964496c7efab671c9af16`;
  test-only child: `1911a06` on draft PR #220. Independent secondary review
  used immutable Git objects and reported no security finding on the preceding
  source. A second immutable-object review of the exact correction and
  test-only child found the pre-promotion issue resolved and zero reportable
  findings; `git diff --check` and in-memory AST parsing passed. The second
  PC had about 0.893 GiB free, below its 2.5 GiB staging gate, so it did not
  run tests, build, install, launch, or mutate a wallet. Its focused static
  scan is `c8e7108f-8d26-4d1d-9106-4d77ae7c2113`.
- Clean detached Windows EXE SHA-256:
  `E082E07715172E1E42DC9D516B49241E597AC5EAE64EE7750D6766291AA4EF5D`;
  bundled UI SHA-256:
  `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB`.
  ZIP SHA-256: `A6D1D56CFD97C1C569B18BEF971C9D22F991159C0BA8381098EC2F7C067C34B1`;
  unsigned installer SHA-256:
  `8DE38908E4CF84D0332DC935806A4E9CF3FAF6277705CE2D691C34C07B595B21`.
  ZIP CRC and embedded EXE hash passed. Packaged API, synthetic Sage,
  publication recovery, native clean/duplicate/persisted/safety checks,
  unique-AppId isolated installer clean install, installed API/Sage and
  uninstall passed. Defender custom scans found zero candidate detections.
  Artifacts were committed and pushed to
  `codex/coin-prep-fee-approval-artifacts` at
  `21930d1`. Fresh independent HTTP downloads of the ZIP and installer
  matched their exact SHA-256 values and byte counts (36,636,521 and
  38,430,146 bytes).
- The earlier `1affe7b` original-profile monitor was deliberately ended for
  this candidate at about 12:52 UTC after 17 clean one-minute samples. Its
  process exit caused the expected terminal monitor error. It provides no
  24-hour credit.
- A fresh original-profile read-only preflight before exact-candidate launch
  confirmed Sage mainnet `TEST 7`, fingerprint `736588221`, synthetic CAT wallet
  ID `2` bound to the exact MZ asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
  XCH `138470301476875` mojos and MZ `780212284` atomic units confirmed and
  spendable, zero pending transactions, complete 4,095-offer history with zero
  nonterminal offers, zero DB open offers/active campaigns/unresolved
  operations, stopped prior campaign, zero authoritative fee spend and no
  approval. The latch was resolved. No Catalyst process or port 5000 listener
  was present at this checkpoint.
- Exact `ce3ba7a` was launched on the original profile as sole PID `120712`;
  its process path and EXE SHA-256 matched the clean detached package, and it
  owned loopback port 5000. Its health reported version `1.4.0` and bot
  stopped; safety was allowed with an owned renewing lease and zero blockers.
  The bound read-only monitor PID `146476` began at
  **2026-10-09T13:28:18.882162Z**. First sample in
  `E:\catalyst-stability-monitor-ce3ba7a-primary\trace-60s.jsonl` had zero
  alerts, exact process/path/hash/port, synced Sage mainnet TEST 7, unchanged
  XCH/MZ balances, zero pending and nonterminal Sage offers, zero durable DB
  open offers/active campaigns/unresolved operations, stopped bot and owned
  safety lease. The trace auditor reported `in_progress` with zero problems.
  This is a new window for the exact candidate; do not award the 24-hour gate
  before a complete continuous trace and fresh end-state review. The monitor
  is planned for 25 hours through about 2026-10-10T14:28Z.

No original-profile wallet action was taken for this fix. Real Splash peer
receipt, live active-offer lifecycle and recovery, primary and secondary
exact-candidate 24-hour windows, full UI, and final review remain open.
