# Incomplete stop visibility and retry — 2026-10-09

## Defect and fix

Exact runtime and package source: `05341035a778a5a4e9680e74ba10dea8c14dde1f` on draft PR #220. When a stop finalizer failed after a transient Splash shutdown timeout, `BotLoop` correctly retained `status=stopping`, but the dashboard's `/api/status` polling omitted that status. The UI inferred `stopped` from `running=false`, hid the unfinished stop, and disabled the only retry control. The status endpoint now carries the exact state and a retry flag. The dashboard enables **Retry Stop** only after the failed finalizer has exited; Start remains disabled until stop completion. An active finalizer still blocks a duplicate stop request.

The regression tests were observed failing before the implementation. The focused bot-stop, API-status, and Chromium dashboard tests then passed after the fix.

## Exact Windows verification

- Full serial Windows backend: **7,563 passed, 261 skipped, 455 subtests passed** in 1,272.97 seconds.
- Complete Chromium suite: **260 passed** in 152.01 seconds.
- Changed-file Ruff check and format check, plus `git diff --check`, passed.
- All **11 PR #220 checks** passed on the exact runtime commit, including CI unit tests, lint, and security analysis.
- Clean detached PyInstaller build at the exact source passed its post-build checks. Packaged API with isolated mock Sage, publication recovery, and native clean/duplicate/persisted/safety smokes passed.
- Acceptance ZIP contains all 192 bundle files, has no unsafe or duplicate paths, passes CRC, and embeds executable and UI bytes matching the clean build. Its extracted executable passed the isolated packaged API/mock Sage smoke.
- Production 1.4.0 installer compiled unsigned. A separate unique-AppId current-user QA variant passed isolated install, installed API/mock Sage smoke, byte comparison of all 192 bundle files, and uninstall. Its QA registration and shortcuts were removed; the unrelated pre-existing QA registration remained.
- Windows Defender custom scans of the EXE, ZIP, and installer completed with zero detections tied to this candidate.
- ZIP, installer, and manifest were fetched independently by HTTP at the immutable artifact commit; downloaded ZIP and installer hashes matched the local files.
- Independent secondary PC acceptance at the exact source passed 54 changed-backend regressions and four subtests, changed-file Ruff, three explicit Chromium stop-state cases, a separate clean Windows build, packaged API/mock Sage RPC, publication recovery, and native clean/duplicate/persisted/safety smokes. Its EXE SHA-256 is `1FCF9D93DE9C07401D79C29819D08CDDD42FFE2F1F8C7B0023B672BF1D5DC361`; the different PyInstaller output does not establish reproducible binaries. The secondary `60eed8c` synthetic canary remained continuous and alert-free through sample 48 with no real wallet/profile mutation. The secondary result is recorded at `acceptance-05341035-secondary-20261009T1935BST/SECONDARY-ACCEPTANCE.md` on that PC (evidence SHA-256 `495E8680EE9D6F5BFAB512DA3875861A59C8C29503D8193BB95F21844637B70E`).

| Artifact | SHA-256 |
| --- | --- |
| `Catalyst.exe` | `94A1A2C31F241EF00EC1DEA3D2DC5229EAF6639B4B1CBB8C108AD79FFEAA0217` |
| Bundled `bot_gui.html` | `125FCB4CE9B68B4363C8E227ED29FDD6604CE6559A0950ABF16783AB03DBCA4B` |
| [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d21fe3cc8fcf6d5fd7de5e5919fe7d913c11d1f8/acceptance-artifacts/CATalyst-0534103-primary-acceptance.zip) | `FCEDFF9166908C48D0CD36F4D741DEEEA00ACAA4B0F44923B36B3CBD04CF447B` |
| [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/d21fe3cc8fcf6d5fd7de5e5919fe7d913c11d1f8/acceptance-artifacts/Catalyst-Setup-0534103-1.4.0.exe) | `A5E8F145D938B5FA76A50BA1745278F17C3B9A97B172B6350F3392273A487CAF` |

## Acceptance still open

The original TEST7 profile and the secondary synthetic canary are still running the prior `60eed8c` executable. Their monitor samples are historical for this new source. Exact `0534103` primary and secondary original-profile live acceptance, active-offer lifecycle and recovery, complete native UI, both 24-hour stability windows, final review, and website beta deployment remain open. There is no new campaign or network-fee approval. PR #220 and website PR #89 remain draft; no merge, tag, release, or public-readiness claim has been made.
