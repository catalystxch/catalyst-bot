# Exact a471 primary read-only startup

The operator-authorized native testing session switched the original TEST 7
profile from the older `74da24c` executable to source
`a471bd0b332726e77ca38719e377f480af36909e`. The older app was shut down
in the native UI with cancel-all unchecked; no Catalyst process or port 5000
listener remained before the exact clean executable was launched. The new
native UI acknowledged the testing Risk Disclosure, connected Sage, selected
**TEST 7** fingerprint `736588221`, continued without Splash, used the
previously configured Spacescan key, and selected Monkeyzoo Token (MZ/XCH).
It did not start the bot or a Bootstrap campaign.

At the initial read-only checkpoint, the sole `Catalyst.exe` was PID `159880`
at `E:\catalyst-a471-primary-build\dist\Catalyst\Catalyst.exe`, SHA-256
`8EDBD77054CE734DD766D982104F6AFD45A993BDCC9EA481CE0D7BA92CEC6BE2`.
It owned the only `127.0.0.1:5000` TCP listener. The app reported a healthy,
synced Sage wallet, stopped bot, zero open offers, inactive Bootstrap and
safety `ALLOWED` with no blockers and an owned renewing lease. Its Bootstrap
identity named mainnet, fingerprint `736588221`, wallet ID `2` and exact MZ
asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.

Independent read-only Sage RPC returned `138470301476875` selectable XCH
mojos, and the exact MZ CAT returned `780212284` atomic units both total and
selectable. Pending transactions were zero. Complete `get_offers` returned
4,095 terminal records: 3,326 cancelled, 231 expired and 538 completed;
none was fillable. The original database's previous campaign
`c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220`
remained stopped, with zero authoritative fee spend and no campaign-bound
Coin Prep fee approval. No new campaign or approval exists.

The exact-PID and executable-hash monitor is
`E:\catalyst-stability-monitor-a471bd0\monitor.ps1` (SHA-256
`694DC858A2D5A562178B71E6294152816652BD22C6A76D2F438FDA8228BE8041`).
It samples loopback safety, health and open-offer state into
`trace-60s.jsonl` every 60 seconds. Two read-only monitor instances briefly
wrote the same trace during startup; the duplicate was stopped, leaving one
monitor. The 24-hour stability window begins only after that cleanup and
must be proven from the complete timestamped trace; the initial samples are
not a completed window. No mainnet wallet effect was authorized or attempted.

PR #220 remains draft. Active-offer creation/cancellation, recovery under
wallet effect, secondary original-profile exact-candidate acceptance, both
24-hour windows and final public-readiness review remain open.
