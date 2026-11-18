# Changelog

All notable changes to CATalyst are recorded here.

This changelog was added during public-readiness work. Earlier release notes may
be reconstructed from GitHub Releases and tag history where available.

## Unreleased

Thin-market mode: build and keep a ladder on any token, however thin or new.

- Added `THIN_MARKET_MODE` (on by default). The ladder no longer needs outside
  depth or a second price source: it quotes from whatever Dexie book exists,
  holds the last good bid and ask when the book becomes unusable, and never
  withdraws because a refresh failed or ran late.
- Each side is anchored to its own outside edge: the inner sell sits
  `THIN_MARKET_EDGE_STEP_BPS` below the best outside ask, the inner buy the
  same distance above the best outside bid, and each side reaches
  `THIN_MARKET_LADDER_DEPTH_BPS` (10%) away from there.
- Added `MANUAL_REFERENCE_PRICE`, a starting price for a token with no usable
  book and no price history.
- Profit-floor, snapshot-age, book-improvement, toxicity-throttle,
  dynamic-band and 90-second rediscovery checks warn instead of blocking in
  thin-market mode. Hard min/max price, position and reserve limits still apply.
- Smart Settings no longer refuses a wide or shallow market, sizes for the
  offers-per-side the operator entered, and no longer comes out one offer short.
- Fixed startup refusing to run with `PUBLICATION_CLAIM_RECOVERY_REQUIRED`
  after Splash publications failed in an earlier safety generation.
- Fixed a resumed ladder being treated as an emergency price move on restart.
- Fixed offers created before a restart being impossible to replace.
- Dashboard, guidance and Market Intelligence now describe what thin-market
  mode is actually doing.

## v1.3.5 - 2026-08-25

- Fixed the Windows clean-install startup path so an unconfigured Sage wallet
  opens CATalyst's first-run wallet setup UI instead of a localhost safety JSON
  response intended for read-only duplicate-instance diagnostics.
- Added a fail-closed setup bootstrap that permits only Sage connection and
  identity selection until the exact signing identity is persisted and normal
  mutation ownership is established; all trading actions remain blocked.
- Added a release-gating smoke test that installs and launches the packaged
  Windows desktop application with an empty user profile and verifies the real
  first-run UI rather than only testing a preconfigured Flask process.

## v1.3.4 - 2026-08-25

- Corrected the Linux desktop release smoke assertion to accept CATalyst's safe
  loopback-port fallback while continuing to reject stale `file://` launchers or
  non-loopback desktop URLs.

## v1.3.3 - 2026-08-25

- Ensured sequential Linux AppImage and Debian package smoke tests terminate the
  complete desktop process group, preventing an extracted AppImage child from
  retaining the loopback port used by the following package test.

## v1.3.2 - 2026-08-25

- Isolated the Linux desktop package smoke test with an explicit synthetic Sage
  wallet identity and mainnet binding so CATalyst can prove the real GUI under
  Xvfb without weakening fail-closed startup safety.

## v1.3.1 - 2026-08-25

- Corrected the cross-platform release workflow to use CATalyst's isolated,
  identity-aware packaged API smoke harness instead of starting an unconfigured
  runtime that safety correctly redirected to read-only diagnostics.

## v1.3.0 - 2026-08-25

- Added a durable stability kernel for wallet mutation ownership, offer
  creation/cancellation journals, publication outbox recovery, authoritative
  reconciliation, and fail-closed restart handling.
- Hardened Sage wallet identity, signing, cancellation, balance caching, and
  diagnostic redaction, including recovery coverage for ambiguous or rejected
  transaction outcomes.
- Improved coin preparation with confirmed-view checks, bounded retry and
  consolidation recovery, one-sided preparation, live top-up journals, and
  dedicated fee-coin reliability.
- Corrected Dashboard, Logs, Offers, P&L, Market Intel, Settings, Help, About,
  reload, and existing-ladder resume behavior; a running session now stays
  behind a neutral status probe instead of flashing first-run Risk Disclosure.
- Added explicit TibetSwap-outage degraded mode: CATalyst reports the external
  outage, falls back to Dexie-only pricing, marks AMM-only metrics unavailable,
  and does not present stale TibetSwap data as live.
- Expanded automated and packaged acceptance coverage around mainnet Sage TEST
  7, offer/fill lifecycle behavior, MZ market state, safety diagnostics, and
  Windows release builds.

## v1.2.5

- Fixed offer replacement after sweep fills so confirmed fills clear stale DB-only
  retry backoff before rebuilding the ladder.
- Reduced noisy proactive coin top-up attempts when a low-spare tier has no
  usable split source.
- Stabilized startup inner spread display while market data and dynamic spread
  inputs are still calibrating.
- Fixed the CAT deposit baseline timestamp path flagged by Code Quality.

## v1.2.4

- Current public-readiness baseline.
- Source version metadata aligned with the latest tagged release.

## v1.2.1

- Desktop application baseline with Flask, PyWebView, SQLite WAL, and Sage wallet integration.
