# Changelog

All notable changes to CATalyst are recorded here.

This changelog was added during public-readiness work. Earlier release notes may
be reconstructed from GitHub Releases and tag history where available.

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
