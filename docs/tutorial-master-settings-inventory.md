# CATalyst Tutorial Master Settings Inventory

Generated from the 2026-05-24 settings deep-dive UI audit.

Use this as the source checklist for tutorial videos and prompt generation. It combines:

- Full-tab screenshots from `output/settings-audit-screenshots-full/`
- DOM control extraction from `controls-inventory-full.json`
- Frontend source checks in `bot_gui.html`
- Backend config/behavior checks in `src/catalyst/`

Coverage legend:

- `Captured`: visible in the saved full-scroll screenshot set.
- `Conditional`: user-facing, but only appears after a specific state/action.
- `Backend`: not directly visible as a user setting, but important for explaining what the bot does.

## Screenshot Coverage Result

Primary tabs were captured top to bottom:

- `Dashboard`: captured.
- `Offers`: captured, including Active, Buy/Sell filters after the fix, and History.
- `P&L`: captured.
- `Market Intel`: captured.
- `Settings > Live`: captured.
- `Settings > Setup`: captured, full inner scroll.
- `Logs`: captured.
- `Data Reset`: captured.
- `Help`, `About`, and previous-session resume modal: captured.

Items not fully captured in the final screenshot folder:

- Startup onboarding flow: risk disclosure, Sage connect, wallet picker, Sage change-address prompt, Splash gate, Spacescan gate. These appeared during testing, but only the resume modal was saved into the final full folder.
- Destructive or state-changing modals: Cancel All confirmation/progress, Shutdown confirmation/progress, reset confirmations.
- Conditional workflow modals: coin prep confirmation/progress/history choice, deposit advisor, Close the Gap confirmation, update modal, crash recovery panel, wallet picker, skip-coin-prep warning, start-without-prep warning, preset-name prompt.
- Help modal inner tabs: overview modal was captured, but each individual help tab was not separately screenshot-captured.

## Front-Facing Settings And Controls

### App Shell And Navigation

| Area | Control | Coverage | What it does |
|---|---|---:|---|
| Sidebar | Dashboard | Captured | Opens the main command center and bot status view. |
| Sidebar | Offers | Captured | Opens active offers and fill history. |
| Sidebar | P&L | Captured | Opens profit/loss, inventory position, spread, and sniper stats. |
| Sidebar | Market Intel | Captured | Opens price history, orderbook, pool, Spacescan, DBX, and Splash intelligence. |
| Sidebar | Settings | Captured | Opens Live and Setup configuration views. |
| Sidebar | Logs | Captured | Opens live diagnostics and debug tools. |
| Sidebar | Data Reset | Captured | Opens reset actions for P&L, offer history, and runtime stats. |
| Sidebar | Theme toggle | Captured | Switches light/dark theme. |
| Sidebar | Help | Captured/Partial | Opens help modal. Individual help tabs should be recorded separately. |
| Sidebar | About | Captured | Opens app/version/about modal. |
| Sidebar | Shutdown App | Conditional | Opens shutdown modal and optional cancel-offers-before-close flow. |
| Sidebar | Update badge | Conditional | Appears only when an app update is available. Opens update/release modal. |
| Desktop titlebar | Shutdown, Help, Minimize, Maximize, Close | Conditional | Native window controls and shortcuts to shutdown/help. |

### Startup And Onboarding Flow

| Step | Control | Coverage | What it does |
|---|---|---:|---|
| Risk disclosure | Continue to wallet connection | Conditional | Confirms the user understands trading risk. |
| Risk disclosure | Close app | Conditional | Exits before wallet connection. |
| Sage startup | Launch Sage for me | Conditional | Starts Sage from the app if possible. |
| Sage startup | I'll open it myself | Conditional | Lets user start Sage manually. |
| Sage RPC | Connect to Sage | Conditional | Attempts wallet RPC connection. |
| Sage RPC | Retry | Conditional | Rechecks Sage/RPC readiness. |
| Sage certificate | Certificate path input | Conditional | Lets user provide Sage `wallet.crt` path. |
| Sage certificate | Browse | Conditional | Opens a certificate file picker. |
| Sage certificate | Auto-Detect | Conditional | Finds likely Sage certificate path. |
| Sage certificate | Save and Continue | Conditional | Persists certificate path and continues. |
| Wallet picker | Fingerprint card selection | Conditional | Selects the Sage wallet fingerprint. |
| Sage change address | Yes - auto-apply it | Conditional | Enables startup change-address application. |
| Sage change address | No - keep wallet unchanged | Conditional | Leaves Sage change address untouched. |
| Splash gate | Install | Conditional | Installs/sets up Dexie Splash where available. |
| Splash gate | Start | Conditional | Starts the Splash node. |
| Splash gate | Retry | Conditional | Rechecks Splash state. |
| Splash gate | Skip - continue without Splash | Conditional | Continues without Splash P2P. |
| Spacescan gate | Continue with configured key | Conditional | Uses saved Spacescan key. |
| Spacescan gate | Key input | Conditional | Lets user paste Spacescan API key. |
| Spacescan gate | Save key | Conditional | Persists Spacescan API key. |
| Spacescan gate | Skip | Conditional | Continues with limited/no Spacescan features. |
| Previous session | Start Fresh | Captured | Clears/starts a fresh session path. |
| Previous session | Load Previous Session / Start Bot Now | Captured | Resumes active offers/session state. |

### Dashboard

| Control | Coverage | What it does |
|---|---:|---|
| Trading pair selector | Captured | Chooses CAT/XCH pair for dashboard/start flow. |
| Refresh pairs | Captured | Reloads available CAT pairs. |
| Review Settings | Captured | Opens Settings. |
| Resume Bot Now / Start Bot Now | Captured | Starts/resumes the bot when ready. |
| Start Fresh for Changes | Captured | Routes to fresh-start flow when resuming locked settings. |
| Start Bot | Captured | Starts trading loop. |
| Stop | Captured | Stops trading loop. |
| Cancel All | Captured | Opens cancel-all-offers flow. |
| Wallet fingerprint display | Captured | Opens wallet picker. |
| Token website link | Captured | Opens token website if known. |
| Full chart link | Captured | Opens Market Intel. |
| View full logs link | Captured | Opens Logs. |
| Dexie Orderbook link | Captured | Opens current pair on Dexie. |
| TibetSwap Pool link | Captured | Opens current pair pool. |
| Spacescan link | Captured | Opens token/address data. |
| Refresh balances | Captured | Refreshes wallet balances. |

Dashboard metrics to explain in videos:

- Startup readiness checklist.
- Active settings snapshot.
- Market health/adverse selection guard status.
- Wallet and coin inventory.
- Spare tier group coins.
- Reserves and top-up pool.
- Performance, loop, fill rate, P&L, toxicity, on-chain risk.
- External market links.

### Settings - Live

These hot-reload on the next bot loop and are safe to change while running.

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Dynamic Spreads toggle | `DYNAMIC_SPREAD_ENABLED` | Captured | Turns dynamic spread engine on/off. |
| Inventory Mgmt toggle | `INVENTORY_ENABLED` | Captured | Turns inventory skew on/off. |
| Sniper toggle | `SNIPER_ENABLED` | Captured | Turns sniper/probe behavior on/off. |
| Competitor Aware toggle | `COMPETITOR_AWARE_ENABLED` | Captured | Turns Dexie competitor nudges on/off. |
| Dynamic Base Spread slider | `BASE_SPREAD_BPS` | Captured | Changes dynamic spread starting point. |
| Base Spread Apply | `BASE_SPREAD_BPS` | Captured | Saves live spread slider value. |
| Base Spread Cancel Move | `BASE_SPREAD_BPS` | Captured | Reverts pending live spread slider move. |
| Skew Sensitivity slider | `SKEW_INTENSITY` | Captured | Changes how strongly inventory affects spreads. |
| Skew Apply | `SKEW_INTENSITY` | Captured | Saves live skew slider value. |
| Skew Cancel Move | `SKEW_INTENSITY` | Captured | Reverts pending live skew slider move. |
| Close the Gap | Boost manager state | Captured/Conditional | Opens manual probe strategy confirmation. |
| Close the Gap starting aggression | Gap strategy | Conditional | Starts near floor/default, balanced, cautious, or very cautious. |
| Close the Gap sniper probe size | Gap strategy / `SNIPER_SIZE_XCH` | Conditional | Sets each manual probe size. |
| Close the Gap Start | Gap strategy | Conditional | Starts manual tightening probe ladder. |

### Settings - Setup

Setup settings are persisted. When the bot is running, most apply on restart rather than immediately.

#### Wallet Session

| Control | Config/backend | Coverage | What it does |
|---|---|---:|---|
| Change Wallet | Sage fingerprint/session | Captured | Opens wallet picker. Blocked while bot is running. |
| Sage certificate path | `SAGE_CERT_PATH` | Captured | Path to Sage wallet RPC certificate. |
| Browse certificate | `SAGE_CERT_PATH` | Captured | Opens file picker. |
| Auto-Detect certificate | `SAGE_CERT_PATH` | Captured | Finds default Sage certificate path. |
| Save Certificate | `SAGE_CERT_PATH` | Captured | Persists certificate path. |

#### Configuration Presets

| Control | Storage | Coverage | What it does |
|---|---|---:|---|
| Save current as preset | localStorage | Captured | Saves the current Setup form under a user name. |
| Preset list/load/delete | localStorage | Conditional | Appears when presets exist. |
| Save as preset footer checkbox | localStorage | Captured | Saves the current config as a preset during save. |
| Preset name prompt | localStorage | Conditional | Asks for a preset name. |

#### Trading Pair

| Control | Config/backend | Coverage | What it does |
|---|---|---:|---|
| Choose Trading Pair | CAT metadata/session | Captured | Changes selected CAT/XCH pair when safe. |
| Hidden pair selector | `CAT_ASSET_ID`, resolved wallet/pair metadata | Captured | Backing select used by frontend logic. |

#### Liquidity Mode

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Two-Sided | `LIQUIDITY_MODE=two_sided` | Captured | Quotes both buy and sell ladders. |
| Buy Only | `LIQUIDITY_MODE=buy_only` | Captured | Quotes only buys to accumulate CAT. |
| Sell Only | `LIQUIDITY_MODE=sell_only` | Captured | Quotes only sells to distribute CAT. |
| Apply suggestion | `LIQUIDITY_MODE` | Conditional | Appears when wallet balance is clearly one-sided. |

#### Reserves

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Reserve quick buttons 5/10/25/50% | `XCH_RESERVE`, `CAT_RESERVE` | Captured | Quickly sizes reserve floors. |
| XCH Reserve slider/input | `XCH_RESERVE` | Captured | XCH amount the bot must not spend. |
| CAT Reserve slider/input | `CAT_RESERVE` | Captured | CAT amount the bot must not spend. |
| Smart Settings | Many config keys | Captured | Recalculates run settings from wallet balance, pair liquidity, volatility, and guardrails. |
| Topup pool percent | `TOPUP_POOL_PCT` | Captured | Percent of available balance assigned to runtime top-up pool. |
| XCH topup budget | `TOPUP_POOL_XCH` | Captured | XCH budget available for future buy-side coin prep/top-ups. |
| CAT topup budget | `TOPUP_POOL_CAT` | Captured | CAT budget available for future sell-side coin prep/top-ups. |

#### Safety And Limits

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Enable Buy Side | `ENABLE_BUY` | Captured | Allows buy offer creation. Also derived from liquidity mode. |
| Enable Sell Side | `ENABLE_SELL` | Captured | Allows sell offer creation. Also derived from liquidity mode. |
| Dynamic Band | `DYNAMIC_LIMIT_PCT` | Captured | Price band around reference price for quote sanity. |
| Step-Change Guard | `MAX_STEP_CHANGE_FRACTION` | Captured | Prevents large mid-price jumps from immediately moving quotes too far. |
| Tibet Shock Cancel | `TIBET_SHOCK_CANCEL_TRIGGER_PCT` | Captured | Cancels defensively when TibetSwap moves sharply. |
| Arb Alert Threshold | `ARB_ALERT_THRESHOLD_BPS` | Captured | Gap threshold for arb warnings/sniper logic. |
| Min Price | `MIN_MID` | Captured | Optional hard lower price bound. |
| Max Price | `MAX_MID` | Captured | Optional hard upper price bound. |

#### Order Book

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Max Buy Offers | `MAX_ACTIVE_BUY` | Captured | Maximum active buy offers. |
| Max Sell Offers | `MAX_ACTIVE_SELL` | Captured | Maximum active sell offers. |
| Base Trade Size | `DEFAULT_TRADE_XCH` | Captured | Default XCH-sized trade amount. |
| Enable Tiers | `TIER_ENABLED` | Captured | Uses tiered order sizing/counts. |
| Reverse Buy Ladder | `BUY_LADDER_REVERSED` | Captured | Sizes buy ladder in reverse order when enabled. |
| Buy Inner/Mid/Outer/Extreme size | `BUY_*_SIZE_XCH` | Captured | XCH sizes for buy ladder tiers. |
| Sell Inner/Mid/Outer/Extreme size | `SELL_*_SIZE_XCH` and legacy `*_SIZE_XCH` | Captured | XCH-equivalent sizes for sell ladder tiers. |
| Coin Prep Headroom | `COIN_PREP_HEADROOM_PCT` | Captured | Extra prep above exact target. |
| Auto From Offer Limits | Tier count helper | Captured | Calculates tier counts from max offers. |
| Buy tier counts | `BUY_*_TIER_COUNT` | Captured | Buy-side coins to prepare for inner/mid/outer/extreme. |
| Sell tier counts | `SELL_*_TIER_COUNT` and legacy `*_TIER_COUNT` | Captured | Sell-side coins to prepare for inner/mid/outer/extreme. |
| Recommended spare counts | Tier spare helper | Captured | Fills suggested spare count values. |
| Buy spare counts | `BUY_*_TIER_SPARE_COUNT` | Captured | Buy-side spare coins per tier. |
| Sell spare counts | `SELL_*_TIER_SPARE_COUNT` and legacy `*_TIER_SPARE_COUNT` | Captured | Sell-side spare coins per tier. |
| Coin prep multiplier | `COIN_PREP_MULTIPLIER` | Backend | Hidden/pinned at 1.0. Spare counts now drive visible prep planning. |

#### Smart Pricing

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Dynamic Spreads | `DYNAMIC_SPREAD_ENABLED` | Captured | Enables dynamic spread calculations. |
| Base Spread | `BASE_SPREAD_BPS` | Captured | Starting spread for dynamic engine. |
| Volatility Window | `VOLATILITY_WINDOW_HOURS` | Captured | Lookback window for volatility measurement. |
| Inner Edge | `MIN_EDGE_BPS` | Captured | Minimum edge protection near inner quote. |
| Min Spread | `MIN_SPREAD_BPS` | Captured | Lower spread bound. |
| Max Spread | `MAX_SPREAD_BPS` | Captured | Upper spread bound. |
| Adverse Selection Guard | `MARKET_TOXICITY_ENABLED` | Captured | Enables market toxicity/adverse selection scoring. |
| Protection Level | `TOXICITY_PROTECTION_LEVEL` | Captured | Gentle, balanced, or defensive preset. |
| Max Widening | `TOXICITY_MAX_SPREAD_MULTIPLIER` | Captured | Max spread multiplier during toxicity. |
| Pause Seconds | `TOXICITY_THROTTLE_SECS` | Captured | How long to pause a side after high toxicity. |
| Inventory Management | `INVENTORY_ENABLED` | Captured | Enables position-based spread skew. |
| Skew Intensity | `SKEW_INTENSITY` | Captured | Strength of inventory skew. |
| Max Position | `MAX_POSITION_XCH` | Captured | Position limit in XCH terms. |
| Fallback Spread | `SPREAD_BPS` | Captured | Static spread used when dynamic spreads are off. |
| Loop Interval | `LOOP_SECONDS` | Captured | Seconds between normal bot cycles. |

#### Auto-Requote

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Enable Auto-Requote | `AUTO_REQUOTE` | Captured | Cancels/recreates offers when price drifts. |
| Requote Threshold | `REQUOTE_BPS` | Captured | Price move required to requote. |
| Requote Cooldown | `REQUOTE_COOLDOWN_SECS` | Captured | Minimum time between requotes. |
| Requote Batch Size | `REQUOTE_BATCH_SIZE` | Captured | Offers refreshed per requote cycle. |

#### Market Intelligence

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Competitor Awareness | `COMPETITOR_AWARE_ENABLED` | Captured | Reads Dexie market depth and nudges spread. |
| DBX Rewards Max Spread | `DBX_MAX_SPREAD_BPS` | Captured | Max spread for Dexie rewards eligibility guidance. |

#### Bot Operations

| Control | Config key | Coverage | What it does |
|---|---|---:|---|
| Sniper | `SNIPER_ENABLED` | Captured | Enables small discovery/probe offers. |
| Sniper Size | `SNIPER_SIZE_XCH` | Captured | XCH size of each sniper probe. |
| Sniper Prep Count | `SNIPER_PREP_COUNT` | Captured | Dedicated sniper coins to prepare. |
| Re-arm Price Move | `SNIPER_REARM_PRICE_MOVE_BPS` | Captured | Price move required before sniper re-arms. |
| Re-arm Arb Gap Move | `SNIPER_REARM_GAP_MOVE_BPS` | Captured | Arb gap move required before sniper re-arms. |
| Transaction Fees | `TRANSACTION_FEE_XCH` enabled/nonzero | Captured | Adds fee to on-chain wallet transactions. Offer creation remains fee-free. |
| Fee Amount | `TRANSACTION_FEE_XCH` | Captured | Fee per on-chain transaction. |
| Fee Coin Size | `FEE_COIN_SIZE_XCH` | Captured | Prepared fee coin size. |
| Fee Coin Count | `FEE_PREP_COUNT` | Captured | Number of fee coins to prepare. |
| Transaction Fee Mode | `TRANSACTION_FEE_MODE` | Backend | Hidden/manual mode. |
| Transaction Fee Target Seconds | `TRANSACTION_FEE_TARGET_SECS` | Backend | Hidden target confirmation time. |
| Splash P2P | `SPLASH_ENABLED` | Captured | Broadcasts offers via Dexie Splash P2P. |
| Coin Prep | `ENABLE_COIN_PREP` | Captured | Splits wallet into trading coins before start. |
| Runtime Coin Health | `ENABLE_RUNTIME_COIN_HEALTH` | Captured | Monitors and top-ups coins while running. |
| Auto-Apply Sage Change Address | `SAGE_SET_CHANGE_ADDRESS` | Captured | Sets Sage change address on startup when enabled. |
| Export .env | Config export | Captured | Downloads/exports current settings. |
| Save and Continue | Bulk settings save | Captured | Validates, persists, and may open coin prep. |

### Offers Tab

| Control | Coverage | What it does |
|---|---:|---|
| Active tab | Captured | Shows current open offers. |
| History tab | Captured | Shows recent fills/taken offers. |
| Export Fills | Captured | Exports fill history CSV. |
| Filter All | Captured | Shows both buy and sell sections. |
| Filter Buy | Captured | Shows only buy offers. |
| Filter Sell | Captured | Shows only sell offers. |
| Buy sort newest/oldest | Captured | Toggles buy offer sorting. |
| Sell sort newest/oldest | Captured | Toggles sell offer sorting. |
| Buy Collapse All | Captured | Collapses/expands visible buy offers. |
| Sell Collapse All | Captured | Collapses/expands visible sell offers. |
| Individual offer collapse | Captured | Opens/closes offer detail row. |
| Copy Coin ID | Captured | Copies coin ID where available. |
| Copy Trade/Offer ID | Captured | Copies full offer ID. |
| View on Dexie | Captured | Opens the offer on Dexie. |
| Load More | Captured | Shows more paginated offers. |
| History Dexie link | Captured | Opens filled/taken offer on Dexie. |

### P&L Tab

| Control | Coverage | What it does |
|---|---:|---|
| Reset Position | Captured | Clears fill history and resets position baseline. |
| Reset All Stats | Captured | Wipes P&L, fills, price history, inventory snapshots, baseline, and runtime stats. |

P&L metrics to explain:

- Realized P&L, unrealized P&L, total P&L.
- Fees spent, total volume, average fill prices.
- Round trips and win rate.
- Position drift chart and current inventory position.
- Current spreads and sniper stats.

### Market Intel Tab

| Control | Coverage | What it does |
|---|---:|---|
| Price range 20m | Captured | Shows recent price history. |
| Price range 1h | Captured | Shows 1-hour price history. |
| Price range 6h | Captured | Shows 6-hour price history. |
| Price range 24h | Captured | Shows 24-hour price history. |
| Splash panel collapse | Captured | Collapses/expands Splash P2P section. |
| Incoming Offer Listener toggle | Captured | Turns inbound Splash offer listener on/off. |
| Splash setup/install button | Captured | Shows installed/setup state. |

Market Intel metrics to explain:

- Mid price chart.
- Market diagnostics for Dexie, TibetSwap, Spacescan.
- Spacescan token context: holders, market cap, supply, rank where available.
- Dexie orderbook depth and arb gap.
- TibetSwap pool ratio and estimated slippage.
- Dexie liquidity rewards eligibility.
- Splash local submit, failures, skipped, API status, incoming listener, received/relevant counts, peers, queue.

### Logs Tab

| Control | Coverage | What it does |
|---|---:|---|
| Run Doctor | Captured | Runs a local diagnostics check. |
| API Stats | Captured | Shows local API/runtime stats. |
| Debug Bundle | Captured | Exports a troubleshooting bundle. |
| Clear | Captured | Clears visible log output. |
| Load more logs | Conditional | Appears when enough logs exist. |

### Data Reset Tab

| Control | Coverage | What it does |
|---|---:|---|
| Reset P&L | Captured | Clears P&L counters/history without touching coins/settings. |
| Clear Offer History | Captured | Deletes closed/cancelled/expired offer rows, leaving live offers. |
| Full Reset | Captured | Clears P&L, offer history, and runtime stat counters while preserving coins/settings/wallet state. |

### Help And About

| Control | Coverage | What it does |
|---|---:|---|
| Help modal | Captured/Partial | User education center. |
| Help tabs: Overview, Getting Started, Dashboard, Offers & Fills, Spreads & Pricing, Inventory & PnL, Coin Management, Market Intel, Sniper, Close the Gap, Sage Wallet, Config Guide, Troubleshooting | Conditional | Need individual screenshots/video sections. |
| About close | Captured | Closes about modal. |
| About links: Report a bug, Send feedback, Latest release | Captured | Opens external support/release links. |

### Conditional Workflow Modals

| Modal | Coverage | What it does |
|---|---:|---|
| Coin Prep confirmation | Conditional | Shows coin prep plan, lets user go back, skip, or prepare coins. |
| Coin Prep progress | Conditional | Shows prep logs/progress and cancel option. |
| Coin Prep history choice | Conditional | Lets user reset P&L, clear offer history, and reset runtime counters before prep. |
| Deposit Advisor | Conditional | Allocates newly detected deposits to trading pool, reserve, or split. |
| Cancel All confirmation | Conditional | Confirms cancelling every active offer. |
| Cancel All progress | Conditional | Shows cancel batch progress and failures. |
| Close the Gap confirmation | Conditional | Explains and starts manual probe ladder. |
| Shutdown confirmation | Conditional | Stops app, optionally cancels offers first. |
| Shutdown progress | Conditional | Shows shutdown/cancel progress. |
| Wallet picker | Conditional | Switches active Sage fingerprint. |
| Skip Coin Prep warning | Conditional | Warns about starting without prepared coins. |
| Start Without Prep warning | Conditional | Allows force-start after warning. |
| Update modal | Conditional | Shows release notes, later/view release/upgrade actions. |
| Crash recovery panel | Conditional | Shows last crash report, copy/open data folder actions. |
| Styled confirm/prompt | Conditional | Generic confirmation/name entry used by reset and preset flows. |

## Backend Behavior Master List

These are the backend systems that tutorial videos should explain even when they are not direct UI settings.

| Backend area | Main modules | What it does |
|---|---|---|
| Desktop/app shell | `desktop_app.py`, `api_server.py`, `app_bridge.py` | Starts Flask, desktop window, tray/app lifecycle, local API bridge. |
| Config persistence | `config.py`, `.env`, API settings routes | Loads typed settings, validates updates, persists allowed keys only. |
| Wallet integration | `wallet.py`, `wallet_sage.py` | Talks to Sage RPC, manages fingerprints, balances, coins, offers, change address, cert path. |
| CAT discovery | `cat_resolver.py`, API startup discovery | Resolves CAT metadata, wallet IDs, Tibet pair IDs, token names, ticker IDs. |
| Price engine | `price_engine.py`, `amm_monitor.py` | Pulls TibetSwap, Dexie, Spacescan/market context, mid price, arb gap, volatility, drift. |
| Trading loop | `bot_loop.py` | Runs each cycle: refresh state, price, risk checks, create/cancel/requote/top-up/fill tracking. |
| Dynamic spread engine | `risk_manager.py`, `bot_loop.py` | Adjusts spreads using volatility, fill rate, pool depth, arb gap, inventory, competitors, and toxicity. |
| Toxicity/adverse selection guard | `risk_manager.py`, `bot_loop.py` | Scores one-sided/large public offers, fills, and order-flow signals; widens, pauses, or cancels if needed. |
| Inventory management | `risk_manager.py`, `bot_loop.py` | Tracks CAT/XCH position and skews buy/sell spreads to return toward neutral. |
| Offer lifecycle | `offer_manager.py`, `fill_tracker.py`, `database.py` | Creates offers, tracks Dexie/Splash posting, detects fills, handles cancels, stores history. |
| Dexie posting | `offer_manager.py`, API helpers | Publishes offers to Dexie and records posting state/link. |
| Splash P2P | `splash_*`, `bot_loop.py`, API Splash routes | Starts/checks Splash, broadcasts offers, receives inbound P2P offers, tracks relevant/received counts. |
| Coin classification | `coin_manager.py`, `coin_classifier.py` | Sorts coins into tier, spare, sniper, fee, dust, reserve, and top-up groups. |
| Coin prep worker | `coin_prep_worker.py` | Splits/composes coins for offer tiers, sniper probes, and fees. |
| Runtime coin health | `bot_health.py`, `bot_loop.py` | Watches coin shortages and top-up budgets, repairs depleted tiers while running. |
| Deposit advisor | `bot_health.py`, API config update | Detects new large coins and asks whether to allocate them to trading pool or reserve. |
| Sniper probes | `bot_loop.py`, `boost_manager.py` | Places tiny edge-discovery offers and re-arms only after meaningful market movement. |
| Close the Gap | `boost_manager.py`, Live Controls | Manual strategy to tighten probes toward the safest arb floor. |
| Requote system | `bot_loop.py`, `offer_manager.py` | Cancels/recreates stale offers by drift, cooldown, and batch size. |
| Pre-confirmation/mempool guards | `bot_loop.py`, wallet/offer lifecycle | Reacts quickly when watched spends/offers indicate fills or pool movement. |
| Circuit breakers | `risk_manager.py`, `bot_loop.py` | Protects against price shocks, stale wallets, bad mappings, excessive drift, and unsafe state. |
| P&L accounting | `database.py`, `fill_tracker.py`, API P&L endpoints | Tracks fills, realized/unrealized P&L, round trips, volume, fees, inventory drift. |
| Logs and debug bundle | `super_log.py`, API diagnostics routes | Streams logs, creates debug bundles, API stats, doctor checks. |
| Data reset | API reset routes, `database.py` | Clears selected tracking data without touching wallet coins/settings unless explicitly intended. |
| App update | update API/build scripts | Checks release, downloads upgrade, restarts into newer build. |
| Cross-platform packaging | `build.py`, requirements files, release workflows | Builds Windows, Linux, and macOS app distributions. |

## Known Tutorial Gaps To Capture Later

For a complete video/screenshot bank, capture these separately:

1. Full startup onboarding from a clean data directory.
2. Wallet picker in startup and in Settings/Dashboard.
3. All Help modal tabs.
4. Coin prep confirmation, progress, complete, failed, and history reset choice.
5. Deposit Advisor flow with all-pool, all-reserve, split slider, apply, decide later.
6. Cancel All confirmation and progress.
7. Close the Gap confirmation/details.
8. Shutdown confirmation, with and without cancel-offers option.
9. Update modal and upgrade progress.
10. Logs Run Doctor, API Stats, Debug Bundle results.
11. Settings in single-sided Buy Only and Sell Only mode, because some controls hide or change.
12. Live Controls while the bot is running, because buttons become enabled and applied states change.
13. Data reset confirmation dialogs.
14. Crash recovery panel after a simulated crash log.

