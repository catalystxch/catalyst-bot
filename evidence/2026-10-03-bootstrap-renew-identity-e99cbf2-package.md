# Bootstrap renewal identity gate and exact e99cbf2 package

Draft PR #220 runtime/source commit:
`e99cbf263ae77929b6ccdb7a9874b78be2566dda`.

## Defect and correction

`/api/bootstrap/renew` required the named prior campaign to be stopped but
did not compare its stored Sage wallet and asset to the currently selected
identity. A red isolated regression showed that naming a stopped campaign from
another wallet returned HTTP 200 and created new authority under the current
wallet. This made the renewal's prior-campaign provenance false even though
the new campaign's preview used the current identity. No live wallet effect
was involved in the reproduction.

The endpoint now compares network, wallet type, fingerprint, CAT wallet ID,
and exact asset before creating renewed authority. Parameterized regressions
reject changes to fingerprint, CAT wallet ID, asset, and network with HTTP
409 `bootstrap_identity_mismatch`; a same-wallet stopped campaign still
renews. All five focused cases and all 43 Bootstrap API tests passed. The
complete Chromium suite passed 208 tests. Ruff check, format, and diff checks
passed. All 11 exact-source PR checks passed. The complete local Windows
backend run passed **7,159 tests**, with **one skipped** and **427 subtests
passed** in 24m 15s.

## Exact Windows package

- Clean detached build: `E:\catalyst-e99cbf2-primary-build`.
- `Catalyst.exe` SHA-256:
  `5AB44677B4EE7B610718527A9B75C328EF451254A88F97BB5512988749645D7E`.
- Bundled `_internal/bot_gui.html` SHA-256:
  `575AE136DC2C144BC5A10F93DDCDF57FD206063DC28C276CF60FB9741B586CF7`.
- 192-file ZIP SHA-256:
  `9D86FF2E6F4B8F177A19D748D7B52008CE652C7DC56E134D3A62BB0996EE602E`.
- Unsigned installer SHA-256:
  `15E94188D7CBB5E8560EF63FB442DB5738330D95772293B1C5CBDEFBBB06BEE7`.

Packaged API, synthetic Sage RPC, publication recovery, native
clean/duplicate/persisted/safety, ZIP CRC and extracted API passed. A
unique-AppId current-user QA installer passed clean install, prior `ef3406f`
to `e99cbf2` same-version upgrade, rollback, restore, installed API/Sage,
and final uninstall. Installed EXE hashes matched each version; the QA
registration and directory were absent after uninstall. Defender custom scans
of the bundle, ZIP, and installer returned no matching detections.

Artifact commit: `e9c95b8aa7d58f1bbdad6364c55acf680be1c225`. Independent
HTTP reads of both pinned artifacts matched the local hashes above.

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e9c95b8aa7d58f1bbdad6364c55acf680be1c225/acceptance-artifacts/CATalyst-e99cbf2-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/e9c95b8aa7d58f1bbdad6364c55acf680be1c225/acceptance-artifacts/Catalyst-Setup-e99cbf2-1.4.0.exe)

## Open gates

The exact package has not run against the original TEST 7 profile. Its prior
campaign is expired; no replacement campaign or fee approval has been
received. Earlier automatic approval review rejected command-tool live
launch of a predecessor before execution, so the operator must manually
start this exact EXE, personally acknowledge Risk Disclosure, and connect
Sage. Live lifecycle, restart/recovery, full interactive UI, both 24-hour
windows, independent secondary acceptance, and final review remain open.
PR #220 stays draft; no main merge, tag, release, or public-readiness claim.
