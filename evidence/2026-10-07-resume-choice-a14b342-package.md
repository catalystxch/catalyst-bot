# Exact a14b342 failed fresh-start recovery and Windows acceptance

All times below are UTC. This records evidence for draft PR [#220](https://github.com/catalystxch/catalyst-bot/pull/220); it does not authorize release.

## Source and regression

- Exact runtime/source is `a14b34234fabea80dcde9c7f875b8ebd054922da` on `codex/coin-prep-fee-approval`. The PR remains draft against `main`.
- The resume modal's Start Fresh path set `_resumeHandled` and cleared the in-memory resumed offer-book summary before POST `/api/session/fresh-start` succeeded. On a rejected durable choice, the modal stayed open but lost the verified resumed-book authority. Both direct modal and post-load entry points failed red when the regression asserted that authority and retry state remained intact. Moving those state changes after server success made both pass; the existing success case passed too.
- The focused recovery tests passed **4 tests**. Full Chromium passed **240 tests**. Ruff check/format and `git diff --check` passed. All **11** exact-source PR checks passed, including unit tests, lint, CodeQL, Semgrep, Gitleaks, and security scan.
- Production backend files are byte-identical to `293d823c486c792f90c188c4e840ce2a8ddecddf`, whose full serial Windows backend passed **7,315 tests, 234 skipped, 433 subtests passed**. A full local backend rerun was not performed for this frontend-only child.

## Clean detached package

- Detached build checkout `E:\catalyst-resume-choice-a14b342-build` was created at exact source. `python build.py` passed.
- EXE `E:\catalyst-resume-choice-a14b342-build\dist\Catalyst\Catalyst.exe`: SHA-256 `337D5529CA488EE6A179A0E84E010019AD614B2473718403253C382D5B2237CB`.
- Bundled `bot_gui.html`: SHA-256 `B0C25FB5C23D5A0B20E78CCC0B23A8DAC29FCBF104B6DCCDAD7B3B76811F6781`, byte-identical to source.
- ZIP `CATalyst-a14b342-primary-acceptance.zip`: SHA-256 `B1CB98FAAD7A8D985CD107BC4DA3F81B158F5514ECBBA9340118B5945B8E319E`. All 192 entries passed CRC; no `.env`, DB/WAL/SHM, fresh-start marker or crash log was bundled. Extracted EXE matched the build and passed packaged API smoke.
- Unsigned installer `Catalyst-Setup-a14b342-1.4.0.exe`: SHA-256 `AD4F3E8AC062E157942734AE82720F953D5C6F68175EDED837A5B0F4C9701973`. The production installer was compiled but not installed.
- Packaged API, synthetic Sage mTLS worker, interrupted-publication recovery, native clean/duplicate/persisted/safety launches, and extracted ZIP API passed. Separate-name QA installer AppId `{34B7450A-6D73-4476-B759-26B7389E3E94}` clean-installed to E, matched the EXE hash, passed installed API smoke, then uninstalled with its executable and registration absent. It did not use the production registration.
- Defender was enabled with real-time protection; custom scans of bundle, ZIP and installer completed and no new threat detection appeared. ZIP, installer and SHA256 manifest were pinned at artifact commit `3b6bd1d902b6ef4b61ec81a31d999f54ee4cfac5`. Independent HTTP downloads of all three matched the local hashes.

## Original TEST 7 rollover and read-only acceptance

- Before rollover, sole `e55d912` PID `173568` and port 5000 owner matched its expected EXE hash. Bot was stopped; safety allowed with an owned renewing lease; Sage was synced with zero offers. Its trace had **18 clean samples** through `2026-10-07T02:29:28Z`. The visible app's Close app action shut it down, leaving no Catalyst process or port 5000 listener; that trace is historical and cannot satisfy the final 24-hour gate.
- Exact `a14b342` launched against the original profile as sole PID `39492` and port 5000 owner. Its on-disk path/hash matched the clean EXE. Testing Risk Disclosure was acknowledged in the native UI, Sage TEST 7 fingerprint `736588221` was selected, optional Splash was skipped while stopped, the configured Spacescan key was retained, and Monkeyzoo Token MZ/XCH was selected. No settings save, bot/campaign start or wallet-offer action occurred.
- Direct Sage read-only RPC and database reads after the native Dashboard/Offers/P&L/Market Intelligence/Settings Setup and Live/Logs/Data Reset/Help/About traversal confirmed mainnet TEST 7, CAT wallet ID `2`, exact MZ asset `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`, unchanged XCH selectable balance `138470301476875` mojos and MZ balance `780212284` atomic units, zero pending transactions, complete 4,095 Sage offers all terminal, zero DB open MZ offers, inactive Bootstrap, and stopped prior campaign `c275b95327bd42fede7bca1b731a76ebbfebe13b84a0b083f51d25ab5cda7220` with zero authoritative fee spend. API safety was ALLOWED with an owned renewing lease, and the bot remained stopped. The UI showed zero active offers and kept Start locked pending settings review.
- Exact-PID/hash stopped-profile monitor `E:\catalyst-stability-monitor-a14b342-clean\monitor.ps1` began `2026-10-07T02:34:36.9698882Z`. Its first four one-minute samples were clean: expected process, safety allowed, lease owned, Sage synced, bot stopped and zero open offers. The 24-hour gate cannot pass before `2026-10-08T02:34:36Z` plus complete trace and end-state review.

Active-offer lifecycle/recovery, secondary original-profile exact-source acceptance, both final-candidate 24-hour windows, final review and release authorization remain open. No new TEST 7 campaign or fee scope has been approved. Keep PR #220 draft; do not merge, tag, release or claim public readiness.
