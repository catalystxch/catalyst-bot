# Bootstrap campaign expiry fail-closed and exact f97efd7 package

Draft PR #220 runtime source is
`f97efd72b0ee65c98f6e4fd80f72e2c5f877ff7b`. Read-only review found
that an active campaign with an unreadable or timezone-free expiry was
treated as unexpired by both Bootstrap status and the bot-start expiry gate.
An isolated malformed-campaign regression failed in both paths before the
fix. The source now treats an unprovable expiry as requiring attention and
blocks bot start; valid future campaign behavior remains covered. No live
campaign row was changed.

The focused regressions passed (3 tests and 2 subtests). The wider Bootstrap
and bot lifecycle slice passed **293 tests and 4 subtests**. Chromium passed
**204 tests**. Ruff, formatting and `git diff --check` passed, and all
**11 exact-source PR checks** passed. The full primary Windows backend run
on this exact source passed **7,148 tests, 205 skipped, 427 subtests** in
26m32s.

## Exact Windows package

- Detached clean build: `E:\catalyst-f97-primary-build`
- `Catalyst.exe` SHA-256: `68A6B935340A1AB7A4EA8850A8943E78205EB6F0F4AF4769EAF9651449C8404D`
- Bundled `bot_gui.html` SHA-256: `7AA51FAB91DBFC439B17749F74237AC6718C93B9D1B4EACBE8F76DC9319F3130`
- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/04875cce81d11757e95a38371cefcf5ec8cbc6f2/acceptance-artifacts/CATalyst-f97efd7-primary-acceptance.zip), SHA-256 `C196BFF777532663F9BA23CAA694C3B806DCFBCC028045CD17A2352D520D04BE` (192 files, full CRC read)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/04875cce81d11757e95a38371cefcf5ec8cbc6f2/acceptance-artifacts/Catalyst-Setup-f97efd7-1.4.0.exe), SHA-256 `98F960CF84B6ECC78EA2C3897E83D2D0EECFFD98D505D77A8579F4B91B851C14`
- [Artifact manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/04875cce81d11757e95a38371cefcf5ec8cbc6f2/acceptance-artifacts/CATalyst-f97efd7-primary-acceptance.md)

The exact EXE passed packaged API, mock Sage RPC, publication recovery, and
native clean/duplicate/persisted/safety smokes. Extracted ZIP EXE matched
the build hash and passed packaged API smoke. An isolated unique-AppId
installer clean-installed to a separate QA directory, matched EXE and UI
hashes, passed installed API and mock Sage smokes, then uninstalled with no
QA target or registry key remaining. Defender custom scans of the bundle,
ZIP and installer returned zero matching detections. Independent HTTP
downloads of the immutable ZIP and installer matched the hashes above.
These were isolated checks with no original profile or wallet effect.

## Open live gates

The exact `f97efd7` EXE has not run against the original TEST 7 profile.
At approximately 2026-10-03 05:09 UTC, an exact-source read-only Sage/SQLite
preflight confirmed mainnet fingerprint `736588221`, CAT wallet ID `2`, and
MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
XCH confirmed/spendable were `138470301476875` mojos; MZ confirmed/spendable
were `780212284` atomic units. Complete 4,095-offer history had zero open
MZ/XCH buys/sells, zero pending transactions, and the primary DB had zero
open MZ offers. This remains a read-only checkpoint, not an action-time
wallet authorization. The latest stored campaign is expired despite its
`active` status, with zero fee spend and no fee approval. The operator must
manually launch
the exact package, personally acknowledge Risk Disclosure, and connect Sage;
a previous command-tool live launch was blocked before execution by
automatic approval review and was not retried through another tool.
New campaign approval and consequential wallet actions require separate
operator handoffs after a fresh identity, balances, offers, safety and ledger
preflight. Exact live lifecycle, restart/recovery, both 24-hour windows,
full UI acceptance and final review remain open. Keep PR #220 draft with
no main merge, tag, release or public-readiness claim.
