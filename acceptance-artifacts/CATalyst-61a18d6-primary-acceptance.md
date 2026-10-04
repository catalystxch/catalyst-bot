# CATalyst 61a18d6 primary acceptance package

Draft PR #220 exact source: `61a18d661e1e38a24dc0b5893e59d0f53d12e03d`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `909E569FA59D077E594757E64B5CC6F3D47DD9CE67369EF6870DADD8A8BF274D` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-61a18d6-primary-acceptance.zip` | `631BB97054378353C5279CB5C03E393A0BA53188303749115A09D79AA92CC1F0` |
| `Catalyst-Setup-61a18d6-1.4.0.exe` | `8E6C8320EBAF5AD190443896F7F2008B7FB694ACEEE05B596F277A411A4DB499` |

The source traps keyboard focus inside the Splash and Spacescan setup gates.
Two browser regressions failed before the correction and passed afterward;
the full Chromium suite passed 211 tests. The 192-entry ZIP passed CRC and
extracted API. The bundle passed packaged API, synthetic Sage RPC,
publication recovery, and native clean, duplicate, persisted and safety
smokes. A unique-AppId current-user QA installer passed clean install,
installed EXE hash/API/Sage, same-version reinstall and uninstall. Its QA
directory and registration were absent afterward. Defender custom scans
reported no matching detections. Independent HTTP downloads of the pinned
ZIP and installer matched the table hashes. Exact-source PR CI was still
running when this manifest was written.

The original TEST 7 app remains the older stopped `a3b299c` package. This
new package has not run against the original live profile. No wallet effect
was made. Live wallet lifecycle, complete native UI, both 24-hour windows,
independent secondary acceptance and final review remain open. PR #220 stays
draft.
