"""Update landing stats from live scrapers and write HTML to LANDING_DEST."""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from mahogany import config
from mahogany.config import LANDING_DEST, LANDING_SRC
from mahogany.jobs.costofliving_report import fetch_gas_prices
from mahogany.scrapers.listings import fetch_mahogany_listings

logger = logging.getLogger(__name__)


def update_stats(html: str, listings: list, gas: dict) -> str:
    """Replace live stats in the HTML. Skips listing stats if scraper returned nothing."""
    gas_price = gas.get("calgary", 165.2)
    gas_str = f"{gas_price:.0f}¢"

    html = re.sub(r"\d{3}¢(?:/L)?", gas_str, html)
    html = re.sub(r"\d{3}\.\d¢/L", f"{gas_price:.1f}¢/L", html)

    if not listings:
        logger.warning("Listings scraper returned 0 — keeping existing listing stats")
        return html

    prices = [l["price"] for l in listings if l.get("price")]
    if not prices:
        return html

    active = len(prices)
    med = sorted(prices)[len(prices) // 2]
    entry = min(prices)
    # naive "new this week" — listings with days_on_market <= 7 when present
    new_week = sum(1 for l in listings if (l.get("days_on_market") or 99) <= 7)

    html = re.sub(
        r'(id="stat-active"[^>]*>)(\d+)',
        rf"\g<1>{active}",
        html,
    )
    # fallback plain number replacements used by legacy template
    html = re.sub(r"(Active listings</[^>]+>\s*<[^>]+>)\d+", rf"\g<1>{active}", html, count=1, flags=re.I)
    return html


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    src = LANDING_SRC
    if not src.exists():
        raise SystemExit(f"Landing source missing: {src}")

    html = src.read_text(encoding="utf-8")
    listings = fetch_mahogany_listings()
    try:
        gas = fetch_gas_prices()
    except Exception as e:
        logger.warning("gas fetch failed: %s", e)
        gas = {}

    html = update_stats(html, listings, gas)
    # stamp
    html = re.sub(
        r"Updated [^<]+",
        f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        html,
        count=1,
    )

    dest = LANDING_DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.resolve() != src.resolve():
        dest.write_text(html, encoding="utf-8")
        logger.info("Wrote %s", dest)
    else:
        src.write_text(html, encoding="utf-8")
        logger.info("Updated %s in place", src)

    # Optional remote sync when DO_HOST set (no password in repo — use SSH keys)
    do_host = os.getenv("DO_HOST", "").strip()
    if do_host:
        remote = os.getenv("DO_LANDING_PATH", "/var/www/mahogany/index.html")
        user = os.getenv("DO_USER", "root")
        import subprocess

        subprocess.run(
            ["scp", str(dest if dest.exists() else src), f"{user}@{do_host}:{remote}"],
            check=True,
        )
        logger.info("scp → %s@%s:%s", user, do_host, remote)


if __name__ == "__main__":
    main()
