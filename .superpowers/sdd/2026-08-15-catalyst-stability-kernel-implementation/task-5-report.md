# Task 5 report: durable mutation gate and run lease

## Outcome

Implemented the process-independent mutation safety boundary for CATalyst. A
durable SQLite latch, one-writer run lease, and narrowly scoped worker
delegations now gate wallet-affecting work. A process that cannot prove current
authority stays operational for bounded diagnostics while all guarded API and
AppBridge mutations fail closed with stable, non-secret responses.

The implementation initializes its gate before Flask can serve mutations and
does not contact Sage or another wallet to do so. A second desktop process
opens a loopback diagnostics server on another available port instead of
exiting. The private V50.11 code was used only as design input for strict reason
codes, stop-handler notification, and durable fencing; its CSV/file persistence
was not copied.

No live wallet, RPC, external network, GitHub operation, or user data was used
during this task.

## RED / GREEN evidence

The initial focused tests were written before `mutation_gate.py` existed:

- RED: `python -m pytest tests/test_mutation_gate.py -q` stopped during
  collection with the expected `ModuleNotFoundError: mutation_gate`.
- First GREEN: the initial latch, lease, PID, reload, and delegation contract
  passed with `18 passed`.

The first integration increment exercised Flask/AppBridge classification,
worker launch validation, and process lifecycle:

- RED: `8 failed, 19 passed`; the failures covered missing route guards,
  missing bridge fencing, unvalidated child mutations, and unavailable
  lifecycle integration.
- GREEN: `27 passed` after the narrow integration changes.

Adversarial self-review then added token secrecy, exact hostile-input
boundaries, parent epoch binding, fresh durable reads, concurrent lease loss,
and direct worker-mutator coverage:

- RED: `6 failed, 28 passed`; GREEN: `34 passed`.
- A separate raw-token inheritance test was observed RED before the worker
  removed handoff variables from its environment; it then passed.
- Static worker-call analysis found two direct `sage_login` / `sage_split`
  mutation sites before they were routed through fresh delegation validation;
  that test was observed RED and then GREEN.

Independent review identified atomic-authorization, terminal-fence, complete
write-route classification, second-process diagnostics, cancellation
revocation, cleanup release, and reinitialization gaps. Each was reproduced by
a behavior test before its production fix:

- The first review-fix selection was RED with 12 contract failures and GREEN
  with `12 passed`.
- A deterministic lock/race test then proved expired-lease takeover could race
  a newly tripped latch. It was RED before the latch/blocker recheck moved into
  the same `BEGIN IMMEDIATE` transaction, then GREEN.
- A terminal-fence precedence test was RED when durable latch resolution could
  reveal an earlier heartbeat failure; terminal process fences now remain
  irreversible for that runtime and the test is GREEN.
- A compatibility RED in the coin-prep reset tests showed stale state was being
  treated as a proven live child. The guard now rejects only a child whose
  process handle proves it is alive, preserving prior stale-state cleanup.

The final independent re-review found that wallet-start routes were still
classified as read-only and that alternate-port diagnostics performed writable
database initialization and inherited the owner's shared-service shutdown:

- RED: `6 failed, 48 deselected`; both HTTP wallet-start calls returned 200,
  the AppBridge mirror lacked guard metadata, desktop diagnostics called
  `init_database()`, and the standalone read-only helper did not exist.
- A second RED produced three failures for non-acquiring-runtime promotion,
  read-only snapshot selection, and diagnostics shutdown isolation.
- GREEN: the focused diagnostics/startup/promotion selection passed with `9
  passed`, followed by `58 passed` for the complete focused file.
- A further adversarial RED proved diagnostics still exposed ordinary GET
  handlers. The server now exposes only `/api/safety/status` in that mode;
  missing/unreadable SQLite returns bounded fail-closed status without creating
  a database. The final focused re-review passed `59 passed`.
- The first combined run exposed one order-dependent test leak after `412
  passed`: a focused live-worker test left `_coin_prep_state["running"]` set.
  Restoring that state through pytest's monkeypatch fixture made the exact
  sequence GREEN and the fresh combined suite passed all 420 tests.

## Contract

### Durable latch and coherent authorization

- Latch state and generation live in SQLite and survive module reload and
  process restart. Every mutation boundary obtains a fresh durable snapshot;
  module-local state can only add a denial, never authorize work.
- `trip()` stores only a bounded uppercase reason code, increments generation
  with compare-and-swap semantics, and invokes a registered stop handler once.
  A handler registered after a trip observes the existing latch immediately.
- Durable read failures, heartbeat failures, expiry, and lease loss create
  terminal process-local fences. Resolving a durable latch cannot clear them.
- `release_resolved()` is wallet/network/generation bound and succeeds only
  when the durable journal has no latest unresolved blocker.
- `get_mutation_authorization_snapshot()` reads the singleton latch, latest
  blockers, current lease, and optional exact worker delegation in one SQLite
  transaction. It validates complete presence and always commits or rolls back
  and closes safely. Mutation authorization and child validation do not stitch
  together independently timed reads.

### One-writer lease

- Lease acquire, heartbeat, and release use exact owner, wallet, network,
  version, and acquisition-epoch bindings. Heartbeats extend monotonically and
  cannot resurrect an expired lease.
- Independent-process races produce one owner. An expired owner can be taken
  over only when a local PID is explicitly proven dead and no latch or journal
  blocker exists. A live PID, unknown/remote host, or PID-reuse ambiguity fails
  closed.
- Heartbeat failure immediately switches the process to read-only. Best-effort
  normal and forced desktop cleanup releases the exact owned lease, even when
  bot shutdown raises.
- Reinitialization is idempotent only for the exact existing runtime binding;
  a different binding must explicitly shut down the old runtime first, so an
  owned lease cannot be silently stranded.
- An exact non-acquiring runtime may be explicitly promoted, but promotion
  reruns the complete durable acquire/dead-owner/blocker/CAS path. Heartbeat
  starts only after a successful acquisition; a terminal local fence remains
  irreversible.

### Worker delegation

- The parent creates a cryptographically random raw token and persists only
  its SHA-256 hash. The opaque delegation object does not expose the token via
  repr, `vars()`, dataclass serialization, or pickle.
- The raw token crosses only the inherited child environment. It is not put on
  the command line or logged and is deleted from the child's process
  environment before grandchildren can inherit it.
- Validation is exact for operation ID, purpose, optional worker ID, wallet
  fingerprint hash, network, state, expiry, and the current parent lease's
  acquisition epoch. Normal heartbeat version increments preserve a child,
  while release/reacquire invalidates it.
- Missing, wrong, expired, revoked, changed-parent, and dead-parent
  delegations fail before wallet construction or any Sage/CLI coin mutation.
  The explicit read-only `--sage-rpc-smoke` path remains exempt.
- Both coin-prep launch paths issue and revoke delegation. Cancellation kills
  the child and revokes/clears its delegation, and completion/failure performs
  best-effort revocation.

### API, AppBridge, and diagnostics

- Unknown write routes default to mutating. Only exact read-only POSTs and
  local monotonic controls are exempt; destructive shared-database, config,
  reset, purge, wallet, publication, and session operations are guarded.
- Guarded Flask requests return stable HTTP 423 JSON with `success: false`, a
  safe error, reason code, and bounded status. AppBridge guards return the same
  dict-shaped failure contract without raising into JavaScript.
- Bounded safety status exposes latch and current lease ownership without raw
  tokens, token hashes, arbitrary exception text, or private configuration.
- If the requested desktop/Flask port is already serving the owner, a second
  process selects another loopback port, initializes a non-acquiring gate, and
  serves diagnostics without constructing or starting the trading bot.
- Diagnostics reads the existing stability state through SQLite URI `mode=ro`
  plus `query_only`. It never initializes/migrates/checkpoints SQLite, writes a
  durable startup event, backs up the database, or stops the owner's bot,
  Sage/Chia, or Splash services. Only the bounded safety endpoint is available;
  every other API endpoint returns a stable diagnostics-read-only response.
- Wallet begin-startup and retry-connect routes are mutations because preload
  can launch Sage. Both HTTP routes and the direct AppBridge mirror require
  current lease authority before preload code can run.

## Files

- `src/catalyst/mutation_gate.py`: pure safety policy/runtime facade.
- `src/catalyst/database.py`: all latch, journal, lease, delegation, and atomic
  authorization-snapshot SQL.
- `src/catalyst/api_server.py`: startup, heartbeat, route classification,
  bounded status, shutdown, and alternate-port diagnostics.
- `src/catalyst/app_bridge.py`: direct bridge mutation boundary.
- `src/catalyst/blueprints/bot.py` and
  `src/catalyst/blueprints/coin_prep.py`: guarded operation IDs and child
  cancellation/revocation.
- `src/catalyst/coin_manager.py` and `src/catalyst/coin_prep_worker.py`:
  parent issuance/handoff/revocation and child-side revalidation.
- `desktop_app.py`: second-process diagnostics and reliable normal/forced
  release.
- `tests/test_mutation_gate.py`: focused policy, concurrency, process, API,
  desktop, launch-boundary, and adversarial coverage.

## Verification

Fresh combined functional verification on the final implementation:

- `python -m pytest tests/test_mutation_gate.py tests/test_stability_schema.py
  tests/test_api_local_guard.py tests/test_plan_02_02_api_server_unit.py
  tests/test_plan_04_06_coin_prep_endpoints.py
  tests/test_plan_02_14_coin_manager_unit.py
  tests/test_coin_prep_worker_cancel.py tests/test_coin_prep_consolidation.py
  tests/test_coin_prep_split_retry.py
  tests/test_plan_03_04_05_06_coin_prep_lifecycle_integration.py
  tests/test_plan_03_13_shutdown_resume_integration.py
  tests/test_linux_desktop_release.py tests/test_windows_process_lifetime.py
  tests/test_instance_lock.py -q`
- Result: `420 passed in 40.20s`.

Independent final re-review:

- Focused mutation-gate suite: `59 passed in 11.07s`.
- Findings: 0 Critical, 0 Important, 0 Minor.
- Verdict: READY for Task 5.

Final static verification is recorded after the last report update and before
the scoped commit: Ruff lint/format, compileall, and `git diff --check` all
pass.

Task 6 remains responsible for independently obtaining and continuously
confirming fresh wallet identity. Task 5 deliberately accepts the exact
supplied wallet fingerprint hash and network binding while enforcing it at
every safety boundary.

## Fix Round 1 — ownership and diagnostics hardening

The controller review of `b72abe7` identified six Important and three Minor
binding gaps. Each finding was reproduced before its production change.

### RED/GREEN evidence

- **I1 — terminal lease loss.** Fake-clock expiry and external lease-version
  changes were RED because time rewind or row repair reauthorized the same
  runtime. Deactivation and owner replacement were later added as adversarial
  REDs because those branches returned nonterminal diagnostic reasons. GREEN:
  every formerly owned runtime that observes expiry, deactivation, binding
  replacement, or version loss irreversibly fences itself for that process.
  Promotion and durable latch resolution cannot clear the fence.
- **I2 — heartbeat/status serialization and delegation cleanup.** A controlled
  snapshot/heartbeat interleaving produced a false `LEASE_LOST`, while a
  post-insert delegation check could strand an active row. GREEN: the complete
  authorization snapshot/evaluation is serialized with lease CAS state, and
  failed issuance revokes the exact inserted scope before re-raising. A further
  RED showed stop callbacks ran under the outer gate lock; callback delivery is
  now deferred until the outermost gate boundary releases it, preserving
  exactly-once behavior without deadlocking a synchronous gate reader.
- **I3 — delegation epoch revival.** With a frozen clock, release/reacquire
  revived an old delegation. GREEN: lease release and takeover atomically
  revoke exact parent delegations; DB rollback preserves both lease and child
  state; ordinary heartbeat still preserves the active delegation.
- **I4 — truly side-effect-free diagnostics.** Spawned missing/corrupt-DB REDs
  showed desktop diagnostics importing writable application modules. A second
  RED showed the real duplicate-launch path imported `user_paths` and opened
  the instance lock before durable-owner selection. GREEN: the minimal stdlib
  diagnostics server and lock-path resolver avoid application config/log/path
  imports, Pythonw uses `os.devnull` until ownership, and missing/corrupt
  diagnostics create no shared files. A spawned Pythonw import probe leaves the
  configured data directory absent.
- **I5 — ownership before services.** A free-port child with an active foreign
  lease entered writable initialization. GREEN: standalone and desktop startup
  perform side-effect-free durable preflight before full imports/services;
  valid pre-Task-5 SQLite databases remain upgrade candidates, while every
  canonical partial stability schema fails closed. A checkpoint deliberately
  raced between main-DB and WAL copies; the old snapshot returned no owner,
  while the stable-copy implementation detects any DB/WAL/SHM identity change
  and fails closed.
- **I6 — safe release.** REDs covered bot-stop exceptions, live/unverifiable
  threads, unkillable and unknown-PID children, in-flight permits, late thread
  and child publication, delegation cleanup, and process-exit fallback.
  GREEN: central cleanup begins quiescence, stops/aborts producers, drains
  permits, then takes definitive fresh child and thread snapshots before the
  only authorized release. Failed proof stops heartbeat and retains the lease;
  `atexit` can no longer undo that choice. The inventory now includes both
  coin-prep launchers, cancel-all, boost activation, CAT resolution, ladder,
  graceful cancel, sniper probes, and shape-fix workers. Safe cleanup still
  revokes children and releases normally.
- **M1 — local hostname aliases.** Short-name/FQDN takeover tests were RED under
  exact hostname pre-rejection. GREEN delegates locality to conservative PID
  liveness; remote/unknown hosts remain untakeable.
- **M2 — connection setup cleanup.** Injected PRAGMA/tracing setup failures
  leaked both writable and read-only SQLite handles. Both factories now close
  on every setup exception.
- **M3 — future AppBridge default deny.** Inventory and hostile dynamic-method
  REDs proved unclassified methods, and then a forged `mutation` marker without
  the decorator, could bypass the guard. GREEN requires every statically
  classified mutator to carry its operation decorator and dynamically guards
  any public callable without that proof.

Focused adversarial checkpoints on the final pre-review snapshot:

- mutation-gate suite: `105 passed in 17.91s`;
- ordered database/API/desktop/instance/coin-prep adjacent suite: `235 passed,
  1 skipped in 28.65s`;
- worker/coin-prep suite: `129 passed` (two pre-existing collection warnings);
- API/Sage/package suite: `88 passed`;
- BotLoop/shape-fix/sniper/CAT producer suite: `173 passed, 5 subtests passed`.

The two repository files named `test_api_data_sources.py` and
`test_all_apis.py` are executable audit scripts whose helper function is named
`test` and requires CLI parameters; they are not pytest suites. They were
excluded from pytest pass counts after collection correctly reported missing
fixtures. No wallet, RPC, live-network, or GitHub mutation was performed.

### Final review hardening and verification

- A late I6 RED showed GUI shutdown cancellation could run before `BotLoop`
  stopped, allowing concurrent offer recreation. GREEN stops the bot and
  proves every inventoried producer dead before wallet-wide cancellation;
  central cleanup independently repeats the proof before lease release.
- Independent review's only non-blocking note reproduced as a RED: shape-fix
  worker inventory read `_threads` without its mutation lock. GREEN snapshots
  under the owner lock and converts any lock/mapping uncertainty into an
  unverifiable producer, so cancellation is skipped and lease release fails
  closed.

Fresh post-format verification on the final snapshot:

- focused mutation gate: `107 passed in 19.42s`;
- database/API/desktop/instance/coin-prep adjacency: `313 passed in 26.87s`;
- worker/coin-prep adjacency: `154 passed in 10.50s` (two pre-existing
  collection warnings);
- API/Sage/package adjacency: `133 passed, 342 subtests passed in 2.79s`;
- BotLoop/shape-fix/sniper/CAT adjacency: `173 passed, 5 subtests passed in
  13.07s`.

Total: `880 passed`, plus `347 subtests`. Independent final bounded re-review:
0 Critical, 0 Important, 0 Minor; verdict `READY`. No resource, thread, or
test-child leaks remained. Final Ruff lint/format, compileall, and diff checks
are recorded immediately before the scoped Fix Round 1 commit.
