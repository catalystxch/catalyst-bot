# PR #220 code-scanning triage, 2026-10-08

This is a scoped review checkpoint for draft PR #220, not a final security
review or public-readiness approval. The reviewed branch head was
`c3553c37d025e91b3714abbd0315d1f930eb9f3d`; its runtime/source is
`7ce8ffafef3ac8e14c269348c5285a2e268e2734`.

At 03:53 UTC, `gh pr checks 220` reported all 11 checks successful. The
GitHub code-scanning API returned no open alerts filtered to
`refs/heads/codex/coin-prep-fee-approval`. An unfiltered repository query
returned 13 open alerts whose latest instances were all on
`refs/heads/main` at `bfa25b6eac12faa4585dcf6c710ad63278431509`.
This branch-filter result does not prove that all inherited main-branch
findings are harmless.

Focused source review compared the main-branch DOM alerts 80–84 and URL
scheme alert 79 with the current PR code. The current Smart Settings result
uses `resultTitle.textContent` and `resultBody.textContent`, instead of the
main-branch `innerHTML` result sink. The current external-link handlers parse
with `new URL(...)` and accept only `http:` or `https:` using a full protocol
check. The older PR-head CodeQL exception comment at alert 91 points to a
superseded commit; the current Bootstrap `_error` handler returns fixed public
codes and logs only the exception type for unexpected failures. These are
limited source checks, not proof of every data-flow or security property.

The main-branch Sage path and other exception alerts were not fully triaged in
this pass. The complete PR diff is large, and final independent code review,
original-profile live lifecycle/recovery, secondary exact-candidate
acceptance, and both final-candidate 24-hour windows remain open. PR #220
must stay draft; no merge, tag, release, or public-readiness claim follows
from this checkpoint.
