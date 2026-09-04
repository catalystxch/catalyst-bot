# Windows wallet identity timing

During user-started parallel ladder creation on the secondary Windows PC,
12 offer attempts stopped before any wallet effect with
`WALLET_IDENTITY_STALE`. The selected wallet identity matched throughout.
A read-only probe obtained only five distinct timestamps from 32 concurrent
Sage identity reads; 27 arrivals were nonincreasing. Microsecond formatting
does not imply microsecond Windows wall-clock resolution.

The wallet facade now serializes each fresh observation together with gate
validation. A stale observation gets at most two additional fresh reads,
separated by 20 ms. The strict timestamp, identity and lease policies are
unchanged. No timestamp is synthesized and no wallet effect is retried.
Actual wallet operations run outside the observation lock. Continuation
deadlines are checked again after waiting, before dispatch and before each
adapter effect; expiry propagates through adapter safety-error handling.

The read-only verification on this PC accepted 32 strictly increasing
observations with the updated helper. Nine repeated timestamps were rejected
and reread; no other rejection occurred and no wallet effect was performed.
Mocked regression tests cover collisions at acquisition and per-effect
checks, persistent stale data, mismatched/unavailable/malformed identities,
lease loss, effect non-repetition, deadline expiry and parallel effects.

The startup watchdog also mislabeled later work as `step11_dexie_post`:
Dexie returned in about seven seconds, but the label persisted through
Splash and subsequent work until a 72-second warning. Those phases now
have separate timing labels. Offer creation error messages include the
bounded safety reason code. TibetSwap's outage warning remains unchanged;
it is already emitted once per continuous outage.

The live trading executable was not restarted or replaced for this change.
Read-only identity verification does not establish that the updated build
has completed a live trading startup. That remains a separate verification
after the user chooses when to stop the current run.
