# CATalyst Bootstrap directory contract

This directory format is a no-cost discovery mechanism for public CATalyst
Market Bootstrap manifests. A directory entry proves only that the advertised
Sage public key signed the exact canonical manifest bytes. Inclusion is not an endorsement of the CAT, issuer, anchor price, expected return, or safety of a
market.

Every joining wallet chooses its own trading budget, fee budget, subsidy budget,
reserves, and loss limit. Importing an entry grants no wallet or trading
authority and cannot start Coin Prep, create an offer, cancel an offer, or start
the bot. CATalyst requires a fresh local preview and explicit exact-asset and
budget acceptance.

## Publishing a record

1. Export a campaign manifest from CATalyst.
2. Approve its canonical message in Sage through WalletConnect.
3. Construct the redundant public record defined by `schema.json`.
4. Verify the Sage signature, network, exact 64-character asset ID, expiry, and
   every redundant field before publishing.
5. Set `asset_verification_status` explicitly to `VERIFIED` or
   `UNVERIFIED_ASSET`. A valid wallet signature does not verify an asset.

Publishers must reject unknown fields and noncanonical values. Records are
immutable. Renewal creates and signs a new manifest; it does not extend an old
record in place.

## Participation proofs

Participation proofs are separate signed documents. They contain only the
campaign ID, exact eligible offer/fill identifiers, and aggregate independent
depth, uptime, and within-corridor spread measurements. They intentionally omit
wallet fingerprints, balances, local paths, unrelated history, volume, reward
amounts, budgets, and reserves. Rewards, if an issuer chooses to offer them, are
external to CATalyst v1.4.0.
