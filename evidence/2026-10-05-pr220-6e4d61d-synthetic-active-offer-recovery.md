# Secondary-PC synthetic active-offer recovery acceptance

Date: 2026-10-05 (Europe/London)

This is the delegated independent synthetic/mock-Sage follow-up for draft PR
#220. It exercises exact source
`6e4d61d32702330876ce5cfe26d77401f1c873ba` through active-offer creation,
stopped-app resume, authoritative recovery, cancellation, cleanup, packaged
restart, duplicate-launch handoff, and fail-closed UI paths. All wallet and
provider effects were synthetic. The original Harvestr profile and Sage wallet
were not opened or used.

## Identity

- Exact detached source HEAD:
  `6e4d61d32702330876ce5cfe26d77401f1c873ba`
- Source worktree status after testing: clean
- Secondary-PC Python 3.14.3 build `Catalyst.exe` SHA-256:
  `3C14470C235605DE8B4DD3AFDAD0DE3DA32D76489962C239CA429BF814BDD164`
- Packaged `bot_gui.html` SHA-256:
  `FD92FD2F301DD5343C3B0C5E1F96DBB13A2626712CC71508C679D24852DA0871`
- Supported test runner: Python 3.12.10, pytest 9.1.1

The secondary EXE remains intentionally distinct from the primary Python 3.12
artifact. No release or PR state was changed; PR #220 remains draft.

## Deterministic mock-wallet lifecycle

Command:

```text
python -m pytest -q tests/test_post_tibet_full_lifecycle.py
```

Result: **3 passed in 5.79s**.

The full lifecycle test used a fresh temporary database and the in-process mock
wallet. It performed and verified:

1. Balanced offer-book policy and exact fee-aware profitability floor.
2. Synthetic XCH fee-coin and CAT cohort preparation.
3. Mock-wallet offer creation across durable prepare/finalize boundaries.
4. Dexie/Splash publication outbox creation, exact Dexie acknowledgement, and
   exact discovery/visibility evidence.
5. GREEN operation followed by provider outage and RED gating. Creation,
   publication, and requote were blocked while safety cancellation remained
   available.
6. Three-sample/60-second recovery back to GREEN.
7. Provider disappearance remaining insufficient for fill accounting.
8. Exact Coinset/Spacescan chain agreement authorizing a simulated fill.
9. Deterministic replacement backoff, replacement offer creation, and secure
   mock bulk cancellation.
10. Database close/reopen recovery preserving exact durable intent/discovery
    state and the Continue/Start Over UI contract.

No live network, Sage process, key, coin, fee, or offer was involved.

## Restart, resume, authority and cleanup regressions

The focused backend group covered shutdown/resume, session state, publication
recovery, persisted cancellation cohorts, authoritative active offers, and
orphan-cleanup protection.

Result: **58 passed in 29.42s**.

Key assertions included:

- stopped app with live wallet offers reports resumable state;
- explicit `resume_existing_offers` is required and preserved;
- Start Fresh suppresses repeated resume prompting without silently claiming
  active-offer authority;
- exact active offers remain non-terminal and retain their locks;
- cleanup does not release non-terminal registry/offer authority;
- restart recovers persisted cancellation cohorts before considering fresh
  members;
- expired undispatched Dexie claims become retryable;
- ambiguous dispatched claims are suppressed rather than replayed;
- recovered offer counts are published before the runtime gate opens.

## Chromium UI paths

Focused Chromium E2E result: **3 passed, 72 deselected in 4.11s**.

The browser tests verified:

- Resume Bot sends exactly `{"resume_existing_offers": true}`;
- Cancel All consent explicitly covers every live Sage offer, including offers
  not tracked by CATalyst;
- Coin Prep waits for authoritative cancellation terminality before it starts,
  rather than proceeding on a submitted/unconfirmed cancel.

No console or browser-test failure occurred.

## Exact packaged-process recovery

Command:

```text
python scripts/packaged_upgrade_publication_recovery_smoke.py \
  --exe dist/Catalyst/Catalyst.exe --timeout 90
```

Result: **Packaged upgrade publication recovery smoke PASSED**.

This harness created a fresh temporary CATalyst profile, started an authenticated
mTLS mock Sage server, seeded two active offer projections, and simulated a
hard-killed prior owner:

- one Dexie publication claim had not begun dispatch;
- one claim had begun dispatch and then lost its transport result;
- the stale runtime lease named a deliberately nonexistent PID.

The exact compiled EXE retired the stale owner, made the undispatched claim
retryable, suppressed the ambiguous dispatched claim, cleared both stale claim
owners, reached runtime safety `allowed=true`, and owned the replacement lease.
The harness then shut down the process and mock server and deleted the temporary
profile. Dexie posting and Splash were disabled, so no external provider effect
was possible.

## Native packaged restart and mock Sage identity

`packaged_desktop_first_launch_smoke.py` passed clean native launch,
duplicate-launch handoff, persisted-profile relaunch, and malformed-identity
startup safety fallback against temporary profiles.

`packaged_sage_rpc_smoke.py` passed authenticated mTLS RPC against synthetic
fingerprint `123456789`. The mock RPC worker observed the expected synthetic
identity only.

## Harvestr non-interference

The original Harvestr profile hashes were checked immediately after all
synthetic and packaged tests and exactly matched the end of the preceding
original-profile read-only pass:

- `.env`:
  `A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`
- `bot.db`:
  `D2535E277423552EA187FA03865104B674696DA9045332F2AF8156C0AF1229F3`
- `bot.db-wal`:
  `FDB10904FE1D38B908B17F9753A887789719C75061D25388919EB920BE4F3DBE`
- `bot.db-shm`:
  `33A0052345CB793A112AFFA664DF194A4671CCFA126748EA2DD82796861D84B4`

Final inspection found no CATalyst or Sage process and no listener on ports
5000, 5001, or 9257.

## Result

PASS for the delegated synthetic active-offer creation, stop/restart, resume,
authoritative recovery, cancellation and cleanup scope. No reproducible safety
or UI defect was found. This evidence is intentionally synthetic and does not
replace a real-wallet active-offer recovery run with fresh action-bound fee
approval. The Harvestr wallet and original profile remained untouched.
