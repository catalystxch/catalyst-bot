# CATalyst 13a842b primary acceptance package

Draft PR #220 exact source: `13a842b445a8f72dfa59d1078e8a6b48a0956d2f`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `0C3010C816D216A28FFE1AEA48F17BC7271F3EF9CABEEA4E9998CE344F52EE50` |
| Bundled `_internal/bot_gui.html` | `1FD778D4CC109562FF69942BD705D6CB107067017445C9B5E65E3514EC50A001` |
| `CATalyst-13a842b-primary-acceptance.zip` | `C83D499E483EC84D73252D714F3F7AFC49491E46A51363B7151BD78DC445DAAF` |
| `Catalyst-Setup-13a842b-1.4.0.exe` | `6B10695CEEB6954583FC0DDD807DDFD512EA2B69C431E0EDB908B682CE317F51` |

The Dashboard previously displayed only the clock time for a six-day-old RED
market-confidence snapshot and for provider observations. The browser
regression first failed with the old `15:29:15` output. Both timestamps now
include the local date and time; the RED confidence result and safety logic
remain unchanged. The focused regression and all 212 Chromium tests passed.
All 11 PR checks passed on this exact source.

The detached bundle passed packaged API, synthetic Sage RPC, and publication
recovery smokes. Its bundled HTML matched the source SHA-256. The ZIP passed
CRC and embedded EXE hash checks. A separate QA AppId installer installed
into an isolated E: directory; its EXE hash and installed API smoke passed,
and QA uninstall removed its directory and registration. Defender custom
scans of the bundle, ZIP, and unsigned installer returned no attributable
detections.

The previous exact `dfc53d9` app remains running with its bot stopped on the
original TEST 7 profile. Exact `13a842b` original-profile live acceptance, live wallet
lifecycle, both 24-hour windows, independent secondary acceptance, and final
review remain open. PR #220 stays draft.
