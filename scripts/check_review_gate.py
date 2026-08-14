#!/usr/bin/env python3
"""Fail when Themis review.md has blocking issues."""

from __future__ import annotations

import sys
from pathlib import Path

from mahogany.review_gate import extract_blocking_section, review_has_blockers


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "review.md")
    text = path.read_text(encoding="utf-8")
    if review_has_blockers(text):
        section = extract_blocking_section(text)
        print("Review gate FAILED — blocking issues found:", file=sys.stderr)
        if section:
            print(section, file=sys.stderr)
        raise SystemExit(1)
    print("Review gate: pass")


if __name__ == "__main__":
    main()
