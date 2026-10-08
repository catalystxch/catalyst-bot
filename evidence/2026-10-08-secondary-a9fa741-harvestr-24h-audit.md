# Secondary Harvestr a9fa741 stopped-profile 24-hour audit

The independent secondary-PC tester reported a **pass with environmental
warnings** for its original Harvestr stopped-profile window on runtime/source
`a9fa74115c443657e289fa8a58f996774900d44d`. This is historical
stability evidence. It is **not** acceptance of current exact runtime/source
`196caa890ebf97ed08435ac492edd6edd553f9e9`.

The reported trace ran from `2026-10-07T08:17:37.9275745Z` through
`2026-10-08T08:17:49.9144869Z` (24.003330 hours). It contained 1 start,
1,395 contiguous samples, and 1 end row, with zero parse errors, missing
samples, or gaps above 90 seconds. All 24 periodic EXE hashes and 94 direct
Sage samples matched; monitored CATalyst, wallet, offer, fee, reservation,
lease, and safety invariants had zero failures. The bot stayed stopped and no
wallet-affecting action occurred. At closeout the exact a9 process remained
the sole port 5000 owner. Read-only SQLite `quick_check` passed, with zero
nonterminal Coin Prep operations, offers, reservations, or publications.

The secondary tester observed 736 samples below 2 GiB free space and two
alerts below 1 GiB, with a minimum of 0.427 GiB. Free space recovered to
2.859 GiB by closeout, without a monitor, API, wallet, or trace failure.
That capacity limits subsequent exact-candidate work on the secondary PC.

The report is at
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\monitor-a9fa741-20261007T0915BST\FINAL-AUDIT.md`,
SHA-256 `A4D230844955B97331CDD0AD587CE4374B088359507FAF2DCD239901DD6C22BC`.
These figures are transcribed from the secondary task's final direct report;
the primary PC has not independently opened that remote file. The secondary
tester has begun isolated exact-196 source and artifact acceptance while
preserving its original Harvestr profile. Exact-196 secondary original-profile
live acceptance remains open.
