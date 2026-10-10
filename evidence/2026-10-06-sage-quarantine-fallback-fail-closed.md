# Sage quarantine proof downgrade correction

Draft PR #220. Exact runtime/source candidate:
`61be438d67c015c6f49ee4d401c34266cb6e8091`.

The quarantine resolver accepted version 1 full-history or version 2 exact
Sage-absence proofs. Before this correction, a missing Sage exact-absence
reader caused `_collect_quarantine_resolution_proof()` to fall through to the
version 1 collector. A synthetic, empty, complete history could then pass
`validate_quarantine_resolution_proof()` with `allowed=True` even though no
exact Sage absence read occurred. The same broad `except: pass` could hide a
backend authority or Sage collector error and take that downgrade path.

A focused regression on parent source `a07252a` proved the defect: with Sage
selected and its exact absence reader unavailable, the collector produced a
version 1 proof and the validator returned `allowed=True`. No live wallet was
used. Commit `ad395ce` routed every Sage case through the version 2 collector,
which returns an incomplete proof when the exact read is missing or raises.
Chia retains its version 1 full-history path. Unknown or unreadable backend
authority now errors before proof collection, and the resolver returns a
failure without clearing quarantine. Commit `61be438` consolidated wallet
imports across the API module. A status-endpoint test caught a local variable
shadowing the new module import; that variable was renamed before publication.

The recovery suite passed 64 tests after the first fix. The final-source
affected recovery, wallet identity, status and WalletConnect suites passed
**252 tests and 4 subtests**. Ruff check, Ruff format, and `git diff --check`
passed. An independent secondary-PC read-only review of both commits found no
blocking safety or compatibility gap. All **11 exact-source PR checks** passed
on `61be438`. The full serial local Windows backend passed **7,245 tests,
225 skipped, and 431 subtests** in 1,055.79 seconds. The run exited zero.

## Clean Windows package

Detached build directory: `E:\catalyst-quarantine-fallback-61be438` at exact
source commit `61be438`. The executable is unsigned test evidence. The bundled
`bot_gui.html` SHA-256 remains
`9FD727C40DA72C56BE948B4BFBBD4205B8B2DE33B772ACAF32C5E5DCB37B1801`,
byte-identical to the earlier candidate whose Chromium UI suite passed 224
tests; this correction changes no frontend bytes.

| Artifact | SHA-256 |
| --- | --- |
| `dist\Catalyst\Catalyst.exe` | `78E32799968BC132B4CD3FA39733B45206F1BE08B8DF2354A5B80318B9C71576` |
| `CATalyst-61be438-primary-acceptance.zip` | `414DD20D78EC1118FDFB1B948F524521A7BAB3BB9776E98D702E10572D637754` |
| Unsigned `Catalyst-Setup-61be438-1.4.0.exe` | `C182FA25F72155C02E7F2FC692A6A60D4E25989ED6685D105D1266147A2FA723` |

Packaged API, mock Sage RPC, interrupted-publication recovery and native
clean/duplicate/persisted/safety smokes passed. ZIP CRC passed; all 206 entries
were readable and the embedded EXE matched the clean build byte for byte. An
isolated installer with a unique AppId installed a byte-identical EXE; its
installed API smoke and uninstall passed without leaving the test EXE or HKCU
registration. Defender custom scans of the bundle, ZIP and installer added
zero detections. Independent HTTP downloads of the two pinned binaries
matched the local hashes.

Artifact commit `3792fa66f88f2e679c8a319f458097b7346a4193`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/3792fa66f88f2e679c8a319f458097b7346a4193/acceptance-artifacts/CATalyst-61be438-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/3792fa66f88f2e679c8a319f458097b7346a4193/acceptance-artifacts/Catalyst-Setup-61be438-1.4.0.exe)
- [Hash manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/3792fa66f88f2e679c8a319f458097b7346a4193/acceptance-artifacts/SHA256SUMS-61be438.txt)

The previous exact `cbd7d08` stopped-profile monitor remains a historical
trace while `61be438` is verified. It cannot satisfy a 24-hour gate for this
new runtime. No live wallet effect or campaign action was taken for this fix.
PR #220 remains draft; live offer lifecycle, full exact-candidate stability
windows and final review remain open.

## Independent secondary isolated package acceptance

The secondary PC independently downloaded the pinned ZIP and installer and
matched their hashes and the extracted EXE hash. Packaged Sage mTLS worker,
API/mock-Sage startup and diagnostics, interrupted-publication recovery,
native clean/duplicate/persisted/safety launch, and packaged Playwright UI
traversal passed on an isolated profile. The seven primary views, Risk
Disclosure, Help, About, and reset-confirmation gating produced zero page,
console, or API 5xx errors. The exact report is
`evidence/acceptance-61be438-secondary-20261006T043050/REPORT.md` on that PC,
SHA-256 `5A202A8B6317A1098397DFC732640AFB06EDF40117D891DCF1B48B9DE42E664E`.
No wallet effect occurred.

Two samples of its older `cbd7d08` monitor recorded a second Catalyst process
while the isolated package launched. The protected original-profile app kept
port 5000, wallet balances, offers, locks, safety and lease unchanged; the test
processes exited and the count returned to one. Those alerts are preserved in
the historical trace. The final-candidate 24-hour window must begin after
rollover and be assessed independently.
