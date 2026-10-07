# Sage open-offer identity gate and exact Windows package

Evidence for draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220). Timestamps are UTC. This is not release authorization.

## Source and regression

- Exact runtime/source: `f67739b63aae05c13e6d8c6c9f4d77aa0ef634fc`, incorporating the Chia short-page identity fix at `3da11d63608c0ef2093ad578d63c64155db2107d`. Feature merge head `702a24482b73d32efc2178453050679dcd305c1f` changes only historical secondary evidence after the exact source.
- Sage open-offer filtering could accept a row with no identity or a repeated identity and treat that response as a fresh authoritative book. The fix validates the filtered open book before return. Two focused tests failed against the predecessor, then passed with the fix; the startup-readiness module passed **22 tests and 6 subtests**, and the broader affected primary selection passed **392 tests and 6 subtests**. Ruff check/format and `git diff --check` passed.
- All **11 PR checks** passed on the combined merge head `702a24482b73d32efc2178453050679dcd305c1f`. Its clean, uncontended full serial Windows backend run passed **7,329 tests, 241 skipped, 433 subtests passed** in **1,341.72 seconds**. This supersedes the historical 3da full-suite run with one subprocess timeout.

## Detached Windows package

- Clean detached build checkout: `E:\catalyst-sage-open-id-f67739b-build`, verified at exact source before `python build.py`; build succeeded.
- EXE SHA-256: `A0C0BAA7F04792328E20AA87E99AC5034994C0F93E094789420DDD6BC59B635D`.
- Bundled `bot_gui.html` SHA-256: `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`.
- ZIP SHA-256: `A3E1424A02FEFDCAD665DC628BE4C829E0BB46043DE3BE7E81CC95EF1A6B6E0C`; 192 files and 14 directory entries passed CRC.
- Unsigned installer SHA-256: `E006EFB8D48F9B46CD7AA8748D994A1FE16CA5E49FDA357FA70D0252581869E5`.
- Packaged API, synthetic Sage RPC, publication recovery, native clean/duplicate/persisted/safety, and unique-AppId QA installer clean install, installed API/Sage, and uninstall passed. QA registry and files were removed without changing the original registration. Defender real-time protection remained on; bundle, ZIP and installer scans completed with six detections before and after.
- ZIP, installer, and hash manifest are pinned at artifact commit `1cec479169ee8dbe6392ad097e1cc4428f0221df`. Primary and secondary PCs independently downloaded and matched the ZIP, installer, EXE, bundled UI, and manifest hashes. Both verified ZIP CRC across 206 entries; the primary independently extracted the downloaded ZIP and passed the packaged API smoke from its EXE.

[Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1cec479169ee8dbe6392ad097e1cc4428f0221df/acceptance-artifacts/CATalyst-f67739b-primary-acceptance.zip) · [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1cec479169ee8dbe6392ad097e1cc4428f0221df/acceptance-artifacts/Catalyst-Setup-f67739b-1.4.0.exe) · [SHA256 manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/1cec479169ee8dbe6392ad097e1cc4428f0221df/acceptance-artifacts/SHA256SUMS-f67739b.txt)

## Acceptance state

- Secondary PC independently reproduced both predecessor failures, passed both new regressions, the 22-test Sage module, a 69-test wallet/recovery selection, the complete 263-test mutation gate, Ruff, and an isolated native clean/duplicate/persisted-profile smoke. The native smoke left zero ledger rows and no process or port 5000 listener. It found no defect in this read-only scope. Its [separate evidence report](https://github.com/catalystxch/catalyst-bot/blob/0bedcfd276c19fab185f142cf66d4ee728f83499/evidence/2026-10-07-secondary-f67739b-readonly-acceptance.md) is pinned at `0bedcfd276c19fab185f142cf66d4ee728f83499`. Secondary original-profile acceptance remains open.
- Original TEST 7 still runs the stopped predecessor `3ea62b3`; its monitor is historical for this new source. No `f67739b` mainnet wallet action has occurred.
- A new exact-PID/hash original-profile stability trace, live active-offer lifecycle/recovery, secondary original-profile acceptance, both complete 24-hour windows, and final review remain open. No new campaign or fee approval exists. Keep PR #220 draft; do not merge, tag, release, or claim public readiness.
