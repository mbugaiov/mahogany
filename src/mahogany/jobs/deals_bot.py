"""
deals_bot.py — Weekly deals & flyers digest for stores near Mahogany, Calgary.

Posts to "Deals & Flyers 🛒" thread (id=98).
Schedule: Wednesday 10 AM + Saturday 9 AM.

Data source: Flipp.com API (real-time flyer data).
Focuses on grocery, pharmacy, and household essentials near T3M.
"""

from mahogany.config import data_path
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI
from mahogany.state.dedup import can_run_bot, mark_bot_ran

from mahogany import config  # noqa: F401 — loads .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID       = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
DEALS_THREAD   = os.getenv("DEALS_THREAD_ID", "98")
OPENAI_KEY     = os.getenv("OPENAI_API_KEY")
API_BASE       = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

FLIPP_SEARCH = "https://backflipp.wishabi.com/flipp/items/search"
FLIPP_FLYERS = "https://backflipp.wishabi.com/flipp/flyers"
POSTAL_CODE  = "T3M0X1"   # Mahogany area
HEADERS      = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36", "Accept": "application/json"}

CACHE_FILE = data_path("deals_cache.json")

# Priority stores near Mahogany (closest first)
PRIORITY_STORES = [
    "real canadian superstore", "calgary co-op", "safeway", "save-on-foods",
    "freshco", "no frills", "sobeys", "walmart", "costco",
    "shoppers drug mart", "london drugs", "canadian tire",
    "t&t supermarket", "wholesale club",
]

# Search categories with emoji
SEARCH_CATEGORIES = [
    ("🥩 Meat & Seafood",   ["chicken breast", "ground beef", "salmon", "pork loin", "steak", "shrimp"]),
    ("🥦 Produce",          ["strawberries", "avocado", "broccoli", "blueberries", "tomatoes", "oranges"]),
    ("🥛 Dairy & Basics",   ["milk", "eggs", "butter", "cheese", "yogurt", "cream"]),
    ("🍞 Bakery & Pantry",  ["bread", "pasta", "rice", "cereal", "coffee", "juice"]),
    ("🏠 Household",        ["laundry detergent", "paper towels", "dish soap", "toilet paper"]),
]


# ── Data fetching ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _priority_score(merchant: str) -> int:
    m = merchant.lower()
    for i, store in enumerate(PRIORITY_STORES):
        if store in m:
            return i
    return len(PRIORITY_STORES)


def search_deals(query: str, max_items: int = 20) -> list[dict]:
    """Search Flipp for deals on a query near Mahogany."""
    try:
        r = requests.get(
            FLIPP_SEARCH,
            params={"locale": "en-ca", "postal_code": POSTAL_CODE, "q": query},
            headers=HEADERS,
            timeout=10,
        )
        if not r.ok:
            return []
        data = r.json()
        items = data.get("items", [])
        return items[:max_items]
    except Exception as e:
        logger.debug(f"Search '{query}' failed: {e}")
        return []


def fetch_all_deals() -> dict[str, list[dict]]:
    """
    Fetch deals across all categories.
    Returns dict: category_label → list of best deals.
    """
    results = {}

    for category_label, queries in SEARCH_CATEGORIES:
        cat_deals = []
        seen_names = set()

        for query in queries:
            items = search_deals(query, max_items=15)
            for item in items:
                name     = (item.get("name") or item.get("description") or "").strip()
                price    = item.get("current_price") or item.get("sale_price")
                merchant = item.get("merchant_name") or item.get("merchant", "")
                orig     = item.get("original_price")
                image    = item.get("image_url", "")

                if not name or not price or not merchant:
                    continue

                # Deduplicate by name+store
                key = f"{merchant.lower()}:{name[:20].lower()}"
                if key in seen_names:
                    continue
                seen_names.add(key)

                # Skip if not a near-priority store
                if _priority_score(merchant) >= len(PRIORITY_STORES):
                    continue

                savings_pct = 0
                if orig and price:
                    try:
                        savings_pct = round((float(orig) - float(price)) / float(orig) * 100)
                    except Exception:
                        pass

                cat_deals.append({
                    "name":         name[:50],
                    "price":        price,
                    "orig_price":   orig,
                    "savings_pct":  savings_pct,
                    "merchant":     merchant,
                    "priority":     _priority_score(merchant),
                    "image_url":    image,
                    "query":        query,
                })

            time.sleep(0.3)

        # Sort by savings % then by store priority
        cat_deals.sort(key=lambda x: (-x["savings_pct"], x["priority"]))
        if cat_deals:
            results[category_label] = cat_deals[:4]   # top 4 per category

    return results


# ── GPT writer ────────────────────────────────────────────────────────────────

MAYA_SYSTEM = """You are Maya — a savvy, friendly local guide for Mahogany, Calgary.
You write deal digests for a community Telegram channel. Conversational, warm English.
No markdown, no asterisks. Be specific and practical. Max 2 sentences per take."""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_deals_intro(deals_summary: str) -> str:
    prompt = f"""Write a fun 2-sentence intro for this week's grocery deals digest for Mahogany residents.
Mention one highlight deal or store and get people excited to check the list.
Today is {datetime.now().strftime('%A %B %d')}.

Top deals this week:
{deals_summary}"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=100, temperature=0.8,
    )
    return resp.choices[0].message.content.strip()


def write_shopping_tip(deals: dict) -> str:
    all_stores = list({d["merchant"] for cat in deals.values() for d in cat})
    prompt = f"""Give ONE very specific money-saving shopping tip for Mahogany residents this week.
Could be about store strategy, stacking deals, or an observation from this week's flyers.
Available stores nearby: {', '.join(all_stores[:6])}.
One sentence only, practical and specific."""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=80, temperature=0.8,
    )
    return resp.choices[0].message.content.strip()


# ── Report builder ────────────────────────────────────────────────────────────

def _price_str(item: dict) -> str:
    price = item["price"]
    orig  = item.get("orig_price")
    pct   = item.get("savings_pct", 0)
    s     = f"<b>${price}</b>"
    if orig and pct >= 10:
        s += f" <s>${orig}</s> <i>-{pct}%</i>"
    return s


def build_report(deals: dict) -> str:
    now = datetime.now()

    # Summary for GPT
    deals_summary = "\n".join(
        f"- {d['merchant']}: {d['name']} ${d['price']}" + (f" (was ${d['orig_price']})" if d.get("orig_price") else "")
        for cat, items in deals.items()
        for d in items[:2]
    )

    logger.info("Generating GPT intro…")
    intro = _escape(write_deals_intro(deals_summary))
    tip   = _escape(write_shopping_tip(deals))

    lines = [
        f"🛒 <b>Deals &amp; Flyers — Mahogany Area</b>",
        f"<i>Week of {now.strftime('%B %d, %Y')}</i>",
        "",
        intro,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for category, items in deals.items():
        lines.append(f"\n{category}")
        for item in items:
            name     = _escape(item["name"])
            merchant = _escape(item["merchant"])
            price_s  = _price_str(item)
            lines.append(f"  · <b>{merchant}</b>: {name} — {price_s}")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💡 <b>Pro tip:</b> {tip}",
        "",
        "📱 Full flyers: <a href='https://flipp.com/en-ca/calgary-ab-flyers'>Flipp.com</a>",
        "",
        "#MahoganyDeals #CalgaryDeals #GroceryDeals #CalgaryFlyers #YYC",
    ]

    return "\n".join(lines)


# ── Telegram sender ───────────────────────────────────────────────────────────

def post_report(text: str) -> bool:
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={
            "chat_id":                  GROUP_ID,
            "message_thread_id":        DEALS_THREAD,
            "text":                     text[:4096],
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    result = resp.json()
    if result.get("ok"):
        logger.info(f"✅ Deals posted → msg_id={result['result']['message_id']}")
        return True
    logger.error(f"❌ Error: {result.get('description')}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not can_run_bot("deals_bot", min_interval_hours=20):
        return

    logger.info("Fetching deals from Flipp.com…")
    deals = fetch_all_deals()

    total = sum(len(v) for v in deals.values())
    logger.info(f"Found {total} deals across {len(deals)} categories")

    if not deals:
        logger.warning("No deals found — aborting.")
        return

    text = build_report(deals)
    post_report(text)
    mark_bot_ran("deals_bot")

    _save_cache({"last_run": datetime.now(timezone.utc).isoformat(), "total": total})
    logger.info("Done.")


if __name__ == "__main__":
    run()
