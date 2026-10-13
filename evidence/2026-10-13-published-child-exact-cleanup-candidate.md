# Published-child exact cleanup candidate (2026-10-13)

This candidate addresses the TEST 7 fenced recovery refusal recorded in
`2026-10-13-test7-published-child-recovery-refusal.md`. The replacement child
has a successful local Splash HTTP acknowledgement. That proves a publication
dispatch; it does not prove which independent peers received the offer. The
child is therefore treated as potentially public throughout cleanup.

The existing unpublished-child recovery path still rejects any successful
provider dispatch. A separate `published_cleanup` mode requires an exact
successful publication receipt before it records an append-only cleanup marker
in the same transaction as the abort fence. Entry, replay, successor adoption,
Task 9 authority, individual cancellation, and completion recheck the unchanged
receipt set and reject unconfirmed or ambiguous dispatch. Completion requires
proven cancellation of every exact wallet offer and an empty complete Sage
book. It retains the successful publication row as historical evidence.

The native restricted recovery page identifies the replacement as potentially
public and sends the explicit mode with the exact lineage and complete Sage
trade IDs. Independent second-PC source review found that the ordinary trading
page initially omitted this flag. A failing Chromium test reproduced the
`publication_scope_changed` request mismatch; source commit
`037e7edb199e6f9658b54361892c0dfb7a1ea2a4` now sends the same explicit
mode there and describes the child as potentially public. The affected browser
file passed 11 tests after that change. The reviewer checked the fixed ordinary
UI and native bridge again, with four read-only function probes and no remaining
mismatch found in that narrow scope. Neither page starts the bot or turns a
Splash acknowledgement into a peer-receipt claim.

The backend source commit `c7acc17543673e8ad95f17487b7599b7a78791c7`
passed all 11 exact-head CI checks and the full serial Windows backend:
**7,756 tests, 291 skipped, 457 subtests passed**. The UI-only successor
`037e7edb199e6f9658b54361892c0dfb7a1ea2a4` passed **291 Chromium tests**;
all **11** of its exact-head CI checks passed. Ruff check/format and `git diff --check`
passed. Focused tests
cover the old unpublished-mode rejection, published-child cleanup and restart,
ambiguous-dispatch rejection, and preservation of the successful outbox row.

A disposable SQLite backup of the original TEST 7 profile passed schema
migration and `quick_check`. A second disposable backup, combined with a fresh
complete Sage read, accepted the exact published cleanup entry and recorded
the marker. A repeat fresh read after the UI fix still found the two exact
active TEST 7 trade IDs, zero pending transactions and successful disposable
entry. These probes made no change to the live database or wallet.

A clean detached Windows onedir build from exact successor `037e7edb` passed
its post-build asset checks. `Catalyst.exe` SHA-256 is
`3ED7A6D8EF35FBDD53FA3D5150C85738454B07FE4F9C6BC2E28721B369496AB9`.
The bundled `bot_gui.html` matched the source byte-for-byte.
Microsoft Defender custom-scanned the package directory with zero matching
threat detections. The EXE started on port 55181 with a fresh isolated profile
and an unreachable Sage RPC endpoint. Its health response reported a stopped
bot, its newly initialized database passed `quick_check` and contained the
published-cleanup table, and it held zero offers. The exact isolated process
was then stopped and port 55181 released.

The live TEST 7 app remains on the preceding exact package in its safety
fence. No new cancellation, bot run, fee spend, or wallet effect is claimed by
these isolated checks. The original-profile operator handoff remains open.
The actual parent and child
cancellation sequence still
must be proven against fresh Sage, CATalyst, fee, and safety state before the
fence can clear. No general-readiness claim follows from these green checks.
