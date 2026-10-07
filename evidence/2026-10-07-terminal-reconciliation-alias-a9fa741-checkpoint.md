# Terminal offer identity alias correction: exact package verification

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220) remains open and draft. Exact runtime/source is `a9fa74115c443657e289fa8a58f996774900d44d`; the integration branch commit `49c7e2ecc8e6e7694e3daf63fde044d2cebe56c1` has byte-identical `src/` and `tests/` files and retains the preceding evidence documents.

## Reproduction and correction

`offer_reconciliation._first_present` chose `trade_id` before `offer_id` without requiring both present aliases to agree. Against the `8a25a2a` parent, otherwise exact synthetic Sage evidence with a conflicting or malformed second alias classified `FILLED_PROVEN`; a row with a different primary alias and the target secondary alias also classified `FILLED_PROVEN` through the no-offer-row exact-proof path. A grouped cancellation with a conflicting sibling alias classified `CANCELLED_PROVEN`.

The correction requires exact 64-character hexadecimal agreement of all present aliases before accepting a row's identity. It rejects a targeted ambiguous row before the no-offer-row proof path. Six focused integrated cases passed: conflicting, malformed and reversed aliases return `UNKNOWN`, a grouped-cancellation sibling cannot prove cancellation, and equivalent uppercase/`0x` aliases remain accepted. Ruff check, Ruff format check and `git diff --check` passed. The full serial Windows backend run on committed source passed **7,342 tests, 241 skipped, 436 subtests passed** in **1,241.20 seconds**.

The secondary PC completed its review: 335 reconciliation tests and 297 adjacent cancellation/evidence tests passed on `a9fa741`. It reproduced unsafe parent outcomes for fill, single and grouped cancellation, and expiry, then verified conflicting and malformed aliases fail closed on the fix. Equivalent aliases and absent optional aliases still work. The secondary worktree and exact local/remote commit matched; no wallet or original-profile changes occurred. Its report SHA-256 is `078B361450FFE04C80E99D97167B3BED0A6B9444760CEA6AA09155D40F55DA54`.

## Clean detached Windows package

The clean detached checkout at exact source `a9fa741` produced EXE SHA-256 `403ED21AFA906B5B54D2415AFA3F14E2AE45ABBC4B0228813663298EA8123DA9` and bundled UI SHA-256 `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`. Packaged API, synthetic Sage, publication recovery and native clean, duplicate, persisted and safety smokes passed. The 192-file ZIP passed CRC and embedded EXE verification. A unique-AppId isolated QA installer passed clean install, installed EXE hash, installed API/Sage smokes, and uninstall; its EXE and registry entry were removed. Defender real-time protection remained enabled with no new detections after bundle, ZIP and installer scans.

The ZIP SHA-256 is `E9BE9CEDCD61568C857C12EAFF467D734FC3E1C5BF44C58FBDF44A6509CA2596`; unsigned installer SHA-256 is `06D65A3BD639134C68B44ECA44D0353D7B74C220DC7227A3BF851275E36B499A`. Both are pinned with the manifest at artifact commit `3ff067b2e9aaea225118e80de8df9f1de572b001`. Independent HTTP downloads matched their hashes, and the extracted downloaded ZIP EXE passed packaged API smoke. [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/3ff067b2e9aaea225118e80de8df9f1de572b001/acceptance-artifacts/CATalyst-a9fa741-primary-acceptance.zip), [unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/3ff067b2e9aaea225118e80de8df9f1de572b001/acceptance-artifacts/Catalyst-Setup-a9fa741-1.4.0.exe), [manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/3ff067b2e9aaea225118e80de8df9f1de572b001/acceptance-artifacts/SHA256SUMS-a9fa741.txt).

## Original TEST 7 after retiring the parent

The superseded `8a25a2a` EXE was shut down through the native UI with **Cancel all currently active wallet offers** unchecked while the bot was stopped and no offers were open. The exact-PID/hash stopped-profile trace ran from `2026-10-07T07:05:06Z` until intentional shutdown, and the independent port-owner trace ended after the listener closed. These are historical diagnostics, not 24-hour passes.

A direct read-only Sage mTLS snapshot at `2026-10-07T07:26:28Z` found XCH selectable balance `138470301476875` mojos, MZ selectable and total `780212284` atomic units at precision 3, zero pending transactions and zero nonterminal offers among 4,095 records (3,326 cancelled, 231 expired, 538 completed). The MZ asset remained `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`. No new campaign, Coin Prep approval, offer or fee effect occurred.

Exact `a9fa741` original-profile live acceptance, active-offer lifecycle/recovery, both 24-hour windows, exact-source PR CI and final review remain open. This package evidence is not public-readiness approval.
