# Sage coin amount validation: exact source and primary package

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `60e2875d559a200f23453a2adb1c458853f3fc98`. This is an
intermediate acceptance record, not public-readiness approval.

## Defect and correction

Sage coin views accepted boolean, fractional, and negative amounts through
`int(...)` coercion. The complete spendable view could return those malformed
rows; detailed owned and selectable views also accepted them. CAT balance
summation accepted an alias-only `amt` record but counted it as zero. Red tests
reproduced all cases. The complete reader now uses the existing exact positive
atomic-amount parser and returns a canonical integer `amount`; the detailed
owned and selectable readers apply the same parser and fail closed on malformed
amounts. Valid `amt` aliases contribute their exact value.

## Source verification

- Focused Sage wallet tests: 26 passed. Broader related wallet tests: 55 passed
  with 9 subtests.
- Full serial Windows backend: **7,406 passed, 246 skipped, 447 subtests** in
  1,350.58 seconds.
- Isolated Chromium: **245 passed** in 144.59 seconds.
- Ruff check, Ruff format, and Git whitespace check passed. PR CI on this source
  was still running when this record was written; its final result requires a
  separate check.

## Detached Windows package

Built from clean detached checkout
`E:\catalyst-sage-amount-60e2875-build`. Build-generated version metadata was
the only tracked change in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `5481C1E8D4DAA57F5F8F76BF23422917FB95204EBFAE23F2326503BAE669E17B` |
| Bundled `bot_gui.html` | `A696815D885412C94E1B9B460D2976ED80288819A6E023C0DE60FC4AD0A32609` |
| ZIP | `A0418748E411190BD106315D5E07C2DF7E3DBCCD19E0207A83C907991164D9FB` |
| Unsigned installer | `DB7D4389766FCE2505E2E40110E1CD38F6064022A0E14C32F5F2F0942831510F` |

Packaged API, synthetic Sage RPC, interrupted-publication recovery, and native
clean, duplicate, persisted-profile, and safety startup smokes passed. The
192-file ZIP passed CRC and embedded EXE hash checks. The isolated QA installer
used a separate AppId and product name; it clean-installed to E:, its EXE hash
matched, installed API and synthetic Sage smokes passed, and silent uninstall
removed its EXE and registration. The first installed Sage smoke exceeded its
default 30-second timeout; a repeat with a 90-second ceiling passed in 2.4
seconds. This one-time startup delay remains a package observation, not a
verified deterministic failure. Defender real-time protection was enabled;
scans of the bundle, ZIP, and installer left six pre-existing detections at six.

The ZIP, unsigned installer, and manifest are pinned at artifact commit
`0ff872c71d2d07a10bd19439604021b92fba835b`. Independent HTTP downloads
matched the ZIP and installer SHA-256 hashes above. The downloaded ZIP also
passed CRC and embedded EXE hash checks.

- [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0ff872c71d2d07a10bd19439604021b92fba835b/acceptance-artifacts/CATalyst-60e2875-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0ff872c71d2d07a10bd19439604021b92fba835b/acceptance-artifacts/Catalyst-Setup-60e2875-1.4.0.exe)
- [SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0ff872c71d2d07a10bd19439604021b92fba835b/acceptance-artifacts/SHA256SUMS-60e2875.txt)

## Live and release gates

Exact `60e2875` has not run against the original TEST 7 profile. At this
checkpoint the sole original-profile app is the older `eadb82a` package; its
bot is stopped. The earlier Veeam-overlap stopped-profile 24-hour window
failed. Exact-source original-profile live lifecycle and recovery, secondary
exact acceptance, full native UI, both final-candidate 24-hour windows, and
final review remain open. The prior campaign is stopped and no new campaign or
fee approval exists. PR #220 remains draft; there is no merge, tag, release,
or public-readiness claim.
