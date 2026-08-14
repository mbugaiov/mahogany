"""
rentals_bot.py — Monitor Mahogany/SE Calgary rental listings and post new ones.

Run manually:  python3 rentals_bot.py --post N   (post N recent rentals)
Run as cron:   python3 rentals_bot.py             (post new rentals since last run)
"""

import argparse
import logging
import os
import sys
import time
import io
from datetime import datetime
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

from mahogany.scrapers.rentals import fetch_mahogany_rentals, get_new_rentals, mark_rentals_seen

TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID       = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
RENTALS_THREAD = os.getenv("RENTALS_THREAD_ID", "")  # Set after creating topic
API_BASE       = f"https://api.telegram.org/bot{TOKEN}"

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _type_emoji(prop_type: str) -> str:
    mapping = {
        "Condo/Apt":      "🏢",
        "Townhouse":      "🏘",
        "Basement Suite": "🏚",
        "House":          "🏠",
        "Room":           "🛏",
    }
    return mapping.get(prop_type, "🏠")


def format_rental(listing: dict) -> str:
    """Format a rental listing as a beautiful Telegram HTML post."""
    t     = _type_emoji(listing.get("type", ""))
    rent  = f"${listing['rent']:,}/mo" if listing["rent"] else "Rent N/A"
    address = listing["address"]
    beds  = listing.get("beds", 0)
    baths = listing.get("baths", 0)
    sqft  = listing.get("sqft")
    dom   = listing.get("days_on_market", 0)
    url   = listing["url"]
    desc  = (listing.get("description") or "")[:200]
    unit_type = listing.get("type", "Rental")

    # Freshness badge
    if dom == 0:
        badge = "🆕 <b>POSTED TODAY</b>"
    elif dom <= 2:
        badge = f"🔥 <b>NEW — {dom}d ago</b>"
    elif dom <= 7:
        badge = f"📅 Posted {dom} days ago"
    else:
        badge = f"📅 {dom} days since posted"

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
        f"💰 <b>{rent}</b>  {f'· {stats_line}' if stats_line else ''}\n"
        f"{unit_type}  ·  {badge}\n"
    )

    if desc:
        text += f"\n{desc}…\n"

    text += (
        f"\n"
        f"🔗 <a href='{url}'>View on Kijiji.ca</a>\n"
        f"\n"
        f"#MahoganyRentals #CalgaryRentals #MahoganyCalgary #YYC #CalgaryApartments"
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


def post_rental(listing: dict) -> bool:
    """Post a rental listing to the Rentals thread. Returns True on success."""
    if not RENTALS_THREAD:
        logger.error("RENTALS_THREAD_ID not set in .env — create the topic first!")
        return False

    text = format_rental(listing)
    img_bytes = _download_image(listing.get("image_url"))

    if img_bytes:
        resp = requests.post(
            f"{API_BASE}/sendPhoto",
            data={
                "chat_id":           GROUP_ID,
                "message_thread_id": RENTALS_THREAD,
                "caption":           text[:1020],
                "parse_mode":        "HTML",
            },
            files={"photo": ("rental.jpg", io.BytesIO(img_bytes), "image/jpeg")},
            timeout=30,
        )
    else:
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id":           GROUP_ID,
                "message_thread_id": RENTALS_THREAD,
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
        logger.info(f"✅ Posted: {listing['address']} ${listing['rent']:,}/mo → msg_id={msg_id}")
    else:
        logger.warning(f"❌ Failed: {result.get('description', '')}")
    return ok


def create_rentals_topic() -> int | None:
    """Create the Rentals forum topic and return its thread ID."""
    resp = requests.post(
        f"{API_BASE}/createForumTopic",
        json={
            "chat_id":    GROUP_ID,
            "name":       "Rentals 🏠",
            "icon_color": 0x6FB9F0,  # light blue
        },
        timeout=15,
    )
    result = resp.json()
    if result.get("ok"):
        thread_id = result["result"]["message_thread_id"]
        logger.info(f"✅ Created 'Rentals 🏠' topic → thread_id={thread_id}")
        return thread_id
    else:
        logger.error(f"Failed to create topic: {result.get('description', '')}")
        return None


MAX_DAYS_NEW = 5   # Only post rentals listed within this many days
MAX_PER_RUN  = 5   # Cap per cycle to avoid spam


def run_new_rentals_check():
    """Main cycle: fetch rentals, post only NEW ones (≤5 days old, ≤5 per run)."""
    logger.info("Checking for new Mahogany rental listings on Kijiji…")
    listings = fetch_mahogany_rentals(max_results=40)

    recent = [l for l in listings if l.get("days_on_market", 999) <= MAX_DAYS_NEW]
    logger.info(f"Recent rentals (≤{MAX_DAYS_NEW}d): {len(recent)} / {len(listings)} total")

    new = get_new_rentals(recent)
    new = new[:MAX_PER_RUN]

    if not new:
        logger.info("No new rentals since last run.")
        return 0

    logger.info(f"Found {len(new)} new rentals! Posting to Rentals thread…")
    posted = 0
    for listing in new:
        if post_rental(listing):
            posted += 1
        time.sleep(3)

    mark_rentals_seen(new)
    logger.info(f"Done. Posted {posted} new rentals.")
    return posted


def run_manual_post(n: int):
    """Post N most recent rentals regardless of seen status (for manual/demo use)."""
    logger.info(f"Fetching {n} most recent Mahogany/Calgary rental listings…")
    listings = fetch_mahogany_rentals(max_results=n * 3)
    if not listings:
        logger.warning("No rental listings found.")
        return

    date_str = datetime.now().strftime("%B %d, %Y")

    # Header post
    requests.post(f"{API_BASE}/sendMessage", json={
        "chat_id":           GROUP_ID,
        "message_thread_id": RENTALS_THREAD,
        "text": (
            f"🏠 <b>Mahogany Rentals — {date_str}</b>\n"
            f"Fresh listings from Kijiji.ca 🔑\n\n"
            f"Houses · Condos · Townhouses · Basement Suites"
        ),
        "parse_mode": "HTML",
    }, timeout=10)
    time.sleep(2)

    posted = 0
    for listing in listings[:n]:
        logger.info(f"Posting: {listing['address']} — ${listing['rent']:,}/mo")
        if post_rental(listing):
            posted += 1
            mark_rentals_seen([listing])
        time.sleep(4)

    logger.info(f"✅ Posted {posted}/{n} rentals to Rentals thread.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post",         type=int, default=0,
                        help="Post N rentals manually (ignores seen status)")
    parser.add_argument("--create-topic", action="store_true",
                        help="Create the Rentals forum topic and print thread_id")
    parser.add_argument("--check",        action="store_true",
                        help="Check for new rentals only (default)")
    args = parser.parse_args()

    if args.create_topic:
        thread_id = create_rentals_topic()
        if thread_id:
            print(f"\nAdd to .env:\n  RENTALS_THREAD_ID={thread_id}")
    elif args.post:
        run_manual_post(args.post)
    else:
        run_new_rentals_check()
