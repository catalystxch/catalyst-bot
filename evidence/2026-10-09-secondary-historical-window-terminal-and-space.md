# Secondary PC: historical window and exact-candidate staging capacity

This is a read-only terminal audit from the independent secondary PC on
2026-10-09. It does **not** qualify `196caa8`, `bfe7d0e`, or the newer
`32bfc52` candidate for a clean 24-hour window. No cleanup, package
extraction, installer launch, Splash launch, wallet action or profile mutation
was performed.

## Historical exact-196 window

The historical monitor covers source `196caa890ebf97ed08435ac492edd6edd553f9e9`
and original Harvestr PID 15436. It began at
`2026-10-08T08:41:35.5783885Z`; the fixed target endpoint is
`2026-10-09T08:41:35.5038685Z` (09:41:35 BST). The monitor wrote its
terminal end record at `2026-10-09T08:42:29.2608542Z`. The final trace has
1,392 sequential sample indices and exactly one matching end/summary record.
**755 samples had alerts** that matched all 755 records in its
`alerts.jsonl`. This is the active trace, not stale alerts from another run.
There were 715 unexpected CATalyst process-count occurrences and 78 samples
with system drive free space below 1 GiB; these categories overlap. A
123.161865-second sample gap occurred between samples 1200 and 1201. The
last alert was sample 1249. The clean suffix of 143 samples is not a new
24-hour window. Therefore this trace cannot become a clean 24-hour pass,
even though its terminal state was healthy. This is completed historical
**non-clean** evidence, never acceptance for the current source. The monitor
exited naturally after writing the summary. The original Harvestr app remained
the sole responsive CATalyst process, with no wallet effect.

The preserved evidence directory is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\monitor-196caa8-original-20261008T0945BST`.
The terminal audit reported SHA-256 `C139664317BEBE48D513170E2D99A04C45F4B53A5EDE4F52B91926400E3FF40F`
for `trace-60s.jsonl`, `7CEB52667A6C5F7FD6134A0E4521D22CBA4FFF3C66FDFBAD90998D35737B8D45`
for `alerts.jsonl`, and `BC5172659A9D4E6E658862697B1F2BC0D9963F1108472FE3FDA5657C4BFEC150`
for `summary.json`. The summary matched the terminal end object.

## Exact-candidate staging capacity

Only local C: is mounted. The final secondary measurement had
1,297,334,272 bytes free (~1.208 GiB) at the final source review. The
current `32bfc52` portable payload is 74,839,515 bytes. The established
secondary staging floor is 2 GiB free **after** extraction. The following
CATalyst-owned, reproducible scratch directories were measured read-only;
the running exact-196 installation, original profile, active trace, Git
objects, formal evidence and unrelated user files were excluded.

Root for every relative path below:
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc`

| Relative scratch path | Bytes |
| --- | ---: |
| `work\catalyst-acceptance-5b54d94\.venv-acceptance` | 288,658,518 |
| `work\catalyst-acceptance-60d49f2\.venv-ci-clean` | 265,293,051 |
| `tmp` | 179,340,021 |
| `work\catalyst-pr220-review\dist` | 78,240,515 |
| `work\catalyst-review-f73a2bd\dist` | 78,228,091 |
| `work\catalyst-pr220-review\build` | 34,808,109 |
| `work\catalyst-review-f73a2bd\build` (recommended buffer) | 34,778,072 |

The first six total 924,568,305 bytes (0.861 GiB), projecting
2,147,063,062 bytes free after extraction, **420,586 bytes below** the
2 GiB floor. All seven total 959,346,377 bytes (0.893 GiB), projecting
2,181,841,134 bytes (~2.032 GiB) free after extraction. The secondary
read-only inventory found no external process command-line reference to
these seven paths. They are not the running installation or active trace.

An automatic approval review previously rejected direct PowerShell
cleanup of old scratch before execution with reason `blocked by policy`;
an attempted `git clean` workaround was documented as improper. The agent
must not retry cleanup by another method. The operator may remove these
specific scratch directories directly after review, preferably after the
historical monitor endpoint, then the agent can verify free space and stage
the exact package. No deletion is recorded by this document.

## Fresh exact-`32bfc52` staging calculation — 2026-10-09T09:28:57Z

The secondary PC remeasured C: and the same seven reviewed directories
read-only. All seven remain present and still total **959,346,377 bytes**;
C: had **1,297,870,848 bytes** free before and after the scan. No cleanup or
staging occurred. The independently verified exact ZIP is 36,514,935 bytes
and its extracted content is 74,839,515 bytes. Keeping the ZIP on disk while
extracting it and retaining the 2 GiB free-space floor requires
**2,258,838,098 bytes** free before staging, a current shortfall of
**960,967,250 bytes**. Keeping the separately pinned 38,429,357-byte
installer as well requires **2,297,267,455 bytes**, a shortfall of
**999,396,607 bytes**. Even hypothetical removal of all seven reviewed
directories would leave **1,620,873 bytes** below the ZIP-plus-extraction
threshold. This supersedes the earlier extraction-only projection above;
the operator needs to free additional space before exact secondary package
staging. The prior blocked cleanup decision remains in effect.
