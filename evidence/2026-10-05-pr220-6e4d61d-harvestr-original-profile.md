# Secondary-PC original-profile read-only acceptance

Date: 2026-10-05 (Europe/London)

This is the delegated secondary-PC follow-up for draft PR #220. It is a
read-only wallet/economic-state check of the exact source candidate
`6e4d61d32702330876ce5cfe26d77401f1c873ba` against the original Harvestr
CATalyst profile. No campaign, setting, fee approval, Coin Prep, offer, or
wallet mutation was authorized for this pass.

## Candidate identity

- Exact detached source HEAD:
  `6e4d61d32702330876ce5cfe26d77401f1c873ba`
- Secondary-PC Python 3.14.3 build `Catalyst.exe` SHA-256:
  `3C14470C235605DE8B4DD3AFDAD0DE3DA32D76489962C239CA429BF814BDD164`
- Secondary packaged `bot_gui.html` SHA-256:
  `FD92FD2F301DD5343C3B0C5E1F96DBB13A2626712CC71508C679D24852DA0871`
- The secondary EXE is intentionally not byte-identical to the primary
  Python 3.12 artifact. The primary-reported EXE SHA-256 is
  `1BA5FD4F3367CBE61DC2E3AADA0DA3EA5AD848136345C6AAA2504BAF9F5168D7`.

The executable was re-hashed immediately before the first original-profile
launch. It ran from the exact source worktree's `dist/Catalyst` directory with
`CMM_DATA_DIR=C:\Users\M920q\AppData\Roaming\Catalyst` scoped only to the
child process.

## Authoritative backup

Before launch, the original profile was copied to:

`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\backups\harvestr-original-before-6e4d61d-20261005T1845BST`

The lean backup contains 23 files / 283,332,889 bytes and was verified with
zero copy/hash mismatches. It includes the database and WAL/SHM snapshot,
`.env`, SSL client material, Splash material, status files, and logs. Nested
historical `backups` and disposable `updates` were deliberately excluded. The
authoritative backup remains present and was not modified or deleted.

Important pre-launch hashes:

- `.env`: `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`
- `bot.db`: `9DD7D388E0DDD38733284D051B862939AF2B411380973DF42F6979BB9392DD4D`
- `bot.db-wal`: `C6E7782CDF41B127AA84B0936213BDD9500E2F87258C6657BA668D7F3693BEE4`
- `bot.db-shm`: `A1AA05675CEDEB9A7B166918FE1FC0B2335EFB83AEEF3720A2D08BF2047B8BD3`

## Sage identity and before/after state

Sage 0.13.0 read-only RPC evidence was captured before launch and again after
both CATalyst launches:

- Network: Chia mainnet
- Key name: `Harvestr test wallet`
- Fingerprint: `3702373391`
- Key kind: `bls`; secrets present
- XCH wallet ID: `1`
- MZ CAT wallet ID: `2`
- MZ asset ID:
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
- XCH confirmed/spendable/unconfirmed:
  `240800676512155` mojos (`240.800676512155 XCH`)
- MZ confirmed/spendable/unconfirmed:
  `3381521720` raw units (`3,381,521.720 MZ` at 3 decimals)
- Pending coin removals: 0 for both wallets
- Pending transactions: 0
- Sage returned 949 historical offers and ignored its
  `include_completed=False` request; CATalyst's client-side normalization
  correctly reduced them to 0 active, unexpired, fillable offers.

Every value above was identical after the test. No wallet effect occurred.

## Offline preflight

No CATalyst process or port 5000 listener existed before launch. Sage was the
only wallet owner and listened on port 9257.

The original database contained:

- one expired owner lease from PID 4284 / host `Minipc`, last heartbeat
  2026-10-02 and long past its expiry;
- a resolved runtime safety latch with no blocking operation IDs;
- zero unfinalized Coin Prep operations;
- zero unreleased reservation leases;
- zero non-terminal publication outbox rows;
- zero open CATalyst offers;
- one expired campaign still durably marked `active/bootstrap`, campaign ID
  `d61791de6807761e4a81c2a3ce58fb7b2ebad2dd012593ba0a37a122198694d5`,
  revision 1, stored fee spend `0.000037339821 XCH`.

The expired campaign was preserved rather than stopped because stopping it is
an economic/configuration mutation outside this delegated pass.

## First packaged launch

The exact package started as PID 13452 and listened only on
`127.0.0.1:5000`. Startup safely retired the dead expired lease and acquired a
new lease for the current run. The runtime safety API reported:

- `allowed=true`
- owned-by-this-run active lease
- 0 operations, prepared creations, submitted cancels, contradictory history,
  reservations, and publication claims
- fresh live-gate/durable-snapshot evidence
- bot stopped
- 0 open offers

The bootstrap status correctly failed closed for the expired campaign:
`needs_attention=true`, `cancel_required=true`,
`manual_restart_required=true`, `open_offer_count=0`, and
`unresolved_creation_count=0`. The public API displayed authoritative proven
fee spend `0.000082338193 XCH`; the stored campaign row remained unchanged at
`0.000037339821 XCH`. Source inspection confirmed that the public view
deliberately reports `max(authoritative evidence, materialized campaign row)`.
This was not a startup write or defect.

GUI observations:

1. Risk disclosure appeared and clearly stated the wallet/trading risks.
2. Continuing displayed `Sage wallet is already open` and a single
   `Connect to Sage` control.
3. `Connect to Sage` made only the read-only
   `POST /api/wallet/begin-startup` request with
   `{"auto_launch": false}` plus GET status/discovery requests.
4. The picker reported Sage 0.13.0 as supported and showed exactly one wallet:
   `Harvestr test wallet / 3702373391`.
5. The wallet card was a real visible button and no browser console or page
   error occurred.
6. The card was deliberately not activated because selecting a fingerprint
   persists configuration. Wallet identity had already been proven by direct
   Sage RPC.

The underlying dashboard simultaneously displayed the expired-campaign
warning, RED stale/single-provider market confidence, zero offers, stopped bot,
and a disabled Start reason requiring campaign stop before restart or renewal.

CATalyst closed through its native window. PID 13452 exited, port 5000 closed,
and the lease was durably released with `active=0` and a `released_at` value.

## Restart

The same exact executable relaunched as PID 14848. It acquired a new lease,
again reported all runtime blocker counts as zero, reproduced the same
expired-campaign safety state, and served the same risk-disclosure UI. The
initial and restart screenshots are byte-identical. CATalyst again closed
through its native window; the second lease was durably released and the port
closed. Sage then closed through its native window. Final inspection found no
CATalyst or Sage process and no listener on ports 5000, 5001, or 9257.

## Original-profile comparison

The post-test `.env` SHA-256 remained exactly
`A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`.

The backup and post-test databases were queried with their corresponding WAL
snapshots. The following economic/safety projections were byte-for-byte
equivalent as structured query results:

- active campaign row and stored fee spend;
- all offer status/lifecycle counts;
- Coin Prep outcome counts and zero unfinalized operations;
- reservation status counts and zero unreleased reservations;
- publication outbox state counts and zero non-terminal rows;
- approved fee reservation count (11) and total reserved fee mojos
  (109,929,257);
- resolved runtime safety latch and empty blocker list.

Ten profile file hashes changed as expected from normal process ownership,
SQLite WAL activity, window state, and log retention. Two new superlogs were
created. The two oldest 2026-10-02 superlogs were rotated out of the live
profile, but both remain intact in the authoritative backup. No configuration
or economic state changed.

## Artifacts

Artifacts are under
`evidence/artifacts/2026-10-05-pr220-original-profile/`:

- `initial.png`:
  `E58013D3F1EA5604121814E5D03CFE833E6B3C50242D3B73DC6D6D0FF1C86053`
- `wallet-startup.png`:
  `9B751CDA296897D475512F55C8F17B26AC68B16019D8EE750C3AFADC2DFFB165`
- `fingerprint-picker.png`:
  `E80E658FFE4D63F3B8622EE7AC867B41F75AF186F0DC1EF291399D456DD8056E`
- `restart.png`:
  `E58013D3F1EA5604121814E5D03CFE833E6B3C50242D3B73DC6D6D0FF1C86053`

## Result

PASS for the delegated original-profile read-only startup, identity, fail-closed
safety, wallet-picker, shutdown, and restart observations. No reproducible
CATalyst defect was found in this pass. It does not authorize or claim a pass
for stopping the expired campaign, selecting/persisting the fingerprint,
Coin Prep, fee approval, offer publication/cancellation, or full live trading.
Those actions remain intentionally untested here.
