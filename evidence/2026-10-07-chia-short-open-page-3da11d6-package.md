# Chia short open-offer page validation and exact Windows package

Evidence for draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220). Timestamps are UTC. This is not release authorization.

## Source and regression

- Exact runtime/source: `3da11d63608c0ef2093ad578d63c64155db2107d`.
- The Chia open-offer reader accepted a short page before validating trade IDs. An idless or duplicate-ID offer row could therefore be treated as part of a fresh authoritative book, while the full-page path rejected those rows.
- Two focused regressions failed on the predecessor for the expected reason. Moving the short-page return after the existing `complete_book()` validation makes both pass. The complete Chia pagination file passes **20 tests**; the related wallet/start-safety selection passes **369 tests**. Ruff check/format and `git diff --check` pass.
- All 11 PR checks passed on the exact source. The full serial Windows backend run recorded **7,326 passed, 241 skipped, 433 subtests, and one failure**: `test_api_import_does_not_start_cat_resolver_before_lease` exceeded its 15-second subprocess timeout while package building, installer testing, and Defender scans were also running. That isolated test passed on rerun in 1.50 seconds. This full-suite result is not counted as a clean pass; the combined successor needs an uncontended full run.

## Detached Windows package

- Clean detached build checkout: `E:\catalyst-chia-shortpage-3da11d6-build`, verified at exact source before `python build.py`; build succeeded.
- EXE SHA-256: `15957017478477595936B99DE94A5DD77D2CD99AFE1C070B1FEEC2B4B30F7EB3`.
- Bundled `bot_gui.html` SHA-256: `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`.
- ZIP SHA-256: `9DE9D4F3FAE00F7DAA0F9D589CEA4391A7539C30F46335882B7B1A66D94AE1ED`; **192 files** and 14 directory entries passed CRC, and the extracted EXE hash matched.
- Unsigned installer SHA-256: `81F036C2154740AB49803160051FEA3114D6C4822A5C8A0B90DA3FBF3FF73048`.
- Packaged API, synthetic Sage RPC, publication recovery, native clean/duplicate/persisted/safety, and independently downloaded ZIP extracted-API smokes passed. A unique-AppId, unique-name QA installer clean-installed to E:, its EXE hash matched, installed API and synthetic Sage smokes passed, and uninstall removed its EXE and QA registration. The original app registration was untouched.
- Defender real-time protection and antivirus were enabled. Custom scans of the bundle, ZIP, and installer completed with **six detections before and after**.
- Artifacts are pinned at commit `633129e90f86b4433a9353caaf0bdc89bccf6b70`; independent HTTP downloads of ZIP, installer, and manifest matched the pinned local files and hashes.

[Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/633129e90f86b4433a9353caaf0bdc89bccf6b70/acceptance-artifacts/CATalyst-3da11d6-primary-acceptance.zip) · [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/633129e90f86b4433a9353caaf0bdc89bccf6b70/acceptance-artifacts/Catalyst-Setup-3da11d6-1.4.0.exe) · [SHA256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/633129e90f86b4433a9353caaf0bdc89bccf6b70/acceptance-artifacts/SHA256SUMS-3da11d6.txt)

## Acceptance state

- Secondary PC independently reviewed exact source under pinned Python 3.12 and `chia_rs 0.30.0`: the Chia file passed **20 tests**, and its wallet/offer selection passed **1,008 tests with 374 subtests**. Its immutable-package acceptance passed **17 of 17** read-only checks. The [secondary report](https://github.com/catalystxch/catalyst-bot/blob/137ce74e9230189bb373e0efbb62d80dae253653/evidence/2026-10-07-secondary-3da11d6-readonly-acceptance.md) is on a separate evidence-only branch.
- Original TEST 7 still runs the predecessor `3ea62b3` while stopped; its monitor is historical for this new source. No `3da11d6` mainnet wallet action has occurred.
- A new exact-PID/hash original-profile stability trace, live active-offer lifecycle/recovery, secondary original-profile acceptance, both complete 24-hour windows, and final review remain open. No new campaign or fee approval exists. Keep PR #220 draft; do not merge, tag, release, or claim public readiness.
