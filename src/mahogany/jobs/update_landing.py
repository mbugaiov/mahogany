"""Update landing stats from live scrapers and write HTML to LANDING_DEST."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from mahogany.config import LANDING_DEST, LANDING_SRC

logger = logging.getLogger(__name__)


def _fmt_price(n: int) -> str:
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M".replace(".00M", "M")
    return f"${n // 1000}k"


def update_stats(html: str, listings: list, gas: dict) -> str:
    """Patch elements with data-stat / known ids."""
    gas_price = gas.get("calgary")
    if gas_price is not None:
        gas_str = f"{float(gas_price):.0f}¢"
        html = re.sub(
            r'(id="stat-gas"[^>]*>)([^<]*)',
            rf"\g<1>{gas_str}",
            html,
            count=1,
        )
        html = re.sub(
            r'data-stat="gas">[^<]*',
            f'data-stat="gas">{gas_str}',
            html,
        )

    if not listings:
        logger.warning("Listings scraper returned 0 — keeping existing listing stats")
        return html

    prices = [int(l["price"]) for l in listings if l.get("price")]
    if not prices:
        return html

    active = len(prices)
    med = sorted(prices)[len(prices) // 2]
    entry = min(prices)
    new_week = sum(1 for l in listings if (l.get("days_on_market") or 99) <= 7)

    replacements = {
        "active": str(active),
        "median": _fmt_price(med),
        "entry": _fmt_price(entry),
        "new-week": str(new_week),
    }
    for key, val in replacements.items():
        html = re.sub(
            rf'(data-stat="{re.escape(key)}">)([^<]*)',
            rf"\g<1>{val}",
            html,
        )
        id_map = {
            "active": "stat-active",
            "median": "stat-median",
            "entry": "stat-entry",
            "new-week": "mkt-new",
        }
        eid = id_map.get(key)
        if eid:
            html = re.sub(
                rf'(id="{eid}"[^>]*>)([^<]*)',
                rf"\g<1>{val}",
                html,
                count=1,
            )
        if key == "active":
            html = re.sub(
                r'(id="mkt-active"[^>]*>)([^<]*)',
                rf"\g<1>{val}",
                html,
                count=1,
            )
        if key == "median":
            html = re.sub(
                r'(id="mkt-median"[^>]*>)([^<]*)',
                rf"\g<1>{val}",
                html,
                count=1,
            )

    return html


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from mahogany.jobs.costofliving_report import fetch_gas_prices
    from mahogany.scrapers.listings import fetch_mahogany_listings

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
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = re.sub(
        r"(Updated)[^<]*",
        rf"\1 {stamp}",
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

    do_host = os.getenv("DO_HOST", "").strip()
    if do_host:
        import subprocess

        remote = os.getenv("DO_LANDING_PATH", "/var/www/mahogany/index.html")
        user = os.getenv("DO_USER", "root")
        subprocess.run(
            ["scp", str(dest if dest.exists() else src), f"{user}@{do_host}:{remote}"],
            check=True,
        )
        logger.info("scp → %s@%s:%s", user, do_host, remote)


if __name__ == "__main__":
    main()
