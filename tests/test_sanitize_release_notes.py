from scripts.sanitize_release_notes import sanitize_release_notes


def test_sanitize_release_notes_removes_private_repo_links():
    notes = """## What's Changed
* Use signed public update manifest by @Lowestofttim in https://github.com/catalystxch/catalyst-bot/pull/42
* Polish [upgrade modal](https://github.com/catalystxch/catalyst-bot/pull/41)

**Full Changelog**: https://github.com/catalystxch/catalyst-bot/compare/v1.2.7...v1.2.8
"""

    cleaned = sanitize_release_notes(notes, "catalystxch/catalyst-bot")

    assert "github.com/catalystxch/catalyst-bot" not in cleaned
    assert "Full Changelog" not in cleaned
    assert "* Use signed public update manifest by @Lowestofttim" in cleaned
    assert "* Polish upgrade modal" in cleaned


def test_sanitize_release_notes_keeps_label_for_private_issue_form_link():
    notes = (
        "Report defects through the "
        "[CATalyst issue forms](https://github.com/catalystxch/catalyst-bot/issues/new/choose). "
        "Read the [beta guide](https://catalystxch.com/beta-guide.html)."
    )

    cleaned = sanitize_release_notes(notes, "catalystxch/catalyst-bot")

    assert cleaned == (
        "Report defects through the CATalyst issue forms. "
        "Read the [beta guide](https://catalystxch.com/beta-guide.html)."
    )


def test_sanitize_release_notes_keeps_label_for_repo_root_link():
    notes = "Read [source](https://github.com/catalystxch/catalyst-bot/) before testing."

    cleaned = sanitize_release_notes(notes, "catalystxch/catalyst-bot")

    assert cleaned == "Read source before testing."
