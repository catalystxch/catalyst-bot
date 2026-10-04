# CATalyst b7eab4f Windows acceptance artifacts

Draft PR #220 exact source: `b7eab4f263409c0b4c846d6a506b21e16335ee37`.
These are unsigned test artifacts, not a public release.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `9EB27A8DFCB15B026318F75B797B6FAD628A9D46AB44DFC49C9CE2F9AACF3C8A` |
| Bundled `_internal/bot_gui.html` | `1FD778D4CC109562FF69942BD705D6CB107067017445C9B5E65E3514EC50A001` |
| `CATalyst-b7eab4f-primary-acceptance.zip` | `D7E5066C33477A60A944EF6E2EB7A8FA4E2E583BC0CA58E44DC83584D533050D` |
| `Catalyst-Setup-b7eab4f-1.4.0.exe` | `4F68B683BB1FFE0D8495E5A546A29C08E71ED2310DD48C724C9670002C0E871B` |

The detached Windows build completed with 192 payload files. The ZIP passed
CRC and its embedded executable matched the detached build byte for byte.
Packaged API, synthetic Sage RPC, interrupted-publication recovery, and native
clean/duplicate/persisted/safety smokes passed in isolated profiles. A
separate QA AppId installer installed to an isolated E: directory; the
installed EXE hash and packaged API matched, then silent uninstall removed
its executable and HKCU registration. Microsoft Defender custom scans of
the bundle, ZIP and public unsigned installer added zero detections.

The full exact-source local Windows backend suite passed 7,197 tests,
skipped 213, and passed 431 subtests. The frontend payload is byte-identical
to the previous 212-pass Chromium candidate. CI and original-profile live
acceptance are tracked separately in the PR evidence; their completion is
not implied by this artifact manifest.
