# Sage open-offer identity aliases: exact Windows package

Draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220), exact
runtime/source `310dcc3ddb3cb4562b35080498316f1e3b92a636`.
This record is not a public-readiness or release approval.

## Failure and correction

The Sage adapter's `get_all_offers(include_completed=False)` accepted a
non-hex open-offer ID, two conflicting IDs on one row, or two representations
of the same ID across separate open rows. Its uniqueness check compared raw
strings and did not validate the exact 32-byte hex identity. A fresh offer-book
read could therefore pass an ambiguous identity to startup, cancellation, or
mutation safety decisions.

The regression at `tests/test_wallet_sage_startup_readiness.py` failed in all
three cases before the correction. The adapter now compares canonical IDs,
requires exactly 64 hexadecimal characters, rejects disagreeing `trade_id`
and `offer_id` fields, and rejects duplicates across the open book. A positive
case preserves compatible case and `0x` encodings of the same identity on a
single row. The adapter returns failure rather than an empty offer book when
the identity cannot be trusted.

## Source verification

- Focused startup-readiness module: **24 tests and 9 subtests passed**.
- Broader Sage/wallet, bot-start, and mutation selection: **409 tests and 24
  subtests passed**.
- Repository `ruff check src tests`, `ruff format --check src tests`, and
  `git diff --check` passed.
- [Secondary PC](2026-10-07-secondary-310dcc3-readonly-acceptance.md)
  independently reproduced the three parent failures, passed the new source
  assertions, **430** selected tests and **24** subtests, built a fresh local
  EXE, and passed isolated clean, duplicate, and persisted-profile native
  smokes without wallet effect. Its local EXE is not the primary immutable
  acceptance artifact.
- The clean full serial Windows backend passed **7,331 tests, 241 skipped,
  436 subtests passed** in **1,374.20 seconds**. All **11 PR checks** passed
  on the exact source commit.
- Full Chromium from the preceding byte-identical UI candidate remains
  applicable; this source commit changes only the Sage adapter and its test.

## Detached Windows package

Built from clean detached checkout
`E:\catalyst-sage-identity-310dcc3-build` at exact source `310dcc3`.
The build succeeded; generated version metadata was the only tracked change
in that checkout.

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `D4705DD2764A7D27C19DA8E1B10505CFDDCF9FF7529E199159675ADBF0B902D7` |
| Bundled `bot_gui.html` | `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781` |
| ZIP | `085DAF16DBCA5C34298CD174F4E2127429270E01FAD237C9A2AE68D9DFFA7A08` |
| Unsigned installer | `08B88F8C11A8B88DD5929556DA222E9C27E04508292067D6AE7F1B45ABEDEF93` |

Packaged API, synthetic Sage RPC, publication recovery, and native clean,
duplicate, persisted-profile, and safety smokes passed. The ZIP has 206
entries, clean CRC, and embedded EXE/UI bytes matching the detached build.
The extracted ZIP EXE passed the packaged API smoke.

An isolated installer compiled with separate name and AppId
`{F0A07562-3452-4BD0-8355-F95C6C4AAC12}` installed into a dedicated E:
directory. Its installed EXE hash matched the detached build; installed API
and synthetic Sage smokes passed. The silent uninstaller exited zero and
removed its QA EXE and registry entry. The original current-user registration
was absent both before and after this test. Defender real-time protection
remained enabled; custom scans of the bundle, ZIP, and unsigned installer left
the six pre-existing detections unchanged.

ZIP, installer, and manifest were pinned at artifact commit
`0dbec31691a8d5e50890f440733d61c7d8b20015`. Independent HTTP downloads
of all three matched the local hashes. The downloaded ZIP passed CRC and
embedded EXE/UI hash checks; an EXE extracted from that download passed the
packaged API smoke. The manifest SHA-256 is
`CDB84F71DC7DD44F7FAC3E1DB7BC4288E3679033E6759F499C8A8D96D52BD83B`.

- [Pinned ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0dbec31691a8d5e50890f440733d61c7d8b20015/acceptance-artifacts/CATalyst-310dcc3-primary-acceptance.zip)
- [Pinned unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0dbec31691a8d5e50890f440733d61c7d8b20015/acceptance-artifacts/Catalyst-Setup-310dcc3-1.4.0.exe)
- [Pinned SHA-256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/0dbec31691a8d5e50890f440733d61c7d8b20015/acceptance-artifacts/SHA256SUMS-310dcc3.txt)

## Live acceptance state

At the package checkpoint, the original TEST 7 profile still runs the
preceding f677 candidate with bot stopped, zero open offers, and clean
exact-process monitoring. The new source has not yet run against that profile.
No campaign or fee approval was created; active-offer lifecycle, secondary
original-profile acceptance, both final-candidate 24-hour windows, and final
review remain open. Keep PR #220 draft; no merge, tag, release, or public-use
claim.
