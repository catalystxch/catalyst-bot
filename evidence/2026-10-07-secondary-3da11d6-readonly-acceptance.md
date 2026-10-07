# CATalyst exact-3da immutable package — secondary read-only acceptance

Date: 2026-10-07 05:40–05:45 BST
Status: **HISTORICAL / SUPERSEDED — package checks passed, not a release verdict**

The primary review identified a later safety gap while this immutable-package check was running. This record therefore preserves only the completed read-only package evidence for exact source `3da11d63608c0ef2093ad578d63c64155db2107d`. No wallet was selected, no disclosure was bypassed, and no wallet-affecting operation occurred.

## Identity

- Source checkout: detached, clean `3da11d63608c0ef2093ad578d63c64155db2107d`
- Artifact branch head: `633129e90f86b4433a9353caaf0bdc89bccf6b70`
- ZIP SHA-256: `9DE9D4F3FAE00F7DAA0F9D589CEA4391A7539C30F46335882B7B1A66D94AE1ED`
- Installer SHA-256: `81F036C2154740AB49803160051FEA3114D6C4822A5C8A0B90DA3FBF3FF73048`
- Extracted `Catalyst.exe` SHA-256: `15957017478477595936B99DE94A5DD77D2CD99AFE1C070B1FEEC2B4B30F7EB3`
- Extracted `bot_gui.html` SHA-256: `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`
- EXE metadata: file version `1.4.0.0`, product version `1.4.0`, company `MonkeyZoo`, description `CATalyst - Chia AMM Liquidity Bot`
- Authenticode: `NotSigned`
- Manifest SHA-256: `36738081082780C9AD18833C737F3B89CA065D129FFD00D89AA3B58FB30EEBD5`

## Checks completed

1. `git rev-parse HEAD` returned the exact required source commit; `git status --short --branch` showed detached HEAD with no changes.
2. `git ls-remote origin refs/heads/codex/coin-prep-fee-approval-artifacts` returned the exact pinned artifact commit.
3. Independent HTTPS downloads of the ZIP, installer, and pinned manifest completed successfully.
4. All four required artifact hashes matched the manifest and handoff values exactly.
5. Python `zipfile.testzip()` checked 206 entries and returned `None` (no CRC failure).
6. The archive extracted into a new evidence directory; expected executable and UI assets were present.
7. Clean first launch used only the isolated `CMM_DATA_DIR` under this evidence directory. PID `2764` was responsive, owned only `127.0.0.1:5000`, and its running image hash matched the required executable hash.
8. `/` returned HTTP 200 with 2,215,026 bytes. `/api/health` returned `status=ok`, `version=1.4.0`, `bot_running=false`, wallet type `sage`.
9. `/api/status` remained fail-closed: `runtime_safety.allowed=false`, reason `WALLET_IDENTITY_BINDING_INVALID`, zero buy/sell/history offers, zero application errors, and zero balances because no wallet was selected.
10. `/api/sage/startup-status` reported idle/not running and an empty fingerprint.
11. Duplicate launch PID `2396` exited normally with code 0; original PID `2764` remained the sole listener.
12. The first process remained responsive through repeated health/status checks, with the bot stopped and error count zero.
13. Graceful `CloseMainWindow()` shut down PID `2764`; port 5000 was released.
14. Persisted-profile relaunch PID `12884` was responsive, used the same exact executable, owned port 5000, reported health OK/version 1.4.0/bot stopped, and remained fail-closed with the same identity-binding reason. Graceful close succeeded and released the port.
15. Final read-only database inspection showed zero rows in every checked trading/effect ledger: `offers`, `fills`, `fee_approvals`, `approved_fee_reservations`, `coin_prep_operations`, `offer_operation_journal`, `publication_outbox`, `reservation_leases`, `bootstrap_campaigns`, `wallet_effect_claims`, and `wallet_effect_dispatches`.
16. Windows Application event review found no CATalyst crash/error event during the test window. Log scan found zero matches for `ERROR`, `CRITICAL`, `Traceback`, `unhandled`, or `exception`.
17. Final state: zero `Catalyst.exe` processes and zero listeners on port 5000.

## Limitations and safety boundary

- The previously observed Windows UI-control helper failure (`failed to write kernel assets ... os error 3`) remains an automation-environment limitation. No stale-coordinate or alternative UI automation was used.
- Risk Disclosure, Connect Sage, wallet selection, native interaction, and visual GUI assertions were deliberately not exercised.
- No original user profile was read or mutated.
- No wallet identity was selected or assumed; no wallet, offer, fee, bot, campaign, cancellation, or coin-prep action occurred.
- The installer was downloaded and hash-verified but not executed; primary evidence already covered installer/Defender checks.
- This candidate is superseded by a later safety fix under review, so these passes do not support READY status for `3da11d6`.

## Result

Read-only immutable package checks: **PASS (17/17 recorded checks)**.
Release acceptance for this candidate: **NOT READY — SUPERSEDED BY LATER SAFETY FIX**.
