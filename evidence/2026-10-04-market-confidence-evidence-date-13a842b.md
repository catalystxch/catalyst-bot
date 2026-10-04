# Market confidence evidence date in Dashboard

Draft PR #220 exact source `13a842b445a8f72dfa59d1078e8a6b48a0956d2f`.
The original TEST 7 `dfc53d9` app remained stopped for trading and reported
RED market confidence. Its `/api/market/confidence` response on 2026-10-04
contained a safety snapshot derived at `2026-09-28T14:29:15.775248Z`, with
`confidence_snapshot_expired` and `market_evidence_expired` among the reasons.
The native Dashboard displayed only `15:29:15` under **Evidence Time**. The
provider observation renderer also discarded dates. This obscured the age of
the displayed safety evidence. The separate raw Dexie order-book response had
three buys and 29 sells; those raw rows did not make the persisted confidence
snapshot current or authorize Follow offer creation.

A browser regression rendered a six-day-old RED snapshot and asserted that
both the Dashboard evidence value and provider observation include the year
and a clock time. It failed before the fix with `15:29:15`, then passed after
the two timestamp renderers changed from `toLocaleTimeString()` to
`toLocaleString()`. Confidence classification and trading gates were not
changed. The full Chromium suite passed **212** tests. Ruff check and format
passed. A four-worker local Windows backend run passed **7,195 tests, 213
skipped, 431 subtests**. All **11** PR checks passed on this exact source.

## Clean detached Windows package

Built from a detached checkout at the exact source; generated version metadata
was the only tracked build change in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `E:\catalyst-confidence-date-13a842b-build\dist\Catalyst\Catalyst.exe` | `0C3010C816D216A28FFE1AEA48F17BC7271F3EF9CABEEA4E9998CE344F52EE50` |
| Bundled `_internal\bot_gui.html` | `1FD778D4CC109562FF69942BD705D6CB107067017445C9B5E65E3514EC50A001` |
| `CATalyst-13a842b-primary-acceptance.zip` | `C83D499E483EC84D73252D714F3F7AFC49491E46A51363B7151BD78DC445DAAF` |
| Unsigned `Catalyst-Setup-13a842b-1.4.0.exe` | `6B10695CEEB6954583FC0DDD807DDFD512EA2B69C431E0EDB908B682CE317F51` |

Packaged API, synthetic Sage RPC, publication recovery, ZIP CRC/embedded EXE,
isolated QA installer clean install, installed API and QA uninstall passed.
The QA installer used its own AppId, application name, E: directory and HKCU
registration; it did not replace the original profile or installed app.
Defender custom scans of the bundle, ZIP and unsigned installer returned no
attributable detections. Independent HTTP downloads of the pinned ZIP and
installer matched their local SHA-256 values.

Artifact commit `02c08185bf5691aaf4095cb726156de4253794dd`:

- ZIP: <https://raw.githubusercontent.com/catalystxch/catalyst-bot/02c08185bf5691aaf4095cb726156de4253794dd/acceptance-artifacts/CATalyst-13a842b-primary-acceptance.zip>
- Installer: <https://raw.githubusercontent.com/catalystxch/catalyst-bot/02c08185bf5691aaf4095cb726156de4253794dd/acceptance-artifacts/Catalyst-Setup-13a842b-1.4.0.exe>

The preceding `dfc53d9` exact app remained the sole original-profile process
with bot stopped and no campaign or offer action during this build. Live
verification of the new UI, both 24-hour windows, wallet lifecycle,
independent secondary acceptance, and final review remain open. PR #220 stays
draft; this is not a public-readiness claim.
