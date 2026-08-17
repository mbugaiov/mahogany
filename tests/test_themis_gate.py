"""Contract: gate.sh Themis builder prefers local checkout and skips offline clone."""
from pathlib import Path

GATE = Path("scripts/gate.sh").read_text()


def test_prefers_local_themis_builder_before_clone():
    local = GATE.find(".themis-agent/scripts/build_review_prompt.sh")
    clone = GATE.find("git clone")
    assert local != -1
    assert clone != -1
    assert local < clone


def test_clone_failure_skips_instead_of_failing_gate():
    assert "themis builder skipped (offline)" in GATE
    assert "if git clone" in GATE
