# Native offer, public Dexie and Splash audit (2026-10-13)

Read-only checks at approximately 05:00–05:06 UTC. This is an interim live
observation, not a final 24-hour or fill acceptance result.

## Primary TEST 7

- Sole port 5000 owner remains PID 171260, executable
  `C:\catalyst\.superpowers\desktop-resume-f034-build\dist\Catalyst\Catalyst.exe`,
  SHA-256 `378E7F36ED914F2344F04DEE9F502044660AAB9AEBD76ABEB95A57D74A5A55A3`.
- The exact-PID/hash 60-second monitor began 2026-10-13T03:31:15Z. At
  05:00:41Z it contained 89 sample rows, all with process alive, bot running,
  Sage synced, safety allowed and owned lease. The 24-hour endpoint is
  2026-10-14T03:31:15Z plus complete-trace and end-state review.
- The running native CATalyst Offers accessibility tree showed one open buy
  (`376406992d61590c83092ec392348d347871c0e37d840ec042d42a2dfd268ecf`)
  and one open sell
  (`4d9e0b37ba019ba18e5bfb409adf588c2c54fd6477a9ec307b89cfb92836c8c7`),
  each with 0.25 XCH notional; pending cancels displayed as zero. The UI
  explicitly says Dexie exact and Splash local submission acknowledged, with
  peer broadcast unverified. The window capture was black while accessibility
  exposed the live DOM; this does **not** prove the visual GUI. A human visual
  check was requested and remains pending.
- Direct public Dexie v1 offer-detail reads returned HTTP success, status `0`
  and the exact matching trade IDs for the buy
  `HvcxZHxT52GdGunaq3Pvqt2xLrQri3a1VYFjmR8VgX12` and sell
  `ES23Vq37KKfNZVHZUYTf8JimPNMyhqfZ2BcHwne32Vhh`. CATalyst's Dexie
  manager treats status `0` as an active published offer.
- The actual Splash child PID 197208 listens on P2P port 11511 and metrics
  port 4001. Direct `/metrics` reported zero peers, two broadcasts, zero
  received offers and zero total connections. Reverse peer receipt is open.

## Secondary Harvestr

- The independent secondary task reported six live Sage and Dexie offers,
  70 continuous clean monitor samples, and no take or cancel. Its sampled buy
  `3CpmDHh8uWYqLb6n48kuZiFwgRssxmRFb4seMuNkqmyk` and sell
  `4qa67i2hhXQE3QjdRqzpCTm94MtNJi7BHWySGVZoQgNP` independently returned
  Dexie status `0`, with Sage trade IDs
  `b97ee4ef2ca6adcf893ee1a082b9434989bcb93c5d9d0dde6224aa43364c662f`
  and `468d822d3c415ff3065abe8a284dd7ea84131f714d85ca0e8a253c67e0538dcd`.
- Harvestr Splash reported six peers, six broadcasts, 1,286 received offers,
  but those aggregate counters do not prove receipt of a particular TEST 7
  offer. The earlier primary-to-Harvestr offer-text receipt is documented
  separately. A witnessed reverse receipt and active relevant-offer display
  on the integrated candidate remain open.

Neither original-profile process was changed during these checks. A witnessed
cross-wallet offer view/take and fill, full visual GUI traversal, both final
24-hour audits, and final review remain unverified.

## Follow-up at 05:16 UTC

- The primary exact-PID/hash monitor reached 104 contiguous sample rows through
  05:15:53Z, with zero process, bot-running, Sage-sync, safety, lease or reason-code
  failures. PID 171260 still exclusively owns port 5000 and its executable hash
  still matches the value above. This remains far short of its 24-hour endpoint.
- Independent public Dexie v1 reads again returned status `0` and the matching
  Sage trade IDs for both primary offers and the sampled Harvestr buy and sell.
  These reads establish public Dexie visibility at this instant, not fills or
  a 24-hour lifecycle pass.
- The primary Splash metrics still read `peers: 0`, `offers_broadcasted: 2`,
  `offers_received: 0`, `total_connections: 0`. The running app log for its
  03:25Z offer cycle explicitly records two `Broadcasting Offer failed:
  InsufficientPeers` warnings after successful local submission and a cleared
  Splash queue. A local submission acknowledgement is therefore not evidence
  of peer broadcast. The exact cause of the missing peer connection is open.
- The secondary task independently audited 99 contiguous clean samples through
  05:14:44Z, with the six-offer book, balances, campaign fee ledger and safety
  unchanged. Harvestr's campaign expires at 10:26:40Z, before a full 24-hour
  run. Its terminal trace and settled post-expiry book still require review.
