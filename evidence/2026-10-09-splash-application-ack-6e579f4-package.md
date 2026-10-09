# Optional Splash application acknowledgement: exact `6e579f4`

Runtime/source `6e579f4ec62857e6b7051ee94ec733def74a02bf` on draft PR
#220 keeps Splash as an opt-in offer broadcaster. It corrects a false
acknowledgement in both the durable publication path and legacy posting path.

## Defect and correction

The [upstream Splash 0.2.0 HTTP handler](https://github.com/dexie-space/splash/blob/11d2a826ec492a1391158ca3c290f0fff8e61604/src/main.rs)
returns HTTP 200 with JSON `success: true` when its local broadcast function
accepts an offer, and HTTP 200 with `success: false` and an error when it
rejects one. CATalyst previously treated either HTTP 200 as success. A local
rejection could therefore mark a durable publication acknowledged or add the
offer fingerprint to the legacy posted set.

CATalyst now acknowledges Splash only when a parsed JSON object contains the
exact boolean `success: true`. Exact `success: false` is recorded as a
response-bound, no-effect rejection and remains retryable. Missing, malformed,
or truthy-lookalike success values remain ambiguous/unresolved. The change
does not equate local Splash queue acceptance with delivery to another peer.
Dexie and wallet mutation paths are unchanged.

## Source verification

- Two red/green regressions reproduced the durable and legacy HTTP 200
  `success: false` false acknowledgement on the parent source, then passed
  after the correction.
- Primary focused nine-file Splash/publication suite: **262 passed, four
  subtests**, exit 0. Changed-file and repository-wide Ruff check/format pass.
- Independent secondary PC checked the exact commit in an isolated worktree:
  **262 passed, four subtests** in 44.55 seconds; changed-file Ruff passed.
  Its separate 12-case transport matrix passed exact boolean, missing,
  malformed, wrong idempotency echo, and malformed provider-ID cases. It
  restored its worktree clean and did not launch Splash or touch a wallet.
- All **11** PR checks passed on the exact source. The complete serial local
  Windows backend suite passed **7,516 tests, 259 skipped, 455 subtests** in
  2,576.12 seconds, exit 0.

## Clean Windows package

A detached clean checkout of the exact source produced the files below. ZIP
CRC passed; its extracted 192 files match the build byte for byte. Packaged
API, synthetic Sage, publication recovery, native clean/duplicate/persisted/
safety, extracted ZIP API, and unique-AppId QA installer clean install,
installed API/Sage, prior-package update, rollback, restore, and uninstall
passed. Microsoft Defender custom scans of EXE, ZIP, and installer returned
no new detections. The canonical installer remains unsigned.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-splash-6e-build\dist\Catalyst\Catalyst.exe` | `0D6EACE79EDAB03778F84C098D5C0C486E421570A0E886BE1204F5BDDAB07E63` |
| Bundled `bot_gui.html` | `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0cc901931342798eef67f2876b58b2a20a249014/acceptance-artifacts/CATalyst-6e579f4-primary-acceptance.zip) | `5026827AB50414FC486BB6EE2AED6F1AF8A9CAE630004F8976C721C474AEF8F6` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0cc901931342798eef67f2876b58b2a20a249014/acceptance-artifacts/Catalyst-Setup-6e579f4-1.4.0.exe) | `DE41E089D9C30A49E8BB1EAAFBDF906FBAAE2305CF85F1B28A116A06D10D22F0` |

The ZIP, installer, and manifest are pinned at artifact commit
`0cc901931342798eef67f2876b58b2a20a249014`. Primary independent HTTP
streams of both pinned files returned status 200 with exact byte counts and
matching SHA-256 hashes. The secondary PC independently streamed both files
without writing large artifacts to its constrained C: drive. It matched both
byte counts and hashes, verified all 206 safe unique ZIP entries and full CRC,
and matched embedded EXE/UI hashes. It also checked the separate pinned
`SHA256SUMS-6e579f4.txt` Git blob byte for byte against HTTP, including all
four listed hashes and the runtime source. The ZIP has no internal manifest;
the authoritative manifest is that separate pinned file.

## Open acceptance gates

No independent Splash peer has received an exact matching live offer from
this candidate. The original TEST 7 profile still runs a historical binary;
exact `6e579f4` has not run there. The prior campaign is stopped, and no new
campaign/fee scope was approved. The primary and secondary exact-candidate
live lifecycle/recovery, full original-profile UI, both 24-hour windows, and
final review remain open. PR #220 and website PR #89 stay draft. There has
been no merge, tag, release, website deployment, or public-readiness claim.
