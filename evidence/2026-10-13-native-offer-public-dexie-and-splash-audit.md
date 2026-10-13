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

## Read-only transport and browser checks

- From the primary PC, a 3.5-second TCP probe reached Harvestr's LAN Splash
  listener at `192.168.1.130:11511`. The same probe did not reach either
  previously resolved public introducer (`46.126.171.63:11711`,
  `178.33.32.19:11512`) or three public endpoints to which Harvestr had
  reported established connections (`65.109.166.68:11511`,
  `146.70.129.125:11511`, `178.63.169.37:13804`). This is a transport
  observation, not proof of which firewall, router, VPN or remote endpoint
  causes the failure. Primary outbound firewall default is Allow; Ethernet is
  the selected default route. Harvestr's reverse LAN probe to the primary
  Splash listener failed, so no direct two-way peer connection is proven.
- The installed Splash CLI exposes `--known-peer <MULTIADDR>` but no command to
  report the running node's public PeerId. Harvestr's current supported
  status/metrics and retained startup logs do not reveal its PeerId. The
  reachable LAN address alone is therefore not a verified complete known-peer
  multiaddress. Neither live node nor firewall configuration was changed.
- A separate headless Chromium navigation to the running Flask root returned
  HTTP 401, and the browser was closed. This expected authorization boundary
  prevents that independent browser session from substituting for a visual
  check of the native window. The human physical-screen check is still open.

## Native display recheck at 05:53 UTC

- Windows Computer Use selected the sole running CATalyst window from its
  returned app/window inventory. Its screenshot was entirely black both before
  and after activation. The accessibility tree remained populated from the
  WebView2 document and reported the Dashboard, Sage fingerprint 736588221,
  running bot, synced wallet, two active offers (one buy and one sell), live
  cycle activity and wallet balances. PID 171260 and its WebView2 child were
  still alive; the backend monitor remained clean. This is a repeat of the
  black-window observation, not proof of a process crash or a visual pass.
- An accessibility click on the returned Offers element was rejected by the
  computer-use tool because its mapped point was outside the 1000×700 window;
  no tab change occurred. The current window therefore cannot support a fresh
  full visual GUI acceptance. A physical-screen report is still pending.
- A later normal in-window `Ctrl+R` refresh on the observed Dashboard returned a
  populated, running accessibility document but the captured WebView remained
  black. No wallet control, process restart, or offer mutation was used. The
  active monitor remained clean. Recent Application Error/Windows Error
  Reporting events contained no CATalyst or WebView2 crash, and no display
  driver recovery event appeared; this does not identify the rendering cause.

## Inbound Splash rule found at 05:57 UTC

- Read-only Windows Firewall inspection found an enabled persistent GlassWire
  application rule for the exact managed
  `C:\Users\t_you\AppData\Roaming\Catalyst\splash\splash.exe` path with
  `Direction: Inbound`, `Action: Block`, `Profile: Any`. A separate outbound
  application rule allows that path; the active Ethernet network is Private.
  The inbound block is a concrete explanation for the failed Harvestr-to-primary
  LAN TCP 11511 probe, but does not establish why the primary cannot reach the
  public introducers or those public peer addresses. No firewall rule changed.
- The upstream Splash README requires a complete `/p2p/<peer-id>` multiaddress
  for `--known-peer`; upstream `src/main.rs` prints `Our Peer ID` on startup,
  but the current managed status and retained logs do not expose the already
  running Harvestr node's ID. See
  <https://github.com/dexie-space/splash/blob/main/README.md> and
  <https://github.com/dexie-space/splash/blob/main/src/main.rs>.
- A request for the operator to allow private-network inbound Splash traffic on
  this PC was sent. Direct two-PC peer receipt remains unverified.

## Recheck at 06:13 UTC

- The original TEST 7 executable still matched the pinned SHA-256 and solely
  owned local port 5000. The exact-PID/hash trace had 160 contiguous samples
  through 06:12:59Z, with no process, bot, Sage sync, safety or owned-lease
  failure; its largest intersample gap was 63.62 seconds. This is not the
  24-hour endpoint.
- Both exact primary Dexie offer IDs still returned public status `0` and the
  expected Sage trade IDs. The local Splash metrics remained at zero peers,
  zero received offers and zero connections. No cross-wallet take or reverse
  peer receipt had occurred.
- The WebView2 child process remained alive. The native window capture was
  still black after a normal in-window refresh, while its accessibility tree
  continued to expose a live running Dashboard. The desktop code selects Edge
  WebView2 and a frameless window; these observations do not isolate a renderer
  cause. No live runtime or wallet action was changed.
- The draft integration PR head `7dd011e01be261ddd27b9a0f9877c4fde1994aea`
  completed all 11 checks successfully. This is source/CI evidence; the
  original-profile live processes still run their earlier pinned binaries.
- The independent Harvestr tester audited 159 continuous clean live samples
  and left Sage's exact TEST 7 sell-offer preview untouched. Its installed
  Splash CLI has no identity-query command, metrics expose only counters, and
  retained accessible logs no longer contain its startup PeerId. A complete
  known-peer LAN multiaddress for the current process therefore remains
  unverified. No node was restarted to obtain one.
