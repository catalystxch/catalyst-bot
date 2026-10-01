# Spent Coin Prep recovery integration and exact Windows package — 30 September 2026

## Source and review

The secondary Harvestr profile exposed a confirmed direct-batch Coin Prep
operation that could not pass startup recovery after five of its 31 sealed
outputs were later spent. The final secondary [PR #231](https://github.com/catalystxch/catalyst-bot/pull/231)
head `9a33697f57a2a61d02a07b808d51eb8a48879e70` was independently reviewed
and integrated into draft PR #220 as one source commit,
`b352516c491f57a72758a9d25c82052c16444956`. Squashing kept the first,
unsafe intermediate PR #231 revision out of PR #220 history.

The first revision proved the sealed outputs but then inserted all 31 as free
capacity. The secondary task reproduced that error on an isolated profile
copy. The final source carries the five later-spent heights through bounded
authoritative evidence and the database transaction. Those outputs remain
`spent` with null purpose; protected permanent trade history remains untouched.
Absent outputs without spent proof and current outputs with contradictory spent
proof fail closed. Real Sage records omitted asset and ownership fields, so the
final lookup does not copy caller-supplied asset hints into purported evidence.
The sealed, pre-dispatch output identities retain their asset binding. Full
secondary proof and its exact profile-copy results are in
`evidence/2026-09-30-spent-coinprep-startup-recovery.md`.

Primary review of the final diff found no remaining spent-output resurrection
path. The two affected test files passed **74 tests** on the primary machine.
The complete local Windows backend suite passed **7,082 tests, 179 skipped,
422 subtests** in 1,279.52 seconds. Chromium passed **178 tests**. Ruff lint,
format, and diff checks passed. All **11 PR checks** passed on the exact source
head, including unit, lint, CodeQL, Semgrep, and secret scanning.

## Detached Windows package

A clean detached checkout of exact source `b352516c` built a Windows EXE.
Packaged API, synthetic Sage RPC, and upgrade/publication recovery smokes
passed. The ZIP passed CRC, contained 206 entries, included `.env.example`,
contained no profile `.env` or database, and its extracted EXE matched the
built hash. The extracted EXE passed packaged API smoke.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `BC76ECD9D24FAC983ED4852FA1709322ED640AABBCA0806659D2E9041F847EE7` |
| `CATalyst-b352516-primary-acceptance.zip` | `F9B3C822CAACCD255C44F531E47F4FF1693851BF7FB4ED2CC2367BDC40D2D86D` |
| `Catalyst-Setup-b352516-1.4.0.exe` (unsigned) | `E0862DA93A7B173BAD40FAFBE7E08BF204F167CCF4ABD899348633EE1D23B280` |

The unsigned installer completed an isolated current-user clean install to
`C:\catalyst\.superpowers\installed-b352516`. Its installed EXE matched the
built hash, the registration showed version 1.4.0, and installed API and Sage
RPC smokes passed. Silent uninstall removed the EXE and registration. This did
not use the primary user profile or create a wallet effect. Defender custom
scans of the downloaded ZIP and installer returned successfully, with no new
matching threat detection; both downloaded hashes remained intact.

Acceptance files and checksum sidecars were pushed to artifact commit
`d542cf74e3a3f9f5f162720bf184a5f66f200a8f`. Independent HTTP downloads
from that commit matched the local ZIP and installer hashes:

- [Exact ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d542cf74e3a3f9f5f162720bf184a5f66f200a8f/acceptance-artifacts/CATalyst-b352516-primary-acceptance.zip)
- [Exact unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d542cf74e3a3f9f5f162720bf184a5f66f200a8f/acceptance-artifacts/Catalyst-Setup-b352516-1.4.0.exe)

These are acceptance artifacts, not a public release.

## Independent secondary PC verification

The secondary PC fetched the exact `b352516c491f57a72758a9d25c82052c16444956`
source and verified that the later PR head `946fc8f6bc9ac76655e3afb41a226843ec02f77d`
changes only documentation. Its independent download matched the ZIP, extracted
EXE, and unsigned installer hashes above. Embedded `bot_gui.html`, `splash.html`,
and `.env.example` matched the exact source byte for byte. Focused recovery
verification passed **77 tests** in 10.99 seconds; Ruff and diff checks passed.

Read-only Sage RPC from an isolated minimal profile proved Chia mainnet,
Harvestr test wallet fingerprint `3702373391`, CAT wallet ID `2`, and exact MZ
asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Balances were 240.800786441412 XCH and 3,381,521.720 MZ, with zero fillable
Sage offers. No CATalyst process was running. The original secondary profile
and its authoritative backup were left untouched. No wallet action or fee
occurred.

The secondary PC could not start packaged runtime/UI acceptance: automatic
approval review had rejected direct execution of a prior candidate EXE on
that host before process creation, so this exact EXE was not launched by an
alternate mechanism. Windows UI inspection also failed twice during its own
initialization with `failed to write kernel assets: The system cannot find the
path specified (os error 3)`, before reaching Sage or CATalyst. The secondary
did not route around either block. Its live Coin Prep, offers, native UI, and
stability gates remain unverified.

## Native and live acceptance boundaries

The isolated native first-launch smoke displayed the first-run window and
confirmed trading stayed blocked, but its duplicate-launch foreground check
timed out. The same smoke now fails identically against the prior `b4a3daf`
package, whose desktop code is unchanged by this recovery patch. Diagnostics
showed the original profile lock still named the owner PID, the startup
arbiter was free, and the duplicate safely opened a read-only diagnostics
listener. The owner window was restored but Windows kept `TextInputHost.exe`
foreground. The same source-level foreground attempt from the test parent
returned false. No second mutation owner or wallet effect occurred. This
automated native foreground handoff gate remains **unverified**; it is not
counted as a package pass or attributed to the Coin Prep change.

At the 22:50 UTC process check, no CATalyst process or port 5000 listener was
present. Automatic approval review previously rejected a command-tool live
launch against the primary profile with `blocked by policy`; this was not
retried through another tool. The approved PR campaign expired before this
source ran live and has no exact-candidate fee approval or wallet effect. No
renewal was created. Primary and secondary exact-candidate Coin Prep, offer
lifecycle, restart recovery, 24-hour stability, full interactive UI, and final
review gates remain open. Keep PR #220 draft; no main merge, tag, release, or
public-readiness claim follows from these isolated tests.
