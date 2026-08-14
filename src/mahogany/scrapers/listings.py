from mahogany.config import data_path
"""
listings_scraper.py — Kijiji scraper for Mahogany, Calgary real estate listings.

Kijiji embeds all listing data as Apollo/GraphQL JSON inside __NEXT_DATA__,
so no per-page fetching is needed — one request gets all listings.

Tracks seen listing IDs in listings_seen.json to detect NEW ones.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEEN_FILE = data_path("listings_seen.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control":   "no-cache",
    "Referer":         "https://www.google.ca/",
}
TIMEOUT = 15

# Mahogany + adjacent SE Calgary communities (all covered by the neighbourhood)
KIJIJI_URL = (
    "https://www.kijiji.ca/b-real-estate/calgary/mahogany/"
    "k0c34l1700199?sort=dateDesc"
)

MIN_PRICE = 100_000   # exclude rentals
MAX_PRICE = 5_000_000 # exclude obvious data errors


# ── Seen listings tracking ────────────────────────────────────────────────────

def _load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False))


# ── Kijiji parser ─────────────────────────────────────────────────────────────

def _fetch_kijiji_page(url: str) -> dict:
    """Fetch Kijiji page and extract embedded Apollo/GraphQL listing data."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"Kijiji fetch failed: {e}")
        return {}

    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        r.text, re.DOTALL
    )
    if not m:
        logger.warning("No __NEXT_DATA__ found in Kijiji page")
        return {}

    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse __NEXT_DATA__: {e}")
        return {}


def _parse_apollo_listings(data: dict) -> list[dict]:
    """Extract listing dicts from Kijiji Apollo state."""
    try:
        apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    except (KeyError, TypeError):
        logger.warning("Could not navigate to __APOLLO_STATE__")
        return []

    listings = []
    for key, val in apollo.items():
        if not key.startswith(("RealEstateListing:", "StandardListing:")):
            continue
        if not isinstance(val, dict):
            continue

        # Price — stored in cents on Kijiji
        price_data = val.get("price", {})
        amount_cents = price_data.get("amount", 0) if isinstance(price_data, dict) else 0
        price = int(amount_cents / 100) if amount_cents else 0

        if not (MIN_PRICE <= price <= MAX_PRICE):
            continue

        # Days on market from activation date
        activation = val.get("activationDate") or val.get("sortingDate", "")
        days_on = 999
        if activation:
            try:
                dt = datetime.fromisoformat(activation.replace("Z", "+00:00"))
                days_on = (datetime.now(timezone.utc) - dt).days
            except Exception:
                pass

        # Attributes (beds, baths, sqft)
        attrs = val.get("attributes", {}) or {}
        beds  = _attr_val(attrs, "numberbedrooms")
        baths = _attr_val(attrs, "numberbathrooms")
        sqft  = _attr_val(attrs, "areainfeet")

        # Property type
        prop_type = _infer_type(val.get("title", ""), val.get("categoryId"))

        # Address — Kijiji gives a mapAddress in location
        location = val.get("location", {}) or {}
        address = location.get("mapAddress", "") or val.get("title", "")

        # Image
        images = val.get("imageUrls", []) or []
        image_url = images[0].replace("kijijica-200-jpg", "kijijica-640-jpg") if images else None

        # Kijiji listing URL (already full URL in __NEXT_DATA__)
        url_path = val.get("url", "")
        if url_path.startswith("http"):
            listing_url = url_path
        elif url_path:
            listing_url = f"https://www.kijiji.ca{url_path}"
        else:
            listing_url = ""

        listings.append({
            "mls_id":         str(val.get("id", key)),
            "price":          price,
            "address":        address,
            "beds":           beds,
            "baths":          baths,
            "sqft":           sqft,
            "type":           prop_type,
            "url":            listing_url,
            "image_url":      image_url,
            "description":    (val.get("description") or "")[:400],
            "listed_date":    activation[:10] if activation else "",
            "days_on_market": days_on,
        })

    listings.sort(key=lambda x: x["days_on_market"])
    return listings


def _attr_val(attrs: dict, key: str):
    """Extract attribute value from Kijiji attributes.all list."""
    all_attrs = attrs.get("all", []) if isinstance(attrs, dict) else []
    for item in all_attrs:
        if item.get("canonicalName") == key:
            vals = item.get("canonicalValues", [])
            if vals:
                raw = vals[0]
                try:
                    v = int(float(str(raw).replace(",", "")))
                    # Kijiji bathroom codes: 10=1, 20=2, 30=3, 40=4+
                    if key == "numberbathrooms" and v % 10 == 0 and v > 9:
                        return v // 10
                    return v
                except (ValueError, TypeError):
                    return raw
    return None


def _infer_type(title: str, category_id=None) -> str:
    t = (title or "").lower()
    if any(w in t for w in ["condo", "apartment", "suite", "unit"]):
        return "Condo"
    if any(w in t for w in ["townhouse", "townhome", "row home", "row house"]):
        return "Townhouse"
    if any(w in t for w in ["semi-detached", "semi detached", "duplex", "half duplex"]):
        return "Semi-Detached"
    return "House"


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_mahogany_listings(max_results: int = 40) -> list[dict]:
    """
    Fetch current Mahogany for-sale listings from Kijiji.
    Returns list of listing dicts, newest first.
    """
    data = _fetch_kijiji_page(KIJIJI_URL)
    listings = _parse_apollo_listings(data)
    logger.info(f"Fetched {len(listings)} for-sale listings from Kijiji")
    return listings[:max_results]


def get_new_listings(listings: list[dict]) -> list[dict]:
    """Return only listings not previously seen."""
    seen = _load_seen()
    new = [l for l in listings if l["mls_id"] not in seen]
    logger.info(f"New listings: {len(new)} / {len(listings)} total")
    return new


def mark_listings_seen(listings: list[dict]):
    seen = _load_seen()
    for l in listings:
        seen[l["mls_id"]] = {
            "address": l["address"],
            "price":   l["price"],
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }
    _save_seen(seen)


def get_recent_listings(days: int = 7, max_results: int = 20) -> list[dict]:
    """Get listings added in the last N days."""
    all_listings = fetch_mahogany_listings(max_results=max_results * 3)
    return [l for l in all_listings if l.get("days_on_market", 999) <= days][:max_results]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    listings = fetch_mahogany_listings(max_results=n)
    print(f"\n{'='*60}")
    print(f"Found {len(listings)} Mahogany listings from Kijiji:")
    for l in listings:
        print(f"\n  🏡 {l['address']}")
        print(f"     💰 ${l['price']:,} | {l['beds']}bd {l['baths']}ba" +
              (f" | {l['sqft']:,} sqft" if l['sqft'] else ""))
        print(f"     🏷  {l['type']} | {l['days_on_market']}d on market")
        print(f"     🔗 {l['url']}")
        if l.get("image_url"):
            print(f"     🖼  {l['image_url'][:80]}")
