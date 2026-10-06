# Sage quarantine ownership proof

Draft PR #220, source parent `f73a2bd85be1ba205542530ca3752b6feaa6c04e`.
This is a source-fix checkpoint; a new exact package and live acceptance are
pending.

The version-2 quarantine resolution path used an exact Sage coin read to check
selected inputs. Sage may omit the optional `owned` field from that response.
`_collect_sage_quarantine_absence_proof()` treated the omission as `True`, so
an otherwise complete exact-offer absence read could authorize release without
affirmative input ownership proof. The stability-kernel design requires both
offer absence and owned, unlocked inputs before clearing quarantine.

A focused regression kept the exact offer missing and coin unlocked, removed
the coin's `owned` field, and made the owned-wallet view unavailable. On the
parent source it failed as expected: the proof validator returned
`allowed=True` rather than denying release. The test did not use a live wallet.

The correction accepts an omitted `owned` field only when the exact coin ID
and amount are present in Sage's owned-only XCH or active CAT wallet view. An
explicit `owned=False` still denies release. The wallet identity is read again
after both the exact coin read and any owned-view reads, so an identity change
during collection invalidates the proof. Missing or failed owned-view reads
fail closed. The wallet IDs come from the selected Sage adapter, rather than
hard-coded defaults.

Independent review found a second gap before publication: Sage's owned view
can include offer-locked coins. A later owned-view offer lock or spent-height
contradiction now blocks release even when the earlier exact coin read looked
unlocked. Both cases were reproduced with red/green synthetic regressions.

The initial focused red/green regression passed after the ownership correction.
The affected recovery, Sage exact-evidence and offer-reconciliation suites
passed 399 tests on that initial fix. A local clean EXE was built from that
intermediate commit for isolated smokes only; it was superseded before artifact
publication or live use. Final affected and full Windows suites, final package,
and exact live acceptance remain pending. No wallet effect was initiated for
this finding.

The previous exact `f73a2bd` stopped-profile monitors remain live while the
new source is verified. Their results cannot count as a completed 24-hour
window for a later runtime candidate. PR #220 remains draft; active-offer
lifecycle, both exact-candidate 24-hour windows and final review remain open.
