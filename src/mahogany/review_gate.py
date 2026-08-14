"""Parse Themis review output for blocking issues. Pure — no I/O."""

from __future__ import annotations

import re

LGTM = re.compile(r"^LGTM - no blocking issues found\.?\s*$", re.I)
NO_OUTPUT = re.compile(
    r"^Cursor review produced no output \(see build log above\)\.\s*$", re.I
)


def extract_blocking_section(text: str) -> str | None:
    lines = text.splitlines()
    in_section = False
    body: list[str] = []
    for line in lines:
        if re.match(r"^## Blocking issues\s*$", line, re.I):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            body.append(line)
    if not in_section:
        return None
    return "\n".join(body).strip()


def review_has_blockers(text: str) -> bool:
    trimmed = text.strip()
    if not trimmed:
        return True
    if "\n" not in trimmed and LGTM.match(trimmed):
        return False
    if NO_OUTPUT.match(trimmed):
        return True
    section = extract_blocking_section(text)
    if section is None:
        return True
    if re.match(r"^None\.?\s*$", section, re.I):
        return False
    if not section:
        return True
    return True
