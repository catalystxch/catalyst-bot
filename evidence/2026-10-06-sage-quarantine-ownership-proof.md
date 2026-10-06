# Sage quarantine ownership proof

Draft PR #220, source parent `f73a2bd85be1ba205542530ca3752b6feaa6c04e`,
exact correction `cbd7d08e3efb99ee449efc5d5b3da2c6381f0d31`. Live
acceptance on original profiles remains pending.

The version-2 quarantine resolution path used an exact Sage coin read to check
selected inputs. Sage may omit the optional `owned` field from that response.
`_collect_sage_quarantine_absence_proof()` treated the omission as `True`, so
an otherwise complete exact-offer absence read could authorize release without
affirmative input ownership proof. The stability-kernel design requires both
offer absence and owned, unlocked inputs before clearing quarantine.

A focused regression kept the exact offer missing and coin unlocked, removed
the coin's `owned` field, and made the owned-wallet view unavailable. On the
parent source it failed as expected: the proof validator returned
`allowed=True` rather than denying release. The test did not use a live wallet.

The correction accepts an omitted `owned` field only when the exact coin ID
and amount are present in Sage's owned-only XCH or active CAT wallet view. An
explicit `owned=False` still denies release. The wallet identity is read again
after both the exact coin read and any owned-view reads, so an identity change
during collection invalidates the proof. Missing or failed owned-view reads
fail closed. The wallet IDs come from the selected Sage adapter, rather than
hard-coded defaults.

Independent review found a second gap before publication: Sage's owned view
can include offer-locked coins. A later owned-view offer lock or spent-height
contradiction now blocks release even when the earlier exact coin read looked
unlocked. Both cases were reproduced with red/green synthetic regressions.

The initial focused red/green regression passed after the ownership correction.
The affected recovery, Sage exact-evidence and offer-reconciliation suites
passed 399 tests on the combined correction. The full serial Windows backend
passed **7,243 tests, 225 skipped, 431 subtests** in 1235.30 seconds. Ruff
check and format, `git diff --check`, and all **11** PR checks passed. The
intermediate `f5dc2e7` EXE was built for isolated smokes only and superseded
before artifact publication or live use.

Independent secondary-PC review of exact `cbd7d08` found no concrete defect.
Its isolated checkout passed 82 targeted tests, 32 adjacent recovery/evidence
tests, and 17 adversarial ownership/lock cases. The review report is
`evidence/review-cbd7d08-sage-proof/REPORT.md` in the secondary task, with
SHA-256 `E507064E514B311B5719F60ED650455E19DB77676A3149F1838DCF157316B11F`.
The secondary original-profile monitor was not disturbed.

## Exact Windows package

Clean detached build at `cbd7d08` in
`E:\catalyst-quarantine-cbd7d08-build`. The bundled HTML hash remains
`9FD727C40DA72C56BE948B4BFBBD4205B8B2DE33B772ACAF32C5E5DCB37B1801`.

| Artifact | SHA-256 |
| --- | --- |
| `dist\Catalyst\Catalyst.exe` | `DBC3D205070D58E6C443FDC2C4BE28CE4B106359BAE285C31A87C70FBDA0AE26` |
| `CATalyst-cbd7d08-primary-acceptance.zip` | `C34D26C480B21B05077866E00EA259E9BD583D9659B779993684C368019232E9` |
| Unsigned `Catalyst-Setup-cbd7d08-1.4.0.exe` | `24D7F517C4F8BA4BFA44047CCD9F9BDB8E303069AE7CE92FBC574EAC55B44CFA` |

Packaged API, mock Sage RPC, interrupted-publication recovery, and native
clean/duplicate/persisted/safety launch smokes passed. The ZIP passed CRC and
embedded EXE byte comparison (206 entries). A unique-AppId isolated installer
clean install yielded an EXE with the same hash; installed API smoke and
uninstall passed, leaving no isolated EXE or HKCU registration. Defender custom
scans of the bundle, ZIP, and unsigned installer added zero detections.
Independent HTTP downloads of the pinned ZIP and installer matched both local
hashes.

Artifact commit `7b11d624d4c21ab49f49c4529b59785202b9c100`:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7b11d624d4c21ab49f49c4529b59785202b9c100/acceptance-artifacts/CATalyst-cbd7d08-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7b11d624d4c21ab49f49c4529b59785202b9c100/acceptance-artifacts/Catalyst-Setup-cbd7d08-1.4.0.exe)

No wallet effect was initiated for this finding.

The previous exact `f73a2bd` stopped-profile monitors remain live while the
new package is prepared for original-profile acceptance. Their results cannot
count as a completed 24-hour window for this later runtime candidate. PR #220
remains draft; active-offer lifecycle, both exact-candidate 24-hour windows and
final review remain open.
