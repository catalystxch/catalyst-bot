# Native Windows operator result — 24 September 2026

The operator ran the command in `2026-09-23-review-fix-native-check.md`
against `candidate-review-fixes-dns-20260923/dist/Catalyst/Catalyst.exe`
and returned this final output in the conversation:

```text
Packaged clean, duplicate, persisted, and native safety launches passed
```

The named helper tests clean first launch, duplicate-window handoff,
persisted-profile relaunch and malformed-identity native safety fallback,
using temporary application data and separate localhost ports. This is an
**operator-reported pass**, not an assistant-observed or independently rerun
native test. The native-launch handoff is satisfied; do not ask the operator
to repeat it without a new reason.

The artifact is the existing isolated candidate, runtime-equivalent to
`bc7203d8f1c8ce29e6bb9fab8980422c6688d0ba`. Its previously verified executable
SHA-256 is
`703E707F74977FEE071C93B0940FBEE665446C3620782B393A72DF229C990223`.
The operator output did not separately include a new hash measurement.
A subsequent assistant read-only SHA-256 check confirmed that the executable
at this path still matches the recorded hash. A GET of
`http://127.0.0.1:5000/api/status` was refused because there was no listener;
no live runtime identity or acceptance state was obtained from that attempt.

This receipt does not prove live wallet identity, fee approval, Coin Prep,
publication, fill/requote, active cancellation, remake or live restart
accounting. Those current-candidate acceptance gates remain open. No live
campaign, wallet mutation, installed-package replacement, push, main merge
or release is implied. The goal tool currently returns no registered goal
in this thread; no new goal was created solely from this test receipt.
