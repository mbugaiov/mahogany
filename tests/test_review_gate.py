from mahogany.review_gate import review_has_blockers


def test_lgtm_passes():
    assert not review_has_blockers("LGTM - no blocking issues found.")


def test_none_blocking_passes():
    text = "## Summary\nx\n\n## Blocking issues\nNone.\n\n## Risks\nNone.\n\n## Nits\nNone.\n"
    assert not review_has_blockers(text)


def test_blocking_fails():
    text = "## Summary\nx\n\n## Blocking issues\n- secret in repo\n\n## Risks\nNone.\n"
    assert review_has_blockers(text)


def test_empty_fails():
    assert review_has_blockers("")
