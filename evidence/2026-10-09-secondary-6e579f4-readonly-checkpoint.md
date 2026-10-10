# Secondary PC exact `6e579f4` read-only checkpoint

The independent secondary task `01a0a17d-9e97-75d3-bbeb-b4a736167870`
reported this checkpoint from the Harvestr PC at 2026-10-09T11:16–11:18Z.
It is isolated source and read-only original-profile evidence, **not** exact
candidate secondary live acceptance.

The secondary verified Git object
`6e579f4ec62857e6b7051ee94ec733def74a02bf`, its parent, and the
docs-only nature of PR head `b91a22400f0b3a9e47d4ac26da7b2d86f9c2af10`.
An exact-source `test_publication_outbox.py` run passed **103 tests** in
28.61 seconds; changed-file Ruff and `git diff --check` passed. Earlier
independent checks for this candidate passed the broader 262-test/four-subtest
Splash/publication suite, 12-case transport matrix, and pinned
ZIP/installer/manifest/CRC identity checks. The secondary checkout was clean
after its isolated test.

The sole secondary CATalyst process was historical `196caa8`, PID 15436,
SHA-256 `B350C448350961613A3C57020AC66D992F7FDD319036629CAABA009DD376A8E9`.
It alone owned loopback port 5000. The exact `6e579f4` package had **not**
run on the original secondary profile. Direct read-only Sage checks showed
mainnet Harvestr fingerprint 3702373391, wallet ID 2 in the campaign ledger,
the exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
240.800676512155 XCH and 3381521.720 MZ owned/selectable, zero pending
transactions, and zero fillable offers among 949 historical records.
Unauthenticated private status endpoints returned HTTP 401.

The secondary DB quick check was `ok`; the historical runtime held a renewing
lease with safety resolved and zero blocking operation IDs. It had zero
active offers, nonterminal Coin Prep work or publications, active reservations,
and fee holds. Historical campaign `d61791...` remained marked active but
expired on 2026-10-03; its recorded fee spend was 0.000037339821 XCH.
It was not changed during this check. The historical `196caa8` monitor is
non-clean: 1,392 samples, 755 alert-bearing rows, and one 123.162-second
gap. None of that qualifies as an exact `6e579f4` 24-hour window.

Secondary C: free space fell from approximately 1.019 GiB at 11:16:03Z to
0.934 GiB at 11:18:12Z. The secondary performed no cleanup, package launch,
profile write, wallet action, or daemon launch. Exact-package live acceptance
and the secondary 24-hour window remain open. The critically low space and
expired-but-active historical campaign require reviewed handling before any
candidate switch or wallet effect. PR #220 remains draft.
