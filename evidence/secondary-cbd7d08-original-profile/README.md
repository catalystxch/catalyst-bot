# Secondary-PC exact-candidate transition report

Date: 2026-10-06 (Europe/London)

## Candidate identity

- Source checkout: detached, clean
  `cbd7d08e3efb99ee449efc5d5b3da2c6381f0d31`.
- Pinned package URL:
  `https://raw.githubusercontent.com/catalystxch/catalyst-bot/7b11d624d4c21ab49f49c4529b59785202b9c100/acceptance-artifacts/CATalyst-cbd7d08-primary-acceptance.zip`.
- ZIP SHA-256:
  `C34D26C480B21B05077866E00EA259E9BD583D9659B779993684C368019232E9`.
- Extracted `Catalyst.exe` SHA-256:
  `DBC3D205070D58E6C443FDC2C4BE28CE4B106359BAE285C31A87C70FBDA0AE26`.
- Exact CATalyst PID: `5656`; sole port-5000 owner.

## Safe transition

- Prior `f73a2bd` monitor PID `6096` was stopped after its final clean sample.
  Frozen trace SHA-256:
  `74A9AB3A1B8D52118B8295756D6EAC29A86745B393E29A999D68B9A27B46523E`.
- Prior CATalyst PID `5660` accepted a normal `CloseMainWindow` request and
  exited within 20 seconds. Port 5000 was released before the new launch.
- No cancellation, campaign, offer, coin-prep, fee-approval, or wallet-spend
  action was invoked.
- A lean stopped-profile backup was created at
  `authoritative-backups/pre-cbd7d08-original-profile-20261006T0330BST`.
  Its manifest SHA-256 is
  `F6032742F93E2A0FF10297F3B6E27DFEFA227CAE9BA67B880368A263CBAB3A18`.

## Wallet and economic state

- Wallet: `Harvestr test wallet`.
- Fingerprint: `3702373391` through both CATalyst and direct Sage RPC.
- Network: `mainnet` through both CATalyst and direct Sage RPC.
- CAT wallet ID: `2`.
- MZ asset ID:
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- XCH total: `240.800676512155`.
- MZ total: `3381521.72`.
- Bot stopped; CATalyst active offers `0`; Sage pending `0`; Sage fillable
  `0`; XCH/CAT locks `0`; fee holds `0`; unresolved fee operations `0`;
  reservations `0`; Coin Prep not running.
- Existing campaign remains active-but-expired with
  `cancel_required=true`; no campaign mutation was performed.
- Safety allowed; lease owned and renewing.

## Packaged UI checks

- The live risk disclosure rendered and was acknowledged through its visible
  `Continue to wallet connection` control.
- Sage connection showed exactly one selectable fingerprint,
  `3702373391`, which was verified before selection.
- The live MZ selector contained the exact required asset ID and was selected.
- Traversed Dashboard, Offers, P&L, Market Intel, Settings Live, Settings
  Setup, Logs, Doctor, Data Reset, Help, and About.
- Data-reset and trading controls were observed only; no destructive or
  wallet-affecting control was invoked.
- Playwright recorded zero page errors, zero console errors, and zero failed
  API responses during the completed traversal.

The Windows native-control helper could not initialize because its runtime
assets path was missing, including after one reset/retry. The exact packaged
native executable was still launched and verified, while all interactive
frontend checks were performed through Chromium against that executable's own
loopback server. This is a test-harness limitation, not a confirmed CATalyst
defect.

## New 24-hour monitor

- Evidence directory:
  `evidence/monitor-cbd7d08-20261006T034000BST`.
- Monitor PID: `14716`.
- Exact CATalyst PID: `5656`.
- Monitor script SHA-256:
  `0398BEC86B13FA5D7FCF4D5A921C6CB8BEA68087E498AEB70E7833FC3B1E88DC`.
- Direct Sage probe SHA-256:
  `DA68948F1A3A5B701713CFAAF2B8165EA6062904844C828378C41F31B6134957`.
- First and second samples were clean; alert count `0`.
- The existing hourly heartbeat was updated to the new monitor/PIDs/hash.

## Result

No CATalyst defect was confirmed during the transition, identity checks, or
packaged UI traversal. The exact `cbd7d08` candidate is now running stopped
against the original secondary profile under a pinned 24-hour read-only
monitor.
