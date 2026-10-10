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

## Initial original TEST 7 read-only acceptance

The predecessor `f73a2bd` remained stopped with zero open offers and correct
Sage TEST 7 identity. Its GUI-equivalent shutdown route was called with
`cancel_offers:false`; process PID `160304` and port 5000 exited. Its monitor
recorded 109 clean stopped-profile samples, then a process-exit and end record.
No cancellation or wallet mutation was requested.

The exact `cbd7d08` EXE started as sole PID `149044`, SHA-256 matched the clean
build, and it alone owned `127.0.0.1:5000`. The native window showed Risk
Disclosure, which was acknowledged under the operator's standing testing
authorization. The native startup flow selected Sage mainnet TEST 7 fingerprint
`736588221`, skipped unavailable Splash, retained the existing Spacescan key,
and selected MZ/XCH. The selected CAT wallet ID was `2`, asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
The wallet was synced; balances remained `138.470301476875` XCH and
`780212.284` MZ. The bot was stopped, Bootstrap inactive, DB open-offer count
zero, and runtime safety ALLOWED with an owned renewing lease.

Native read-only traversal loaded Dashboard, Offers, P&L, Market Intelligence,
Settings Setup and Live tabs, Logs, Help, About and Data Reset. Offers showed
zero active and three historical fills; Market Intelligence showed Dexie and
Sage ready, Splash unavailable, Spacescan enabled, and RED attributable-book
confidence. No Save, Reset, Start, campaign, fee approval, offer, or transaction
action was taken. The UI was left on the stopped Dashboard.

The new exact-PID/hash stopped-profile monitor is
`E:\catalyst-stability-monitor-cbd7d08\monitor.ps1` (SHA-256
`CEE1A37583D3B3AA855BF447E2DB985C6766CA9E128AE026DB1C2F656F8120E2`).
Its first clean sample was `2026-10-06T02:25:58.5283494Z`. The 24-hour gate
cannot finish before `2026-10-07T02:25:58Z` and requires the full trace and
end-state review. Four initial samples through `02:29:01Z` were clean; this is
only a stopped-profile window, not a live trading window. The secondary PC
was assigned an independent original-profile exact-candidate pass and monitor.

No wallet effect was initiated for this finding.

The previous exact `f73a2bd` traces are historical and cannot count as a
completed 24-hour window for this later runtime candidate. PR #220 remains
draft; active-offer lifecycle, both exact-candidate 24-hour windows and final
review remain open.

## Independent secondary original-profile read-only acceptance

The secondary PC independently verified the pinned `cbd7d08` ZIP and its
extracted EXE hashes, stopped its predecessor after a clean final sample,
and launched the exact candidate as the sole CATalyst process and port-5000
owner against its original Harvestr profile. Through the packaged UI it
acknowledged Risk Disclosure under the operator's testing authorization,
connected Sage mainnet, selected fingerprint `3702373391`, and selected the
same exact MZ asset ID. Sage and CATalyst agreed on CAT wallet ID `2`,
unchanged balances of `240.800676512155` XCH and `3381521.72` MZ, zero
pending and fillable offers, zero CATalyst offers/locks/fee holds/reservations/
unresolved operations, a stopped bot, allowed safety, and an owned lease.
The old campaign remains active but expired with `cancel_required=true`; no
new campaign or wallet-effect action occurred.

The secondary read-only UI traversal covered Dashboard, Offers, P&L, Market
Intel, Settings, Logs, Doctor, Data Reset, Help and About with zero console,
page, or failed-API errors. The native-control test helper lacked its runtime
assets on that PC, so the interactive traversal used Chromium against the
exact packaged executable's loopback server; this limits the claim to packaged
frontend behavior, while the native executable launch, hash, process, and
port ownership were independently checked. Sixteen screenshots and the full
report are at the secondary PC's
`evidence/acceptance-cbd7d08-20261006T0320BST/REPORT.md` (SHA-256
`F5F0BEF39DF99CA07FFAD7CFA7DE2D06D4A848A22C5AD9264524EEEB96CF4165`).
The [native-helper diagnosis](https://github.com/catalystxch/catalyst-bot/blob/6cfd7e006b013f1d9b614ee8ec7e9dbc8acd1be2/evidence/secondary-cbd7d08-original-profile/native-helper-diagnosis.md)
(published SHA-256
`A1A7472219E77AC714AE78FD7699844214979DC677117BC7F72C04B05E92DE4E`)
records that the secondary task's active computer-use surface was browser-only
and its REPL failed before native control could initialize. The published
38-entry [manifest](https://github.com/catalystxch/catalyst-bot/blob/6cfd7e006b013f1d9b614ee8ec7e9dbc8acd1be2/evidence/secondary-cbd7d08-original-profile/SHA256SUMS.json)
includes that exact report hash and byte count. Its immutable Git/HTTP bytes
have SHA-256 `F1BD92D7CC7C9011D4271EBF99D7C70031E393D2C66D9261EDB97799969A32C3`;
the secondary Windows checkout has CRLF line endings and a different local
manifest-file hash.
The 38-file [immutable secondary evidence tree](https://github.com/catalystxch/catalyst-bot/tree/c3149267d939783aa16ca22d9118464a2945196e/evidence/secondary-cbd7d08-original-profile)
is pinned at commit `c3149267d939783aa16ca22d9118464a2945196e`.
An independent HTTP fetch of its
[report](https://github.com/catalystxch/catalyst-bot/blob/c3149267d939783aa16ca22d9118464a2945196e/evidence/secondary-cbd7d08-original-profile/README.md)
returned HTTP 200 and matched that SHA-256; the remote branch resolved to
the same commit. The secondary manifest SHA-256 is
`19D3E8080A512A2C98057C82F12A5BABCD833B8C101D226A11E5FE0BA7C71BF5`.

Its exact-PID/hash stopped-profile monitor began at about `02:40Z`; the
monitor script SHA-256 is
`0398BEC86B13FA5D7FCF4D5A921C6CB8BEA68087E498AEB70E7833FC3B1E88DC`.
The first ten live samples through `2026-10-06T02:48:07Z` were clean, with
zero alerts; six initial samples are frozen in the evidence tree. The complete
24-hour trace and end-state
review remain pending. This secondary read-only pass does not establish an
active-offer lifecycle or live trading stability window.

## Exact-candidate primary campaign preview without wallet effect

At `2026-10-06T02:56Z`, the sole primary PID `149044` still matched EXE
SHA-256 `DBC3D205070D58E6C443FDC2C4BE28CE4B106359BAE285C31A87C70FBDA0AE26`.
In its native Settings UI, Bootstrap was selected locally and a review-only
preview was generated for the already discussed TEST 7 MZ/XCH limits:
`0.000075` XCH/MZ anchor, one-day expiry, `0.9` XCH and `12,000` MZ market
budgets, `0.001` XCH fee budget, and zero optional subsidy. The preview showed
the exact asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
fixed corridor `0.0000375–0.00015`, first stage `10%`, and three buy plus
three sell offers. Its exact-asset acknowledgement remained unchecked and
Start Campaign disabled. Follow mode was then restored locally without Save.
Read-only API rechecks showed bot stopped, Bootstrap inactive, no campaign,
zero open offers, safety allowed, and unchanged `138.470301476875` XCH and
`780212.284` MZ balances. No fee approval, offer, or wallet mutation occurred.
This preview is not authorization to start a new campaign or incur network fees.
