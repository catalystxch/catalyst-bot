# Bootstrap status stage-target wording

Source commit: `97dc12375d3b25b42171451daaff663809212216` on draft PR #261.

During original TEST 7 native UI acceptance, the campaign was active with a
10% first-stage allocation, but the bot was stopped and Sage and the CATalyst
database held zero open offers. The global and Dashboard banners said
`10% deployed`. `deployment_fraction` is the stage target used by the runtime
offer budget calculation; it is not an observation of live deployed offers.

The banner now says `10% stage target`. A Chromium regression using a durable
active campaign failed before this change because the banner still said
`deployed`, then passed afterward. The full Chromium smoke file passed **99**
tests. `git diff --check` passed.

A clean detached Windows build from this exact commit succeeded at
`C:\Users\t_you\.codex\worktrees\bootstrap-label-package\catalyst\dist\Catalyst\Catalyst.exe`
with SHA-256
`4D2FB1EF7560616297C7156BAB80A0D27EAEDD6E455368FAE7B7801D3DF2A0E5`.
The bundled `bot_gui.html` and source `bot_gui.html` both have SHA-256
`21366E1C4EAF10A514B15D03BF43859A228C4D6FB91D58EA7C09166ABE4B9AAB`.
Packaged API and mock Sage RPC worker smokes passed with isolated data and
ports. The detached build reports v1.4.0 because `build.py` synchronizes
release metadata from the checkout; it is a local smoke artifact, not a new
public or original-profile candidate.

The original TEST 7 profile continued running the previously verified
`512E7514E5D66522B0F6FDA17849DD3CC972E8FD5C731BBF65A9BF50C55221C9`
EXE throughout this work. Its bot remained stopped, Sage synced, lease owned,
and safety allowed with zero blockers. This wording fix has therefore not yet
been observed in the original-profile live EXE; the real-offer lifecycle and
other acceptance gates remain open.
