# CATalyst v1.4.0 Post-TibetSwap Offer-Book Design

**Date:** 10 September 2026; amended 12 September 2026

**Status:** Approved, including Market Bootstrap amendment

**Implementation branch:** `codex/post-tibetswap-v1-4`

**Source baseline:** `4f24f13` (`Avoid duplicate Sage offer-history scans (#212)`)

## Context

TibetSwap has announced that its Chia AMM service will not return. CATalyst 1.3
still treats TibetSwap pool state as part of pricing, slippage, arbitrage,
toxicity, token discovery, Smart Settings, dashboard health, help text, and
release messaging. When TibetSwap disappeared, the live 1.3.21 bot continued to
maintain 36 buy and 36 sell offers at a remembered midpoint even though the
independent Dexie book contained no trustworthy two-sided competitor market.
The dashboard reported that market conditions were healthy, zero competitors,
zero pool depth, and an active sniper probe. That is unsafe and misleading.

CATalyst 1.4.0 becomes an offer-book liquidity bot. Sage is the wallet and
transaction authority; Dexie and Splash distribute and observe offers;
Coinset.org and Spacescan provide optional corroborating chain and ecosystem
evidence. No AMM, swap, DCA, or synthetic replacement for TibetSwap is added.

Because most CAT liquidity previously depended on TibetSwap, an existing
independent two-sided book cannot be a universal prerequisite. CATalyst therefore
supports both following an established offer book and deliberately bootstrapping
the first bounded market for any exact CAT asset ID. Bootstrap authorization is
explicit, campaign-scoped, non-custodial, and incapable of reaching funds outside
its fixed budgets.

The redesign preserves the stability-kernel invariants already on `main`, the
approved direct-batch Coin Prep design, existing settings and accounting history,
and the user's established mainnet TEST 7 acceptance workflow.

## Goals

- Price and manage offers only when CATalyst has a trustworthy, independently
  evidenced offer book.
- Let a user create a bounded first market for any exact CAT asset ID, including
  an unlisted or completely illiquid CAT, without presenting the user-supplied
  launch anchor as independently discovered fair value.
- Coordinate independent makers through interactively Sage-signed campaign
  manifests, an optional static public directory, and privacy-bounded
  participation proofs.
- Exclude CATalyst's own offers before deriving prices, depth, competition, or
  manipulation signals.
- Degrade progressively and visibly when market evidence becomes stale,
  one-sided, shallow, conflicting, or manipulable.
- Keep every offer creation, publication, discovery, cancellation, fill, and
  replacement crash-recoverable and idempotent.
- Replace TibetSwap/AMM/sniper behavior and UI with provider health, trusted
  price, attributed depth, opportunity, publication, and market-confidence data.
- Migrate existing users without losing settings, balances, offer/fill history,
  P&L, or stability-kernel evidence.
- Verify the release through deterministic fault tests, packaged Windows tests,
  and a 24-hour two-PC mainnet acceptance run before publishing the website.

## Non-goals

- Replacing TibetSwap with another AMM, swap router, DCA service, or unverified
  central price feed.
- Activating CHIP-0052 partial offers without proven Sage create, cancel, state,
  lineage, fill, and public-discovery capabilities. An Experimental option is
  visible but disabled until every capability is available; standard offers
  remain the default.
- Treating Dexie, Splash, Coinset.org, or Spacescan as authoritative for wallet
  ownership, signing, offer creation, cancellation, or fill accounting.
- Allowing a manual price override in Market Follow mode. A user-supplied anchor
  is allowed only inside an explicitly authorized Bootstrap campaign and is
  labelled as maker-provided rather than market-derived.
- Making confidence/manipulation thresholds directly editable in 1.4.0.
- Deleting or rewriting historical TibetSwap or sniper records.

## Safety invariants

The stability-kernel invariants remain in force. The following market-specific
invariants are additive:

1. **Sage is authoritative for effects.** Only fresh Sage state or exact,
   corroborated chain evidence can prove a create, cancel, fill, expiry, input
   spend, or owned output. Distribution providers never authorize wallet state.
2. **No independent market means no unbounded or implicit exposure.** Market
   Follow never creates or requotes without usable attributable evidence. The
   only exception is an explicit Bootstrap campaign whose price corridor,
   asset-side budgets, fee budget, optional subsidy budget, expiry, stage, and
   stop limits have been accepted by the user and persisted before any effect.
3. **Own offers never price the bot.** Every exact offer/trade/coin identifier
   known to the durable registry is removed before book aggregation. Anonymous
   aggregate levels cannot independently prove competitor depth.
4. **Evidence is attributed and deduplicated.** Dexie and Splash observations of
   the same offer or coin are one market fact, not two confirmations.
5. **Unknown is unsafe.** Stale, missing, malformed, one-sided, shallow, rapidly
   churning, conflicting, or unattributed evidence lowers confidence and cannot
   be silently replaced by the last displayed value.
6. **Withdrawal precedes pause.** Degradation stops new create/requote work and
   progressively removes exposure. Recovery never blindly rebuilds the ladder.
7. **Replacement follows terminal proof.** CATalyst never creates a replacement
   while the original offer might still be live.
8. **Accounting waits for confirmation.** Observed and probable fills are visible
   but cannot change P&L, inventory, replacement, or coin availability.
9. **Financial calculations are exact.** Prices and amounts use `Decimal`; coin
   amounts use integer atomic units; serialized evidence preserves exact strings.
10. **UI state is not authority.** Every tab renders the same server-side market
    confidence, offer lifecycle, and safety snapshot. Reload and restart rebuild
    it from durable and authoritative sources.
11. **Campaign funds are isolated.** Bootstrap may reserve only its exact fixed
    XCH budget, CAT budget, fee budget, and separately opted-in subsidy budget.
    Wallet percentages may inform suggestions but can never enlarge a persisted
    campaign authorization.
12. **Bootstrap is not a price oracle.** Own offers, own fills, suspected linked
    activity, anonymous aggregate levels, and the campaign anchor cannot prove
    independent fair value or unlock additional exposure.

## Provider-capability architecture

### Provider interfaces

Create focused provider modules under `src/catalyst/providers/`. Each adapter
declares capabilities and returns typed observations rather than loosely shaped
dictionaries:

- `SageAuthorityProvider`: wallet identity, balances, coins, offers,
  transactions, signing, create, cancel, and terminal proof.
- `DexieOrderbookProvider`: exact offers, settled trades, token metadata, public
  offer publication, and discovery confirmation.
- `SplashOfferProvider`: local peer health, exact incoming offers, offer
  publication, and discovery confirmation.
- `CoinsetEvidenceProvider`: optional exact coin, spend, and block evidence.
- `SpacescanEvidenceProvider`: optional asset metadata, holder/activity data,
  exact coin/transaction evidence when the API exposes it.

The provider protocol exposes an immutable `ProviderCapabilities` value and a
`ProviderObservation` envelope containing provider ID, capability, observed time,
source time or height, freshness deadline, exact identity keys, payload digest,
quality result, and bounded/redacted raw evidence. Providers never decide trading
policy.

### Evidence engine

Add `market_evidence.py` as a pure policy module. It consumes normalized
observations plus the durable own-offer identity set and returns a
`MarketConfidenceSnapshot`. The snapshot includes:

- state: `GREEN`, `AMBER`, or `RED`
- trusted midpoint and bid/ask range, or no tradable price
- independent bid/ask depth and depth-to-configured-offer-size ratios
- source health, ages, agreement, and precise reason codes
- volatility, churn, persistence, and manipulation scores
- settled-trade confirmations and last trusted snapshot identity
- degraded start time, withdrawal stage, and recovery progress

The engine persists material snapshots and state transitions through
`database.py`. The last trusted price, its exact evidence, and `degraded_since`
survive restart. A remembered price is display-only unless current policy permits
the relevant grace-period action.

## Market lifecycle and Bootstrap campaigns

### Operating modes and stages

CATalyst exposes two explicit operating modes:

- **Market Follow:** competes inside a current attributable offer book. Data
  validity is separate from provider redundancy. One fresh exact Dexie book may
  authorize restricted staged exposure; a healthy independent Splash book raises
  confidence and can accelerate capacity, but an enabled-yet-empty Splash node
  does not make every Dexie market unusable.
- **Market Bootstrap:** creates the first bounded market from a maker-provided
  anchor when the book is absent, stale, one-sided, insufficiently deep, or wider
  than 1,000 basis points. CATalyst suggests this mode and explains why, but never
  switches into it or creates an offer without explicit confirmation.

The displayed market stage is `BOOTSTRAP`, `DISCOVERY`, `ESTABLISHED`, or
`UNSAFE`. It is distinct from provider health and from the Green/Amber/Red
confidence state so a user-supplied launch anchor is never mislabeled as a Green
independent price. Automatic transition from Bootstrap to Market Follow occurs
only after the evidence requirements below are durably satisfied; the user is
notified without interrupting a healthy ladder.

### Campaign authorization and price corridor

A Bootstrap campaign is bound to the verified network, wallet fingerprint,
wallet type, CAT asset ID, and XCH/CAT pair. Before any Coin Prep or offer effect,
the user supplies:

- a fixed XCH trading budget and fixed CAT trading budget;
- an explicit anchor entered as XCH per CAT or derived from CAT supply plus an
  implied XCH market valuation;
- hard minimum and maximum prices, with a default suggestion of 50% below and
  100% above the anchor;
- a separate fixed fee budget;
- an optional separate launch-subsidy budget, defaulting to zero;
- a seven-day expiry and a 5% campaign-value loss stop.

Campaign value is the XCH budget plus the CAT budget valued at the accepted
anchor. The loss stop includes confirmed realized loss and conservatively marked
adverse inventory movement. Hitting it cancels all campaign offers through the
authoritative lifecycle, preserves the evidence, and requires an explicit manual
restart with a fresh anchor and budget review.

Bootstrap can be two-sided or clearly labelled `BUY_ONLY`/`SELL_ONLY` when the
maker has only one asset. It never borrows, synthesizes, or crosses the market to
manufacture the missing side.

### Staged deployment and discovery

Only 10% of each funded trading-side budget is initially deployable. The initial
ladder contains three ordinary atomic offers per funded side inside the hard
price corridor. Additional capacity requires both attributable independent maker
depth and Sage-confirmed third-party settlement evidence:

- 25% capacity: at least two confirmed fills attributed to two distinct on-chain
  settlement identity clusters;
- 50% capacity: at least six confirmed fills attributed to three clusters, at
  least 30 minutes of stable evidence, and current independent depth;
- 100% capacity: at least twelve confirmed fills attributed to five clusters, at
  least two hours of stable evidence, and current independent depth.

An identity cluster is an evidence heuristic based on attributable non-maker
inputs, puzzle hashes, and settlement lineage; it is not a claim that CATalyst
can prove distinct real-world people. Suspected own or linked activity is excluded
from price movement, capacity, transition, and incentive proofs and raises a
visible manipulation flag.

Confirmed activity may move the anchor by at most 5% in any rolling hour and 20%
in any rolling 24 hours, always remaining inside the hard corridor. An adverse
fill starts a five-minute cooldown on the affected side while Sage reconciliation
and the independent book settle. Inventory imbalance first skews remaining quotes
toward rebalancing, then pauses the depleted side; CATalyst never aggressively
crosses the market to rebalance.

At 80% fee-budget consumption, new creation and requoting stop. The remaining 20%
is reserved for safe cancellation and withdrawal. CATalyst never tops up a
Bootstrap fee budget from unrelated wallet XCH.

### Campaign sharing and incentives

CATalyst exports and imports canonical campaign manifests containing the campaign
ID, network, exact CAT asset ID, maker-provided anchor, corridor, stage rules,
expiry, public signing key, and verification status. Wallet proof uses Sage's
interactive WalletConnect `chia_signMessageByAddress` command. Sage must show the
message and the user must approve it for each manifest or participation report;
CATalyst never routes offer, coin, Coin Prep, or bot mutations through
WalletConnect. The WalletConnect account, chain, and signing address must agree
with an immediate authoritative Sage RPC identity recheck before the request and
again before accepting the response.

The standalone Sage RPC does not currently expose this signing command. When a
free public Reown project ID is not configured, Sage rejects or times out the
request, the account changes, or signature verification fails, CATalyst keeps
core Bootstrap available but marks signing `UNAVAILABLE` or `INVALID`. It never
substitutes an application key or checksum, and it cannot submit that record to
the verified public directory. A joining maker accepts shared market parameters
but chooses independent local trading, fee, subsidy, reserve, and loss budgets.
Imported manifests cannot authorize wallet effects by themselves.

The website may publish a static directory of valid Sage-signed manifests.
Directory entry proves only that the advertised signing key signed the canonical
bytes; it is not an endorsement of the CAT, issuer, anchor, or expected return.
Unsigned manifests remain local/shareable data and are never presented as
verified directory entries. Unlisted CATs are allowed after strong exact-asset
confirmation and remain visibly `UNVERIFIED` as assets even when their manifest
signature is valid.

Participation reports contain only the public signing key, campaign ID, exact
offer/fill identifiers, and aggregated independent depth, uptime, and competitive
spread totals. They omit the Sage fingerprint, balances, unrelated transactions,
and local filesystem identity. Issuer rewards are external in v1.4.0 and should
score sustained independent depth, uptime, and spread quality rather than volume,
which is readily wash-traded. Existing Dexie incentive discovery and automatic
reward claims remain supported.

### Experimental partial-offer capability

Standard Chia Offers remain the only enabled live path by default. Settings show
an Experimental Partial Offers option but keep it disabled until the active wallet
and provider adapters prove exact create, cancel, state, lineage, fill, and public
discovery capabilities. A missing capability returns a stable explanatory reason
and performs no wallet mutation. There is no force-enable path. When the complete
capability contract becomes available, partial offers remain separately opt-in and
must pass the same campaign, budget, evidence, lifecycle, accounting, and recovery
rules as standard offers.

## Trusted pricing and manipulation resistance

### Primary market data

Dexie's exact live offer feed is the primary price book. Settled Dexie trades
validate movement but do not alone create a two-sided book. Splash contributes
exact attributable offers when peer health and offer parsing are valid.

Dexie v3 anonymous aggregate levels are corroborative only. They cannot satisfy
the independent-depth requirement because CATalyst cannot reliably remove its own
offers from those levels.

### Own-offer exclusion and deduplication

The evidence engine removes offers matching any durable Sage trade ID, offer
fingerprint, offer hash, publication ID, input coin ID, or active replacement
lineage member. Dexie and Splash rows are deduplicated by exact offer identity;
chain observations are deduplicated by coin/spend/transaction identity.

If an aggregate level overlaps CATalyst prices but cannot be attributed, it may
raise displayed depth but cannot improve confidence or authorize a mutation.

### Depth and persistence

Minimum independent depth scales with the configured offer size and risk preset.
Each side must have enough attributable depth to absorb at least the preset's
derived multiple of one configured offer without crossing the trusted range.
The exact derived threshold is shown in Settings but is not editable in 1.4.0.

A material book movement must persist for two to three refreshes. A matching
settled trade may confirm it sooner. The hard price-move cap still applies even
when a settled trade exists.

### Manipulation scoring

Rapid add/remove churn, thin top levels, one-wallet concentration, crossed or
implausible books, repeated short-lived undercuts, source disagreement, and
unconfirmed large movement raise a side-specific manipulation score. Thresholds
derive from Conservative, Balanced, or Aggressive risk presets and are visible in
Settings. Increasing risk widens spreads first, suppresses price-war response,
and can enter degraded mode; it never creates a better deal for the suspected
manipulator.

### Competition and opportunity orders

CATalyst may improve against trusted independent offers only when the resulting
order remains profitable after network fees, expected cancellation/requote cost,
and the configured minimum-profit floor. Repeated undercutting is rate-limited.

The legacy sniper is replaced by conservative book-opportunity orders. These are
small, bounded, separately labelled offers placed only against confirmed depth
inside the trusted range. They obey the same publication, discovery, profit,
manipulation, reserve, and cancellation rules as normal ladder offers.

## Confidence states and degraded operation

### Green

Fresh, attributable, sufficiently deep, two-sided evidence exists; provider
agreement and manipulation scores are within the current preset. CATalyst may
create, publish, and manage the configured ladder.

### Amber

Evidence is usable for display or restricted management but has a single-provider
dependency, mild disagreement, reduced depth, emerging churn, or a recent source
recovery. CATalyst widens or limits opportunity behavior as derived by the preset.
It does not increase exposure.

### Red and the ten-minute grace period

When the trusted two-sided book is lost, CATalyst records `degraded_since`, freezes
the last verified midpoint for evidence and display, stops all new create and
requote operations, and begins progressive withdrawal:

- immediately: cancel inner offers;
- after three continuous degraded minutes: cancel mid offers;
- at ten continuous degraded minutes: cancel outer, extreme, and opportunity
  offers, then enter a paused-safe state.

The last trusted price never authorizes a new offer during grace. Withdrawal uses
authoritative Sage cancellation and terminal proof. If manipulation is suspected,
the engine may skip grace stages and withdraw faster; degradation can therefore
never be gamed into creating unusually favorable offers.

### Recovery

Recovery requires three healthy refreshes spanning at least 60 seconds. CATalyst
revalidates current Sage offers against the recovered trusted range, retains
compliant owned offers, cancels only unsafe or unowned offers, and rebuilds missing
slots gradually. It does not mass-cancel and recreate a healthy existing ladder.

Desktop notifications fire only on confidence transitions, safety blocks, and
recovery completion. Routine refreshes remain quiet.

## Offer lifecycle and publication

Every offer uses a durable state machine:

`PLANNED -> PREPARED -> SAGE_CREATED -> PUBLICATION_QUEUED -> PUBLISHED ->`
`DISCOVERED -> ACTIVE -> CANCEL_SUBMITTED -> TERMINAL`

Failure and ambiguity states include `CREATE_UNKNOWN`, `PUBLICATION_DEGRADED`,
`DISCOVERY_EXPIRED`, `CANCEL_UNKNOWN`, and `TERMINAL_CONFLICT`. Valid transitions
are enforced by pure policy and database compare-and-set updates.

CATalyst publishes independently to Dexie and Splash. A successful HTTP response
is a publication acknowledgement, not discoverability proof. The exact offer must
be rediscovered by offer identity. Both providers confirmed is green publication
health; one confirmed is amber; neither confirmed is red for that offer.

The discoverability deadline is 90 seconds from confirmed Sage creation. If
neither provider rediscovers the exact offer by then, CATalyst:

1. marks the offer `DISCOVERY_EXPIRED`;
2. submits an authoritative Sage cancellation;
3. waits for terminal proof;
4. releases the exact reserved capacity only after proof;
5. permits a replacement only after provider health recovers and backoff expires.

CATalyst never stacks a replacement above an undiscovered original. Terminal
offers are removed from both provider queues. Restart recovery resumes the durable
state instead of repeating creation or publication blindly.

Bulk Cancel All uses the same durable lifecycle records as the Dashboard, Offers,
Logs, safety gate, and recovery screen. The general status API and dedicated
operation status expose the same confirmed/pending/failed counts. A native Sage
bulk submission is followed by per-offer terminal proof; no UI reports completion
from submission alone.

## Fill confidence and accounting

Fill evidence is classified as:

- `OBSERVED`: a provider reports disappearance, matching activity, or a likely
  take;
- `PROBABLE`: multiple deduplicated observations agree but authoritative proof is
  incomplete;
- `CONFIRMED`: Sage reports the fill, or exact Coinset.org plus Spacescan evidence
  agrees on offer inputs, asset/amount, spend identity, and block height while Sage
  is temporarily delayed.

Only `CONFIRMED` affects P&L, inventory, replacement, limits, or coin readiness.
If Sage later conflicts with external confirmation, CATalyst enters a durable
amber safety state, preserves both evidence sets, and stops related mutations.
Chain evidence wins over a conflicting Dexie status.

### v1.4 exact-external-authority capability exception

The 2026-09-11 implementation review established that the currently supported
Coinset and Spacescan response contracts do not both expose the complete spent
and created coin flow needed to distinguish a fill from a cancellation or other
spend. CATalyst therefore advertises exact external fill authority as
`unavailable` and keeps Coinset/Spacescan chain observations diagnostic. Generic
`CHAIN_EVIDENCE` never implies economic authority. For v1.4, only exact Sage
wallet reconciliation may produce `CONFIRMED`, affect accounting, or authorize a
replacement. The dual-provider path remains fail-closed until both independent
providers expose a verified exact-flow contract and the later-Sage-conflict latch
has end-to-end coverage.

## Smart Settings and risk presets

Smart Settings keeps Conservative, Balanced, and Aggressive presets, but derives
all values from offer-book evidence:

- base/min/max spreads from trusted depth, volatility, churn, and fees;
- ladder counts and tier sizes from balances, reserves, independent depth, and
  purpose-separated fee/replacement capacity;
- minimum profit from network fee, expected cancel/requote cost, and configured
  profit floor;
- opportunity size/rate limits and manipulation thresholds from the preset;
- progressive withdrawal and recovery thresholds from the preset without making
  the ten-minute maximum grace less safe.

In Market Follow, Smart Settings never uses pool reserves, AMM slippage, arbitrage
gap, or a manual price. In Market Bootstrap it consumes only the explicit campaign
anchor, corridor, fixed budgets, stage decision, and confirmed evidence described
above. Zero and nonzero wallet reserves remain supported outside the isolated
campaign budgets. Existing direct-batch Coin Prep requirements are preserved,
including dedicated fee coins, the 20% cancellation-fee reserve, and exact output
verification.

## Persistence, migration, and retention

Add idempotent migrations for provider observations, market-confidence snapshots,
source-health transitions, publication discoveries, and migration reports. All DB
access remains in `database.py`; no provider or policy module uses raw SQL.

On first 1.4.0 startup:

1. preserve wallet binding, pair, balances, reserves, Smart Settings, offers,
   fills, P&L, logs, registry/journal, and Coin Prep state;
2. mark TibetSwap configuration and live fields retired/unavailable;
3. translate compatible risk and ladder settings into offer-book equivalents;
4. retain legacy TibetSwap/AMM/sniper history with explicit `legacy` labels;
5. validate every nonterminal offer against Sage ownership and current evidence;
6. retain compliant offers and cancel only unsafe or unowned offers;
7. fail closed if ownership or effect state cannot be proven;
8. write a one-time human-readable migration report.

Detailed market evidence is retained for 30 days, after which bounded daily
summaries preserve confidence transitions, source health, manipulation scores,
and decision lifecycle counts. Stability-kernel evidence retention remains at
least as strict as before.

For one release, legacy TibetSwap API fields remain present with explicit
`retired=true`, `available=false`, and reason `TIBETSWAP_SHUTDOWN`. They perform no
network calls and cannot influence policy. They may be removed in a later major
compatibility cleanup.

## User interface

All tabs use one server-side market/safety snapshot and preserve HTML escaping:

- **Dashboard:** Market Confidence badge, trusted range, independent bid/ask
  depth, source health/ages, degraded timer/stage, publication health, active
  offers, wallet balances, safety status, operating mode, campaign stage, deployed
  fraction, budget use, and loss/fee stops. Remove AMM, pool, arb, and sniper cards.
- **Offers:** Sage lifecycle plus per-provider acknowledgement/discovery state,
  fill confidence, lineage, cancellation progress, and exact reason codes.
- **P&L:** confirmed accounting only; observed/probable activity is separate.
  Legacy sniper and TibetSwap history stays visible and labelled historical.
- **Market Intel:** attributed exact order book, own-offer exclusions, settled
  trades, depth ratios, churn, source agreement, confidence timeline, and provider
  health. Splash, Coinset.org, and Spacescan are represented by capability.
- **Settings:** offer-book presets, reserves, limits, fees, provider toggles,
  Coinset.org/Spacescan privacy notice, visible derived thresholds, a Bootstrap
  wizard, signed-manifest import/export, proof-report export, and a visible but
  capability-disabled Experimental Partial Offers control. Remove live
  TibetSwap/AMM/sniper controls.
- **Logs:** confidence transitions, source outages/recoveries, withdrawal stages,
  publication/discovery, confirmed effects, migration, and stable reason codes.
  Dashboard-to-Logs switching immediately backfills and continues chronologically.
- **Data Reset:** retain existing safety gating and include the new evidence tables;
  no reset can clear an unresolved wallet effect.
- **Help/About/setup:** describe CATalyst as an offer-book liquidity bot, explain
  provider roles and the TibetSwap shutdown, and remove claims of AMM operation.

Reload or restart rebuilds the same view from durable state. If a ladder exists,
CATalyst offers Continue or Start Over only after identity and ownership checks.

## External source behavior and privacy

Coinset.org and Spacescan corroboration are enabled by default. Setup and Settings
explain that public asset, coin, transaction, offer, and block identifiers are sent
to those services; no seed, private key, full local wallet history, or private
filesystem data is transmitted.

Polling adapts to exposure: approximately five seconds while relevant offers or
unresolved effects are live, 20–30 seconds while idle, and exponential backoff
with jitter during outages or rate limits. Provider failures are bounded and
deduplicated in logs.

CATalyst should discover emerging public projects and bot activity through Dexie,
Spacescan, Coinset.org, and Splash observations rather than hard-coding a specific
project such as PussySwap. New providers require an explicit capability adapter
and cannot gain wallet authority by being added.

## Pull-request integration

Incoming work is preserved only when verified against this design:

- **PR #213:** startup recovery, live top-up journaling, Sage snapshot, and
  publication-race fixes are based on current `main` and are expected to be
  integrated first after focused review and tests.
- **PR #208:** native bulk-cancel recovery and stale lock-count fixes are distinct
  from #213. Rebase/cherry-pick compatible commits and retain authoritative
  per-offer terminal proof.
- **PR #207:** do not merge unchanged. Its Splash duplicate cache can miss
  concurrent duplicates before the first request persists. Replace it with
  in-flight request coalescing and a focused concurrent regression test while
  preserving bounded warning suppression.

No PR is merged merely because CI is green. Each diff is checked for current-main
compatibility, design invariants, focused tests, and full regression/build impact.

## Testing strategy

Implementation follows red-green-refactor. Focused tests must fail for the intended
missing behavior before production code is changed.

Automated coverage includes:

- provider capability contracts, normalization, freshness, backoff, malformed
  responses, and privacy boundaries;
- own-offer exclusion and Dexie/Splash/chain deduplication;
- two-sided depth scaling, movement persistence, settled-trade confirmation,
  volatility caps, churn and manipulation scoring;
- Follow-versus-Bootstrap suggestion without automatic financial-mode changes;
- fixed campaign-budget isolation, 10/25/50/100 staged capacity, three offers per
  funded side, one-sided launch, price corridor, anchor movement caps, cooldown,
  inventory skew, seven-day expiry, 5% loss stop, and fee-budget withdrawal reserve;
- suspected self/linked settlement exclusion, identity-cluster limitations,
  canonical interactive Sage signatures, WalletConnect account/network binding,
  signing-unavailable behavior, manifest import safety, static-directory trust
  wording, privacy-bounded participation proofs, and quality-based reward totals;
- experimental partial-offer capability detection proving a disabled no-effect
  path when Sage or public distribution support is incomplete;
- green/amber/red transitions, durable degraded timers, staged withdrawal,
  restart during every stage, and three-refresh/60-second recovery;
- Sage create through 90-second discovery, one-provider operation, dual-provider
  success, deadline cancellation, no replacement before terminal proof, crash and
  retry at every boundary;
- observed/probable/confirmed fills, external exact proof, Sage conflict, and
  confirmed-only accounting;
- migration from representative 1.3.21 and legacy databases, preserving
  settings/history and preventing TibetSwap network access;
- Smart Settings with zero/nonzero reserves, full/partial balances, both/one-sided
  operation, fee/profit floors, and manipulated/shallow books;
- direct-batch Coin Prep, dedicated fee inventory, restart, cancellation, and
  changed-size preparation;
- bot start/stop, native bulk Cancel All, general/dedicated progress agreement,
  restart recovery, and safety-gate behavior;
- every UI tab, reload/session recovery, log backfill/order, responsive layout,
  escaping, and truthful unavailable/legacy states;
- Windows PyInstaller build, clean install, upgrade-in-place, shortcuts, version,
  manifest/hash, Defender scan, first launch, localhost routing, and debug bundle.

Static and security checks remain mandatory. New integration tests use fake
providers and clocks; live mainnet effects occur only in the authorized acceptance
run.

## Release acceptance

The release candidate is CATalyst `v1.4.0`. Before public release it must pass:

1. focused tests for every new behavior and bug fix;
2. full serial and supported parallel test suites;
3. lint, syntax, security, dependency, and secret scans;
4. a clean Windows packaged build and installer verification;
5. a clean-install test and a v1.3.21 upgrade/migration test preserving user data;
6. a complete local live cycle on the primary PC using mainnet Sage TEST 7,
   fingerprint `736588221`, wallet ID `2`, ticker `MZ_XCH`, and asset ID
   `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`;
7. Smart Settings, changed-size direct Coin Prep, start, creation, publication,
   discovery, fills, stop, native Cancel All, restart, migration, source outage,
   manipulation, degraded withdrawal, recovery, Market Follow, new/illiquid-CAT
   Bootstrap, WalletConnect-signed manifest import/export, participation proof
   export, signing-unavailable behavior, disabled
   partial-offer capability behavior, and every UI tab;
8. 24 continuous hours on both PCs with the started bot, no unresolved effects,
   no incorrect accounting, no identity drift, no stale/false market data, no
   unbounded errors, and reconciled Sage/Dexie/Splash/Coinset.org/Spacescan state.

The website, GitHub release, installer, checksums, and upgrade metadata are
published only after both-PC acceptance succeeds. Website/release copy describes
an offer-book liquidity bot and explains the TibetSwap shutdown. Because the free
SignPath application was declined, the unsigned Windows beta path remains explicit:
publish exact SHA-256 hashes and truthful SmartScreen/Defender guidance without
asking users to disable security controls.

## Completion boundary

The work is complete only when the compatible PR changes and this design are on
GitHub `main`, every automated and packaged gate passes, both PCs complete the
24-hour live acceptance, and the verified v1.4.0 installer and updated website are
publicly downloadable. Partial implementation, a green unit subset, a local build,
or one healthy PC is not release completion.
