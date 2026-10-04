# Doctor diagnostics disclosure correction and exact eb8df03 package

Draft PR #220 exact source/runtime commit:
`eb8df039948d350a77884b65cce8ec39f2b83824`.

## Observed defect and root cause

On the exact prior `61a18d6` TEST 7 package, Logs → Run Doctor displayed
`Splash unreachable` followed by the raw `requests` connection exception,
including `HTTPConnectionPool`, `localhost:4000`, an internal object address,
and WinError 10061. `doctor.py` interpolated exceptions into ten public
`DoctorCheck.message` fields; `DoctorReport.to_dict()` passed those messages
unchanged to `/api/doctor` and the UI. A malformed configured provider URL
was also included verbatim in `config_validator.py` issues consumed by Doctor
and `/api/config/validate`. These paths could echo credentials or query tokens.

Three Doctor regression cases for database, Dexie and Splash error details
failed before the change. A four-setting invalid URL regression also failed
for Sage, Chia, Dexie and TibetSwap URL settings. The correction returns
bounded check messages without raw exception text and names invalid URL
settings without echoing configured values. Check status and severity remain
unchanged. Focused verification passed **38 tests and four subtests**; Ruff
check, Ruff format and `git diff --check` passed. The complete Windows
backend suite passed **7,181 tests, 212 skipped and 431 subtests** using four
workers in 422.72 seconds. All 11 PR checks passed on the exact source commit.
The frontend is unchanged from `61a18d6`, whose complete Chromium suite
passed 211 tests.

## Clean package and isolated validation

The detached build checkout at `E:\catalyst-doctor-eb8df03-build` was created
from the exact source commit before `python build.py`.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `4272D43DEC7358890418BB80AC417810B41C5708ED05E264B0A98D90FC5003E5` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-eb8df03-primary-acceptance.zip` | `FEEA5414BB484D89605E3D58FD366E7E922C946238F634F015E24C79F83981F6` |
| Unsigned `Catalyst-Setup-eb8df03-1.4.0.exe` | `81BC76D4E2FF6455C329B74D3B4838530663CF770F42533681EC7CBDC2BB007B` |

The 206-entry ZIP passed CRC. The exact bundle passed packaged API,
synthetic Sage RPC and interrupted-publication recovery smokes. A separate
unique-AppId current-user QA installer (`3C2CB931-419B-452F-849E-014B9EAD1F76`)
installed only to `E:\catalyst-doctor-eb8df03-qa-install`; its installed EXE
hash matched the table and installed API smoke passed. The QA uninstaller
exited zero; its directory and registration were absent afterward. Defender
custom scans of the bundle, ZIP and public unsigned installer completed with
no matching detections. The original TEST 7 process/profile was not used by
these isolated checks.

The ZIP and installer are pinned at artifact commit
`b003f17abcf7659786ce3bdc19802f8d31ac4e27`. Independent HTTP downloads
of both pinned files matched the table hashes:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/b003f17abcf7659786ce3bdc19802f8d31ac4e27/acceptance-artifacts/CATalyst-eb8df03-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/b003f17abcf7659786ce3bdc19802f8d31ac4e27/acceptance-artifacts/Catalyst-Setup-eb8df03-1.4.0.exe)

## Original TEST 7 read-only retest

The stopped `61a18d6` process was shut down through its visible browser UI
with the offer-cancellation checkbox unchecked. Its process and port 5000
listener exited. The exact `eb8df03` EXE then started against the original
profile. At the read-only checkpoint it was the sole `Catalyst.exe` process
(PID 53032) and sole 127.0.0.1:5000 listener owner; path and hash matched the
clean package. PID must be rediscovered before future action.

Visible browser startup acknowledged Risk Disclosure under the operator's
standing test authorization, selected Sage TEST 7 fingerprint `736588221`,
skipped the stopped optional Splash node and continued with the configured
Spacescan key. The browser selected MZ/XCH. API/UI checks found mainnet,
CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
stopped bot, XCH `138.470301476875`, MZ `780212.284`, zero open offers,
ALLOWED safety and zero blockers. On-demand Doctor returned nine passes and
one expected Splash warning. Its API message and visible Logs → Doctor modal
both read only **“Splash unreachable”**, without the prior raw exception.
The visible modal snapshot is
`.playwright-cli/page-2026-10-04T13-55-29-937Z.yml` in the primary worktree.
After closing the browser, the process/hash/port, stopped bot, balances,
zero open offers and ALLOWED safety were unchanged. No campaign, fee approval,
offer or wallet transaction was made.

The secondary PC was assigned an independent exact-package read-only check.
Its result, full native UI acceptance, live wallet lifecycle, both 24-hour
windows and final review remain open. PR #220 stays draft; no main merge,
tag, release or public-readiness claim.
