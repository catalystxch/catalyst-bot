# Splash local submission rejection classification

Status: source regression, clean detached package, isolated packaged runtime,
and isolated installer verified; original-profile live acceptance pending.

## Reproduction and cause

- In `6e579f4ec62857e6b7051ee94ec733def74a02bf`, any HTTP 2xx JSON
  `{"success":false}` from the local Splash submission endpoint became
  `SPLASH_APPLICATION_REJECTED` and a durable `retryable` publication.
- The outbox retry delay caps at one hour, but has no attempt ceiling. A
  permanently invalid signed offer could therefore be submitted repeatedly.
- Upstream Splash at `4c050fb180ea15e3da1b200079bc38363251174f`
  returns HTTP 200 for both accepted and rejected submissions in
  `src/main.rs`. Its `src/lib.rs` distinguishes invalid bech32, oversize
  offers, and a failed send to the local network queue:
  <https://github.com/dexie-space/splash/blob/4c050fb180ea15e3da1b200079bc38363251174f/src/main.rs>
  <https://github.com/dexie-space/splash/blob/4c050fb180ea15e3da1b200079bc38363251174f/src/lib.rs>
- The new regression was red: an invalid-offer response produced
  `requeued == 1` where the required result was no redispatch.

## Correction

- Known temporary `Failed to send offer to network` remains retryable.
- Invalid format, oversize, and unknown application rejections become
  `unresolved` with request/response digests and a normalized reason. This
  requires review and prevents automatic redispatch of the same payload.
- The Splash-specific HTTP 400 `INVALID_OFFER` path likewise stops retrying;
  Dexie's existing HTTP 400 policy is unchanged.
- HTTP 2xx `success:true` still proves only acceptance by the local node;
  remote peer receipt remains a separate acceptance gate.

## Checks and remaining gates

- Red regression: four permanent/unknown HTTP 200 cases failed with an
  incorrect requeue; the HTTP 400 invalid-offer case also failed with a
  retryable classification.
- Green focused Splash/publication suite: 202 passed and four subtests passed.
  Follow-up assertions verify the durable normalized reason and response digest
  for each rejection; a temporary send failure is retried on the next eligible
  dispatch while permanent rejections are not dispatched again.
- The secondary PC fetched the exact `1affe7b` commit and independently
  reviewed the upstream response contract, source diff, durable state
  transitions, and focused regressions. It found no source blocker. Its
  limited C: capacity prevented a fresh package build or original-profile
  acceptance, so this review does not count as secondary live acceptance.
- Runtime/source commit: `1affe7b3c05ae42c80792ef9c04fffbb53595336`.
  The follow-up assertions change tests only.
- A clean detached Windows build at that source produced EXE SHA-256
  `E80A174C264EEFD567CA9CE81E72A2FF5DD345B791FB484A63CBB7AB1FD0D822`;
  bundled `bot_gui.html` matches source SHA-256
  `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB`.
- ZIP SHA-256
  `9855193576022DA65CB5F418270FD4D416A431C5621FFC61D1708E07CD228AA7`
  contains 206 safe entries, all with valid CRC, and embeds the exact EXE.
  Unsigned Inno Setup installer SHA-256 is
  `A47AB97E19A2724B1B38DE3C24D1C58BC70346CF16D7B886A2979F2A35624991`.
  Both package files report version 1.4.0; Defender custom scans returned
  no detections for the bundle and installer.
- The exact ZIP, unsigned installer, and SHA manifest were pinned at artifact
  commit `f880fecfce1caa2e0eb0998e27f1c8ebc9592c0a` on
  `codex/coin-prep-fee-approval-artifacts`. Independent HTTP downloads of
  both files matched the recorded hashes and byte counts. These are QA
  artifacts, not a public beta release.
- Full serial local Windows backend passed **7,521 tests, 259 skipped, and
  455 subtests** in 17m36s. Repository-wide Ruff and changed-file format
  checks passed. All 11 PR checks passed on the exact runtime/source commit.
  Isolated packaged API, synthetic Sage, publication recovery, native first
  launch/duplicate/persisted/safety checks, and unique-AppId installer clean
  install, installed API/Sage, and uninstall passed. Installed EXE bytes
  matched the clean package. Defender custom scan found no detections.
- The earlier `6e579f4` original TEST 7 monitor remained alert-free through
  75 samples and a fresh preflight with matching process hash, synced Sage
  fingerprint `736588221`, wallet ID 2, the exact MZ asset, unchanged
  balances, zero pending/nonterminal offers, a stopped bot, and zero safety
  blockers. Its process was deliberately stopped for candidate rollover at
  2026-10-09 approximately 12:27 UTC. Sample 76 observed the deliberate
  process exit and connection loss. It provides **no 24-hour credit** for
  `1affe7b`; retain the raw truncated trace as historical evidence.
- The exact `1affe7b` EXE started against the original TEST 7 profile as
  PID 70800 on 2026-10-09 at 12:34 UTC. The first read-only monitor sample
  at 12:35:30 UTC bound that PID, executable path, SHA-256, and port 5000
  owner; it reported a synced Sage fingerprint `736588221`, unchanged XCH
  and MZ balances, zero pending/nonterminal offers, a stopped bot, zero DB
  open offers/active campaigns/unresolved operations, and allowed safety with
  an owned renewing lease. The authoritative trace is
  `E:\catalyst-stability-monitor-1affe7b-primary\trace-60s.jsonl`.
  The final-candidate stopped-profile 24-hour gate cannot be credited before
  2026-10-10 12:35:30 UTC plus a complete trace and end-state audit.
- A real second-peer exact-offer receipt, active-offer lifecycle, and both
  final-candidate 24-hour windows remain open. No wallet action was taken.
