"""
listings_bot.py — Monitor Mahogany real estate listings and post new ones.

Run manually:  python3 listings_bot.py --post N   (post N recent listings)
Run as cron:   python3 listings_bot.py             (post new listings since last run)
"""

import argparse
import logging
import os
import sys
import time
import io
from pathlib import Path

import requests
from dotenv import load_dotenv

from mahogany import config  # noqa: F401 — loads .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from mahogany.scrapers.listings import fetch_mahogany_listings, get_new_listings, mark_listings_seen

TOKEN              = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID           = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
REALESTATE_THREAD  = os.getenv("REALESTATE_THREAD_ID", "56")
API_BASE           = f"https://api.telegram.org/bot{TOKEN}"

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _type_emoji(prop_type: str) -> str:
    mapping = {
        "House": "🏠", "Condo": "🏢", "Townhouse": "🏘",
        "Semi-Detached": "🏡", "Duplex": "🏗", "Vacant Land": "🌿",
    }
    return mapping.get(prop_type, "🏡")


def format_listing(listing: dict) -> str:
    """Format a listing as a beautiful Telegram HTML post."""
    t = _type_emoji(listing["type"])
    price    = f"${listing['price']:,}" if listing["price"] else "Price N/A"
    address  = listing["address"]
    beds     = listing.get("beds", 0)
    baths    = listing.get("baths", 0)
    sqft     = listing.get("sqft")
    dom      = listing.get("days_on_market", 0)
    url      = listing["url"]
    desc     = listing.get("description", "")[:200]
    prop_type = listing.get("type", "Home")

    # Days badge
    if dom == 0:
        badge = "🆕 <b>NEW TODAY</b>"
    elif dom <= 3:
        badge = f"🔥 <b>NEW — {dom}d ago</b>"
    elif dom <= 7:
        badge = f"📅 Listed {dom} days ago"
    else:
        badge = f"📅 {dom} days on market"

    # Stats line
    stats = []
    if beds:
        stats.append(f"{beds} 🛏")
    if baths:
        stats.append(f"{baths} 🚿")
    if sqft:
        stats.append(f"{sqft:,} sqft")
    stats_line = "  ·  ".join(stats) if stats else ""

    text = (
        f"{t} <b>{address}</b>\n"
        f"\n"
        f"💰 <b>{price}</b>  {f'· {stats_line}' if stats_line else ''}\n"
        f"{prop_type}  ·  {badge}\n"
    )

    if desc:
        text += f"\n{desc}…\n"

    text += (
        f"\n"
        f"🔗 <a href='{url}'>View on Zolo.ca</a>\n"
        f"\n"
        f"#MahoganyRealEstate #Calgary #MahoganyCalgary #YYC #CalgaryHomes"
    )

    return text


def _download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS_HTTP, timeout=15)
        if r.ok and "image" in r.headers.get("Content-Type", ""):
            if len(r.content) < 10 * 1024 * 1024:
                return r.content
    except Exception as e:
        logger.debug(f"Image download failed: {e}")
    return None


def post_listing(listing: dict) -> bool:
    """Post a listing to the Real Estate thread. Returns True on success."""
    text = format_listing(listing)
    img_bytes = _download_image(listing.get("image_url"))

    if img_bytes:
        # Post as photo
        resp = requests.post(
            f"{API_BASE}/sendPhoto",
            data={
                "chat_id":           GROUP_ID,
                "message_thread_id": REALESTATE_THREAD,
                "caption":           text[:1020],
                "parse_mode":        "HTML",
            },
            files={"photo": ("listing.jpg", io.BytesIO(img_bytes), "image/jpeg")},
            timeout=30,
        )
    else:
        # Text only
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id":           GROUP_ID,
                "message_thread_id": REALESTATE_THREAD,
                "text":              text[:4000],
                "parse_mode":        "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )

    result = resp.json()
    ok = result.get("ok", False)
    if ok:
        msg_id = result.get("result", {}).get("message_id", "?")
        logger.info(f"✅ Posted: {listing['address']} ${listing['price']:,} → msg_id={msg_id}")
    else:
        logger.warning(f"❌ Failed: {result.get('description', '')}")
    return ok


def post_separator(title: str = ""):
    """Post a section header to the Real Estate thread."""
    text = f"━━━━━━━━━━━━━━━━━━━━\n{title}" if title else "━━━━━━━━━━━━━━━━━━━━"
    requests.post(f"{API_BASE}/sendMessage", json={
        "chat_id":           GROUP_ID,
        "message_thread_id": REALESTATE_THREAD,
        "text":              text,
    }, timeout=10)


MAX_DAYS_NEW = 7   # Only post listings listed within this many days
MAX_PER_RUN  = 5   # Cap how many we post per cycle (avoid spam)


def run_new_listings_check():
    """Main cycle: fetch listings, post only NEW ones (≤7 days old, ≤5 per run)."""
    logger.info("Checking for new Mahogany listings on Zolo.ca…")
    listings = fetch_mahogany_listings(max_results=40)

    # Filter: only recent listings
    recent = [l for l in listings if l.get("days_on_market", 999) <= MAX_DAYS_NEW]
    logger.info(f"Recent listings (≤{MAX_DAYS_NEW}d): {len(recent)} / {len(listings)} total")

    new = get_new_listings(recent)
    new = new[:MAX_PER_RUN]  # cap per run

    if not new:
        logger.info("No new listings since last run.")
        return 0

    logger.info(f"Found {len(new)} new listings! Posting to Real Estate thread…")
    posted = 0
    for listing in new:
        if post_listing(listing):
            posted += 1
        time.sleep(3)

    mark_listings_seen(new)
    logger.info(f"Done. Posted {posted} new listings.")
    return posted


def run_manual_post(n: int):
    """Post N most recent listings regardless of seen status (for manual/demo use)."""
    logger.info(f"Fetching {n} most recent Mahogany listings…")
    listings = fetch_mahogany_listings(max_results=n * 3)
    if not listings:
        logger.warning("No listings found.")
        return

    # Header post
    from datetime import datetime
    date_str = datetime.now().strftime("%B %d, %Y")
    post_separator(f"🏡 <b>Mahogany Listings — {date_str}</b>\nFresh from Zolo.ca 📊")
    time.sleep(2)

    posted = 0
    for listing in listings[:n]:
        logger.info(f"Posting: {listing['address']} — ${listing['price']:,}")
        if post_listing(listing):
            posted += 1
            mark_listings_seen([listing])
        time.sleep(4)

    logger.info(f"✅ Posted {posted}/{n} listings to Real Estate thread.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post",  type=int, default=0,
                        help="Post N listings manually (ignores seen status)")
    parser.add_argument("--check", action="store_true",
                        help="Check for new listings only (default)")
    args = parser.parse_args()

    if args.post:
        run_manual_post(args.post)
    else:
        run_new_listings_check()
