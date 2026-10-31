"""Shared lifetime terms for reviewed Follow runs."""

# Exact integer in JSON and SQLite. This sentinel represents a run that ends
# only through a recorded Stop or another financial/safety gate.
CONTINUOUS_RUN_EXPIRY = 2**53 - 1
