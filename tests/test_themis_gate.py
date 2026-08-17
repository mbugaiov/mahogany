"""Contract: gate.sh Themis builder prefers local checkout; CI fail-closed when missing."""
import os
import subprocess
from pathlib import Path

import pytest

GATE = Path("scripts/gate.sh").read_text()
ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / ".themis-agent" / "scripts" / "build_review_prompt.sh"


def test_prefers_local_themis_builder_before_clone():
    local = GATE.find(".themis-agent/scripts/build_review_prompt.sh")
    clone = GATE.find('git clone --depth 1 https://github.com/mbugaiov/themis-agent.git')
    assert local != -1
    assert clone != -1
    assert local < clone


def test_offline_local_skip_is_documented():
    assert "themis builder skipped (offline local)" in GATE
    assert "Offline local runs may skip" in GATE


def test_ci_fail_closed_when_builder_missing():
    assert "GITHUB_ACTIONS" in GATE
    assert "themis builder missing in CI" in GATE
    assert "exit 1" in GATE


def test_prints_themis_tip_when_builder_present():
    assert "print_themis_tip" in GATE
    assert "themis builder tip:" in GATE


@pytest.mark.skipif(
    not BUILDER.is_file(),
    reason="no local .themis-agent checkout (offline)",
)
def test_build_review_prompt_help_runs():
    result = subprocess.run(
        ["bash", str(BUILDER), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "build_review_prompt.sh" in result.stdout


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true" or not BUILDER.is_file(),
    reason="executed builder smoke only in CI with workflow checkout",
)
def test_build_review_prompt_emits_review_rules_in_ci():
    result = subprocess.run(
        [
            "bash",
            str(BUILDER),
            "--pr",
            "1",
            "--base",
            "origin/main",
            "--label",
            "mahogany-selftest",
            "--local-rule",
            ".cursor/rules/code-review.mdc",
            "--themis-root",
            str(BUILDER.parents[1]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "review-rules/10-tests-must-have" in result.stdout
