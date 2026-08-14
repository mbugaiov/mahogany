from mahogany.config import data_path
"""
rentals_scraper.py — Kijiji scraper for Mahogany/Calgary rental listings.

Kijiji embeds all listing data as Apollo/GraphQL JSON inside __NEXT_DATA__,
so one request gets all listings on the page.

Tracks seen listing IDs in rentals_seen.json to detect NEW ones.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

SEEN_FILE = data_path("rentals_seen.json")

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

# Kijiji Apartments & Condos for rent in Mahogany/SE Calgary (category c37)
KIJIJI_RENTALS_URL = (
    "https://www.kijiji.ca/b-apartments-condos/calgary/mahogany/"
    "k0c37l1700199?sort=dateDesc"
)

MIN_RENT =   500   # $/month — filter out obvious errors
MAX_RENT = 15_000  # $/month — filter out obviously wrong entries


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
        logger.warning(f"Kijiji rentals fetch failed: {e}")
        return {}

    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        r.text, re.DOTALL
    )
    if not m:
        logger.warning("No __NEXT_DATA__ found in Kijiji rentals page")
        return {}

    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse __NEXT_DATA__: {e}")
        return {}


def _parse_apollo_rentals(data: dict) -> list[dict]:
    """Extract rental listing dicts from Kijiji Apollo state."""
    try:
        apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    except (KeyError, TypeError):
        logger.warning("Could not navigate to __APOLLO_STATE__")
        return []

    listings = []
    for key, val in apollo.items():
        if not key.startswith("RealEstateListing:"):
            continue
        if not isinstance(val, dict):
            continue

        # Only rental category (37 = Apartments & Condos for rent)
        category_id = val.get("categoryId", 0)
        if str(category_id) != "37":
            continue

        # Price — Kijiji stores in cents
        price_data = val.get("price", {})
        amount_cents = price_data.get("amount", 0) if isinstance(price_data, dict) else 0
        rent = int(amount_cents / 100) if amount_cents else 0

        if not (MIN_RENT <= rent <= MAX_RENT):
            continue

        # Days since posted
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
        unit_type = _attr_val(attrs, "unittype") or _infer_type(val.get("title", ""))

        # Address
        location = val.get("location", {}) or {}
        address = location.get("mapAddress", "") or val.get("title", "")

        # Image
        images = val.get("imageUrls", []) or []
        image_url = images[0].replace("kijijica-200-jpg", "kijijica-640-jpg") if images else None

        # URL
        url_path = val.get("url", "")
        if url_path.startswith("http"):
            listing_url = url_path
        elif url_path:
            listing_url = f"https://www.kijiji.ca{url_path}"
        else:
            listing_url = ""

        if not listing_url:
            continue

        listings.append({
            "id":             str(val.get("id", key)),
            "rent":           rent,
            "address":        address,
            "beds":           beds,
            "baths":          baths,
            "sqft":           sqft,
            "type":           unit_type,
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
                    if key == "numberbathrooms" and v % 10 == 0 and v > 9:
                        return v // 10
                    return v
                except (ValueError, TypeError):
                    return raw
    return None


def _infer_type(title: str) -> str:
    t = (title or "").lower()
    if any(w in t for w in ["condo", "suite", "apartment", "apt"]):
        return "Condo/Apt"
    if any(w in t for w in ["townhouse", "townhome", "row"]):
        return "Townhouse"
    if any(w in t for w in ["basement", "bsmt"]):
        return "Basement Suite"
    if any(w in t for w in ["room", "bedroom"]):
        return "Room"
    return "House"


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_mahogany_rentals(max_results: int = 40) -> list[dict]:
    """
    Fetch current Mahogany/SE Calgary rental listings from Kijiji.
    Returns list of listing dicts, newest first.
    """
    data = _fetch_kijiji_page(KIJIJI_RENTALS_URL)
    listings = _parse_apollo_rentals(data)
    logger.info(f"Fetched {len(listings)} rental listings from Kijiji")
    return listings[:max_results]


def get_new_rentals(listings: list[dict]) -> list[dict]:
    """Return only listings not previously seen."""
    seen = _load_seen()
    new = [l for l in listings if l["id"] not in seen]
    logger.info(f"New rentals: {len(new)} / {len(listings)} total")
    return new


def mark_rentals_seen(listings: list[dict]):
    seen = _load_seen()
    for l in listings:
        seen[l["id"]] = {
            "address": l["address"],
            "rent":    l["rent"],
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }
    _save_seen(seen)


def get_recent_rentals(days: int = 3, max_results: int = 20) -> list[dict]:
    """Get rentals posted in the last N days."""
    all_listings = fetch_mahogany_rentals(max_results=max_results * 3)
    return [l for l in all_listings if l.get("days_on_market", 999) <= days][:max_results]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    listings = fetch_mahogany_rentals(max_results=n)
    print(f"\n{'='*60}")
    print(f"Found {len(listings)} Mahogany rental listings from Kijiji:")
    for l in listings:
        print(f"\n  🏠 {l['address']}")
        print(f"     💰 ${l['rent']:,}/mo | {l['beds'] or '?'}bd {l['baths'] or '?'}ba" +
              (f" | {l['sqft']:,} sqft" if l['sqft'] else ""))
        print(f"     🏷  {l['type']} | {l['days_on_market']}d posted")
        print(f"     🔗 {l['url']}")
