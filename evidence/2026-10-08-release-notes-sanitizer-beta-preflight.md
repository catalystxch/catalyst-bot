# Unsigned beta release-notes sanitizer preflight

This is release-tooling evidence for draft PR #220. The packaged desktop runtime remains exact source `085ef6522fc5b4989f8d9a7380cbd08da1696e43`; this change touches only `scripts/sanitize_release_notes.py`, its test, and acceptance documentation.

The staged v1.4.0 Dexie-only beta notes included a link to the source repository's issue form at `/issues/new/choose`. Running the existing sanitizer removed that URL but left the malformed fragment `[CATalyst issue forms](`. The root cause was the Markdown-link pattern matching only numeric pull and issue paths; the later raw-URL removal consumed the unmatched URL inside the link.

A new regression in `tests/test_sanitize_release_notes.py` reproduced the malformed output before the fix. The sanitizer now removes any Markdown link to a path under the configured source repository while preserving its visible label. The same staged notes now produce readable Markdown, preserving the independent beta-guide link. Focused tests passed **2/2** after the red run; Ruff check/format passed. The complete serial Windows backend suite passed **7,436 tests, 246 skipped, and 455 subtests** in 20 minutes 23 seconds. Log: `E:\catalyst-release-notes-sanitize-full-pytest.log`.

The staged `Catalyst-Setup-v1.4.0.exe` and SHA-256 sidecar were also used in a local manifest dry run with the corrected sanitized notes. The installer digest matched, the draft notes appeared without malformed Markdown, and an ephemeral Ed25519 signature verified over the canonical manifest bytes. The ephemeral key was not written to disk or used for production publication.

This preflight did not create a tag, GitHub release, update-channel release, or website deployment. The unsigned-beta workflow currently publishes the release-channel asset as `--latest` while the manifest names its channel `stable`; the effect on existing installations is under separate final review. Exact-candidate original-profile live tests, both 24-hour windows, active-offer lifecycle/recovery, and final release decision remain open.
