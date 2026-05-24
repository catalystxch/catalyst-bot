# CATalyst Video Library Design

Date: 2026-05-24  
Status: Approved structure, ready for production planning  
Location: local Windows PC / CATalyst workspace

## Purpose

Create a complete tutorial and marketing video library for CATalyst. The videos should help people seeing the app for the first time understand what it does, how to get started safely, how the bot makes decisions, and where to go for deeper settings and troubleshooting details.

The material must be useful for:

- Website onboarding.
- Social media clips.
- New user setup.
- CAT/project-owner trust building.
- Power-user reference and support.

## Audience Priority

The agreed audience order is:

1. New non-technical users who want to download the app, connect Sage, run Smart Settings, prep coins, and deploy offers safely.
2. CAT/project owners and market makers who understand liquidity but need confidence in how CATalyst behaves.
3. Power users/testers who want every setting, backend behavior, and troubleshooting path explained.

## Recommended Production Strategy

Use the agreed **Funnel Library** approach:

1. Start with simple beginner videos.
2. Add trust and strategy explainers.
3. Add exhaustive power-user reference videos.
4. Cut short social clips from the longer videos.

This avoids overwhelming new users while still building the deeper reference library needed for docs, support, and advanced users.

## Playlist 1: Start Here

These are the first videos a new user should see.

### 1. What CATalyst Does

Goal: explain CATalyst in plain English.

Core points:

- CATalyst is an automated CAT/XCH market-making app.
- It works with Sage wallet and local signing.
- It creates buy and sell offers on Dexie.
- It uses TibetSwap, Dexie, Spacescan, and Splash for market context.
- It has safety systems: Smart Settings, coin prep, toxicity guard, price bands, reserves, and stop/cancel controls.

Target length: 2-3 minutes.

### 2. Download, Install, First Launch

Goal: get a new user from website download to a connected app.

Core points:

- Download from the official website.
- Install/open the app.
- Start or connect Sage.
- Pick wallet/fingerprint.
- Confirm or configure Sage certificate path.
- Understand the Splash and Spacescan prompts.
- Reach the dashboard safely.

Target length: 5-7 minutes.

### 3. Smart Settings To First Offers

Goal: get from a funded wallet to live offers.

Core points:

- Pick a CAT/XCH pair.
- Run Smart Settings.
- Review reserves, top-up pool, trade sizes, offer counts, spread, and safety settings.
- Save settings.
- Run coin prep.
- Start the bot.
- Verify offers appear in Dashboard/Offers/Dexie.

Target length: 8-12 minutes.

### 4. Monitoring, Stopping, And Safety

Goal: teach a beginner how to watch the bot and stop cleanly.

Core points:

- Dashboard health.
- Toxicity score and adverse selection guard.
- Market health and on-chain risk.
- Offers and fill history.
- Stop vs Cancel All vs Shutdown.
- Logs and Debug Bundle for support.

Target length: 5-8 minutes.

## Playlist 2: Trust And Strategy

These explain why the bot behaves the way it does.

### 5. How Smart Settings Thinks

Goal: explain Smart Settings as a risk-aware sizing and setup engine.

Core points:

- Reads wallet balance and selected pair.
- Allocates reserves and top-up pools.
- Sets offer counts, tier sizes, spare coins, and trade size.
- Uses liquidity and volatility context.
- Avoids using the whole wallet blindly.
- Recomputes from current wallet state each time it runs.

### 6. Risk Controls And Toxicity Guard

Goal: explain why CATalyst widens, pauses, or protects itself.

Core points:

- Adverse selection and toxicity score.
- One-sided sweeps and large public offers.
- Buy/sell side scoring.
- Spread widening.
- Side-specific pauses.
- Tibet shock cancel.
- Price bands and step-change guards.
- Circuit breakers.

### 7. Market Making Strategy

Goal: explain the trading behavior in market-maker terms.

Core points:

- Buy/sell ladders.
- Inner/mid/outer/extreme tiers.
- Inventory skew.
- Dynamic spreads.
- Requoting and cooldowns.
- Competitor awareness.
- DBX reward spread constraints where relevant.

### 8. Coin Prep And Runtime Coin Health

Goal: explain why coin prep exists and why it matters on Chia.

Core points:

- Chia UTXO model.
- Each offer needs suitable coins.
- Tier coins, spare coins, sniper coins, fee coins, top-up pool, dust.
- Coin prep before start.
- Runtime top-ups after fills.
- Deposit advisor.
- What happens if coin prep is skipped.

### 9. Dexie, TibetSwap, Spacescan, Splash

Goal: explain the external data/services and what each contributes.

Core points:

- Dexie orderbook and offer publishing.
- TibetSwap pool price, pool depth, and arb context.
- Spacescan token context and API key status.
- Splash P2P broadcast/receive.
- Local wallet signing remains local; no seed/private keys.

## Playlist 3: Power User Reference

These are detailed reference videos for users who want full control.

### 10. Full GUI Tour

Goal: orient users around every tab.

Tabs:

- Dashboard.
- Offers.
- P&L.
- Market Intel.
- Settings.
- Logs.
- Data Reset.
- Help/About.

### 11. Every Setting Explained

Goal: turn the master settings inventory into a chaptered settings reference.

Sections:

- Settings Live.
- Wallet Session.
- Configuration Presets.
- Trading Pair.
- Liquidity Mode.
- Reserves.
- Safety and Limits.
- Order Book.
- Smart Pricing.
- Auto-Requote.
- Market Intelligence.
- Bot Operations.
- Save/export/preset behavior.

This should be split into chapters or multiple videos, not one unwatchable monolith.

### 12. One Video Per Tab

Goal: create focused tab walkthroughs.

Videos:

- Dashboard deep dive.
- Offers deep dive.
- P&L deep dive.
- Market Intel deep dive.
- Settings Live deep dive.
- Settings Setup deep dive.
- Logs deep dive.
- Data Reset deep dive.
- Help/About/reference resources.

### 13. Troubleshooting And Debug Bundles

Goal: help users and testers report issues well.

Core points:

- Sage connection problems.
- Certificate path issues.
- Settings not saving.
- Linux/Ubuntu differences.
- Spacescan key accepted/rejected signals.
- Splash status and P2P problems.
- Logs tab.
- Run Doctor.
- API Stats.
- Debug Bundle.
- GitHub bug report/feedback flow.

## Short Social Clips

Short clips should be cut from the longer videos.

Initial clip set:

- 30s: Smart Settings in action.
- 30s: From coin prep to first offers.
- 30s: Toxicity Guard widening spreads.
- 30s: How CATalyst keeps reserves untouched.
- 45s: Market Intel explained.
- 45s: Dexie/TibetSwap/Spacescan/Splash ecosystem map.
- 45s: Debug Bundle for support.
- 60s: CAT/project-owner pitch.

## Production Workflow

The agreed workflow is local-first:

1. Codex creates local scripts, storyboards, shot lists, captions, website blurbs, social copy, and production prompts.
2. Codex captures or reuses local screenshots and UI evidence.
3. Codex can assemble simple draft videos locally using available tools such as FFmpeg.
4. Claude/Opus or dedicated video tooling can be used for narration polish, motion graphics, and final social-ready editing where useful.

## Local Capability Notes

Confirmed locally:

- FFmpeg is available.
- PIL/Pillow is available.
- Existing screenshot bank is available at `output/settings-audit-screenshots-full/`.
- Master settings inventory is available at `docs/tutorial-master-settings-inventory.md`.

Not currently confirmed locally:

- High-quality local voice synthesis.
- OBS command-line automation.
- Full motion graphics editing stack.

Therefore Codex can produce a strong local production pack and basic draft videos, but polished final voiceover/motion work may be better handed to Claude plus a video editor or AI video tool after the scripts and storyboards are locked.

## Overnight Work Plan

If the user wants this to run unattended overnight, the practical target should be:

1. Create a production folder structure.
2. Generate one script file per planned video.
3. Generate one storyboard/shot-list file per planned video.
4. Generate website embed copy and social post copy.
5. Generate Claude/Opus production prompts for each video.
6. Generate a reusable caption/title style guide.
7. Optionally assemble simple screenshot-based draft videos for the first beginner videos if time and local assets are sufficient.

Completion criteria:

- Every planned video has a script, storyboard, asset list, and production prompt.
- Beginner Playlist 1 is ready for immediate recording/editing.
- Trust/Strategy Playlist 2 has complete draft scripts.
- Power User Playlist 3 has structured reference scripts or chapter outlines based on the master settings inventory.
- A final local README explains what was produced and what still needs human review.

## Constraints And Risks

- The PC must stay awake.
- Codex and the local workspace must remain open.
- The local browser/server may time out, but production can continue via files.
- Some flows need fresh screenshots later because they are conditional or destructive.
- The first final-quality video should still receive human review before mass-producing all final videos, so tone and pacing do not drift.

## Approved Direction

The user approved:

- All three audiences, priority 1, then 2, then 3.
- The Funnel Library approach.
- The proposed 13-video library structure.
- The local-first production workflow, with optional handoff to Claude/video tooling for final polish.

