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
trade IDs. It does not start the bot or turn a Splash acknowledgement into a
peer-receipt claim.

Focused backend and Chromium tests passed, including the old unpublished-mode
rejection, published-child cleanup and restart, ambiguous-dispatch rejection,
and preservation of the successful outbox row. A disposable SQLite backup of
the original TEST 7 profile passed schema migration and `quick_check`. A
second disposable backup, combined with a fresh complete Sage read, accepted
the exact published cleanup entry and recorded the marker. These probes made
no change to the live database or wallet.

The live TEST 7 app remains on the preceding exact package in its safety
fence. No new cancellation, bot run, fee spend, or wallet effect is claimed by
these isolated checks. Full serial tests, exact package checks, CI, and live
operator handoff must be recorded before using this candidate on the original
profile.
