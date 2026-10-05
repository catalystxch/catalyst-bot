# Sage Task 9 evidence after wallet history growth

Draft PR #220 source checkpoint. This is source and test evidence, not a package or public-readiness result.

Sage's native `get_offers` reads its full offer table without pagination. The previous Task 9 source cap of 4,096 records therefore made an exact cancellation or fill unprovable once the wallet accumulated 4,097 terminal offers. The similarly capped wallet-wide transaction list could hide a confirmed transaction for an exact selected coin.

The Task 9 loader now reads the exact Sage offer ID and every member named by its validated durable cancellation cohort manifest. Missing or mismatched rows, a missing grouped manifest, an inconsistent member count, a failed reader, or a scope wider than 256 members leaves evidence incomplete. The classifier checks that all returned rows and selected-coin scope match the registered intent. On Sage, transaction evidence starts from the registered selected coins and reads their exact spent heights; a missing height reader or matching confirmed transaction leaves that source incomplete. Existing source bounds and cross-source identity checks remain in force.

Quarantine resolution explicitly continues to request full wallet history. Its absence proof cannot be inferred from exact-present offer reads, so a wallet with more than 4,096 total Sage offers remains fail-closed in that path. A separate bounded absence proof and regression are required before claiming that gate complete.

Verification on Windows in `C:\catalyst\.superpowers\pr239-primary-integration`:

- `python -m pytest tests\test_offer_reconciliation.py -q`: 324 passed.
- `python -m pytest tests\test_long_gap_recovery.py -q -k quarantine`: 19 passed.
- Focused exact Sage, cohort, transaction-height, scope and full-history contract cases: 9 passed.
- Ruff check, Ruff format check and `git diff --check`: passed.

The original TEST 7 profile still runs the prior `74da24c` executable in a stopped, read-only monitor. This source change has not been packaged or used for live wallet actions. Mainnet active-offer lifecycle/recovery, exact-candidate 24-hour windows, secondary live trading acceptance, quarantine history-growth recovery, and final review remain open. PR #220 stays draft.
