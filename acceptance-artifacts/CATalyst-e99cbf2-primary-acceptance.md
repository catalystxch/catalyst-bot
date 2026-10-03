# CATalyst e99cbf2 primary acceptance package

Draft PR #220 runtime/source commit:
`e99cbf263ae77929b6ccdb7a9874b78be2566dda`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `5AB44677B4EE7B610718527A9B75C328EF451254A88F97BB5512988749645D7E` |
| Bundled `_internal/bot_gui.html` | `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7` |
| `CATalyst-e99cbf2-primary-acceptance.zip` | `9D86FF2E6F4B8F177A19D748D7B52008CE652C7DC56E134D3A62BB0996EE602E` |
| `Catalyst-Setup-e99cbf2-1.4.0.exe` | `15E94188D7CBB5E8560EF63FB442DB5738330D95772293B1C5CBDEFBBB06BEE7` |

The 192-file ZIP passed complete CRC read, extraction, embedded EXE hash
comparison, and extracted API smoke. The detached EXE passed packaged API,
synthetic Sage RPC, publication recovery, and native clean, duplicate,
persisted-state, and safety launch smokes. A unique-AppId current-user QA
installer passed clean install, `ef3406f` to `e99cbf2` same-version upgrade,
rollback, restore, installed API/Sage, and final uninstall. Installed EXE
hashes matched at every step; QA registration and directory were absent
afterward. Defender custom scans of the bundle, ZIP, and installer returned
no matching detections.

The cross-wallet renewal regression was red on `ef3406f` and green on
`e99cbf2`. Four changed-identity cases and the valid same-wallet path passed;
all 43 Bootstrap API tests and all 208 Chromium tests passed. Ruff, format,
and all 11 exact-source PR checks passed. The full local Windows backend run
passed **7,159 tests**, with **one skipped** and **427 subtests passed** in
24m 15s.

Fresh HTTP reads of the pinned artifacts below matched their SHA-256 values:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e9c95b8aa7d58f1bbdad6364c55acf680be1c225/acceptance-artifacts/CATalyst-e99cbf2-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e9c95b8aa7d58f1bbdad6364c55acf680be1c225/acceptance-artifacts/Catalyst-Setup-e99cbf2-1.4.0.exe)

Original-profile TEST 7 startup, live lifecycle, restart/recovery, full UI,
both 24-hour windows, independent secondary acceptance, and final review
remain open. The prior campaign is expired; no replacement campaign or fee
approval has been received. Keep PR #220 draft.
