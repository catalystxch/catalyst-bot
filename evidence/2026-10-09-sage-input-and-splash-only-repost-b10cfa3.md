# Sage selected input and Splash-only restart repost

Status: exact runtime/source `b10cfa3dfec4a91cfe5fbf2075a23a3c9574b03e` passed local source and isolated package verification. Exact-source PR CI and live acceptance remain open at this checkpoint. No public beta is deployed.

## Defects and corrections

- Secondary immutable-source review found that successful Sage offer creation could be finalized as `created/CONFIRMED` when locked-input verification returned no proof of the selected maker coin, or showed only a different coin. The previous path could then project and publish an offer without exact selected-coin proof. A two-case regression was red on the preceding source. The corrected path records `creation_unknown/UNKNOWN`, retains the selected coin reservation, trips runtime safety, and requires reconciliation. It does not create an open DB offer or publication outbox row.
- Secondary review also found that the restart visibility worker was gated entirely by `DEXIE_AUTO_POST`. With Dexie disabled and optional Splash enabled, live Sage offers were never queued for Splash rebroadcast after restart. A regression was red on the preceding source. The corrected startup and background worker gates accept either publisher, and the Splash-only path uses a fresh Sage offer book, queues and flushes Splash, and makes no Dexie queue or flush call. Cached Sage results still block either publisher.

## Verification so far

- The two affected local suites passed **198 tests** after correcting a pre-existing race fixture to report the coin actually selected by its winning thread. Changed-file Ruff, format, and `git diff --check` passed.
- Exact-source isolated Chromium passed **258 tests** with exit code zero in 200.85 seconds. The complete serial Windows backend passed **7,533 tests, 259 skipped, and 455 subtests** with exit code zero in 30m59s. The full backend log is `E:\catalyst-pr220-f544-local-full-backend.log`; the Chromium log is `E:\catalyst-pr220-f544-local-browser.log`.
- Clean detached checkout `C:\catalyst\.superpowers\pr220-b10-package` was at `b10cfa3` before packaging. `python build.py` passed; its release-metadata step generated `_version.py` at `1.4.0` in that package checkout. The bundled UI SHA-256 is `8D27EB3D7B822B8EDA0ADEA8F6C4675F5680C1F03A17EEAE55BB64236C20D8CB`.
- Clean Windows EXE SHA-256: `9E8429523CCF725DF3950FF305E50AC22AEA69474090FEFD958B3A609A0E0DD4`. The 192-entry ZIP SHA-256 is `159F9F0D81C0984CCDCB2F1024D55B5E25552805BC01AC1BAE5A2F9E8864E052`; CRC, unique paths, `Catalyst/` containment, and embedded EXE hash passed. The unsigned production installer SHA-256 is `9B70FA0E9A9185CF4CA6CBF9E251C84F6B89C497E659BB6FE52DD6F3DE7206CE`.
- Packaged API, synthetic Sage RPC worker, upgrade publication recovery, and isolated native clean/duplicate/persisted/safety smokes passed. The extracted ZIP EXE matched the clean EXE hash and passed packaged API and synthetic Sage RPC smokes.
- A QA installer compiled with isolated AppId `{F52CFA87-CC4E-4766-9C72-4FC8CDFD7FB6}` installed to `C:\catalyst\.superpowers\pr220-b10-qa-install`. Its installed EXE matched the clean EXE hash and passed packaged API and synthetic Sage RPC smokes. The isolated uninstaller exited zero and removed its target directory and registration.
- Defender custom scans of the bundle, ZIP, and unsigned installer completed with zero detections for this candidate.

## Open acceptance

Exact PR CI, independent secondary runtime acceptance, Splash receipt by a distinct peer, original-profile active-offer lifecycle and recovery, full native UI, both exact-candidate 24-hour stability windows, and final review remain open. The older `ce3ba7a` stopped-profile monitor is clean while in progress, but cannot credit the `b10cfa3` final-candidate window. No new TEST 7 campaign or network-fee approval has been received; no wallet effect was made for this correction. PR #220 and website PR #89 remain draft.
