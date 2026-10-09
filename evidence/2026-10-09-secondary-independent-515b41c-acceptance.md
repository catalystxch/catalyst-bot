# CATalyst 515b41c Secondary Independent Isolated Acceptance

Date: 2026-10-09 (Europe/London)

Scope: source identity, focused isolated source/browser verification, pinned package integrity, static package safety, and Microsoft Defender scan. This is not original-profile live acceptance. The packaged application and installer were not launched because the handoff prohibited starting another wallet writer and the existing monitored applications had to remain untouched.

## Source identity

- Remote branch: `codex/coin-prep-fee-approval`
- Remote/source HEAD: `515b41c200fb506594225be498b099b0dbe6c03d`
- Parent: `bae610af28d76627c2013e7b58d17e310b5e674a`
- Detached checkout HEAD: `515b41c200fb506594225be498b099b0dbe6c03d`
- Worktree clean: yes
- Parent-to-HEAD delta: only `src/catalyst/config.py`, one line changed so dormant non-beta `SPLASH_RECEIVE_ENABLED` defaults from `true` to `false`

## Pinned artifacts

- Artifact commit: `893001a24076e250a66c597488d99fbc2638637f`
- ZIP bytes: `37,373,890`
- ZIP SHA-256: `B8C6067FFEE736D986A05E0C0EDAD910528FE73746CB452B2D04DCC7CBEE0570` (match)
- Installer bytes: `38,428,383`
- Installer SHA-256: `68A683BFDE99B77C112A949431088945DF21C9CF733AAA56F5A59841D2254879` (match)
- Installer Authenticode: `NotSigned` (expected unsigned beta installer)
- ZIP CRC: all `192` entries passed (`zipfile.testzip()` returned no bad entry)
- ZIP paths: zero unsafe traversal/absolute paths, zero case-fold duplicates, zero encrypted entries, zero symlinks
- ZIP uncompressed bytes: `74,838,320`; compressed bytes: `37,340,234`; ratio: `2.004`
- Extracted EXE bytes: `11,306,685`
- Extracted EXE SHA-256: `D8FC061FD883ABB268F03A93CDB4B0B4631906043E95588CAAB0F6902A5A0238` (match)
- Extracted EXE Authenticode: `NotSigned`
- EXE file version: `1.4.0.0`; product version: `1.4.0`
- Bundled UI bytes: `2,217,374`
- Bundled UI SHA-256: `F355EF52EA22F1E5F6FAAD872FD6051AB46BE700522F9795832414B63C25EE88` (match)

## Independent tests

- `python scripts/check_env_example.py`: passed; `.env.example` matches `config.py` defaults for `102` keys
- Ruff on corrected config and focused Splash/Dexie tests: passed
- Focused backend: `74 passed in 2.43s`
  - `tests/test_dexie_only_beta.py`
  - `tests/test_plan_04_22_splash_settings.py`
  - `tests/test_splash_runtime_paths.py`
- Focused Chromium: `100 passed in 69.46s`
  - `tests/e2e/test_dexie_only_beta.py`
  - `tests/e2e/test_smoke.py`
- Microsoft Defender custom scan: completed with `0` new detections
  - Engine: `1.1.26080.3`
  - Signatures: `1.459.629.0`, updated `2026-10-08T16:41:35Z`

## Capacity and safety limits

- Final verification C: free space: `2,064,932,864` bytes (`1.923118591 GiB`)
- The full `7,490`-test backend suite was not rerun on this secondary PC because capacity was below 2 GiB after retaining both required final artifacts and extracted evidence. The primary's full-suite result is not claimed as independently reproduced here.
- The installer was not installed and the packaged EXE was not launched. Doing so would violate the explicit prohibition on starting another wallet writer while three existing CATalyst applications and their monitors were active.
- Existing monitored PIDs `15436`, `17212`, `16960`, `3788`, `8956`, and `21376` remained alive. No original profile, Sage wallet, campaign, fee approval, offer, or wallet state was touched.

## Result

PASS for the independently executed isolated scope: exact source and package identity, ZIP integrity, embedded EXE/UI identity, focused backend and Chromium behavior, static package safety, and Defender scan. Original-profile live acceptance and packaged runtime/API/native startup are explicitly not covered by this secondary result.
