"""CLI entry: mahogany <job> [args...]"""

from __future__ import annotations

import importlib
import sys

JOBS = {
    "news": "mahogany.jobs.news",
    "group-bot": "mahogany.jobs.group_bot",
    "market": "mahogany.jobs.market_report",
    "listings": "mahogany.jobs.listings_bot",
    "rentals": "mahogany.jobs.rentals_bot",
    "rentals-report": "mahogany.jobs.rentals_report",
    "weather": "mahogany.jobs.weather_report",
    "cost-of-living": "mahogany.jobs.costofliving_report",
    "deals": "mahogany.jobs.deals_bot",
    "insider": "mahogany.jobs.insider_bot",
    "hoa": "mahogany.jobs.hoa_bot",
    "instagram": "mahogany.jobs.instagram_bot",
    "landing": "mahogany.jobs.update_landing",
}


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage: mahogany <job> [args...]\nJobs:", ", ".join(sorted(JOBS)))
        raise SystemExit(0 if argv else 1)
    job = argv[0]
    if job not in JOBS:
        print(f"Unknown job: {job}\nKnown: {', '.join(sorted(JOBS))}", file=sys.stderr)
        raise SystemExit(2)
    mod = importlib.import_module(JOBS[job])
    sys.argv = [job, *argv[1:]]
    if hasattr(mod, "main"):
        mod.main()
    else:
        raise SystemExit(f"{JOBS[job]} has no main()")


if __name__ == "__main__":
    main()
