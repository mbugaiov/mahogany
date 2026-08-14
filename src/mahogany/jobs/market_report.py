"""
market_report.py — Daily Mahogany real estate market report.

Generates a beautifully written market digest and posts it to the News thread.
Run daily at 9 AM via launchd.

Report sections:
  1. Market snapshot  — total active, new this week, price stats
  2. New listings     — top 3 most interesting new listings (GPT-curated)
  3. Property of the Day — one highlighted listing with GPT deep-dive
  4. Market insight   — GPT-written original observation / trend
  5. Price segments   — entry, mid, luxury breakdown
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
from statistics import median, mean

import requests
from dotenv import load_dotenv
from openai import OpenAI

from mahogany import config  # noqa: F401 — loads .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from mahogany.scrapers.listings import fetch_mahogany_listings
from mahogany.state.dedup import can_run_bot, mark_bot_ran

TOKEN         = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID      = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
NEWS_THREAD   = os.getenv("NEWS_THREAD_ID", "6")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY")
API_BASE      = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

REPORT_CACHE = data_path("report_cache.json")
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36"}


# ── Data helpers ──────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if REPORT_CACHE.exists():
        try:
            return json.loads(REPORT_CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    REPORT_CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def compute_stats(listings: list[dict]) -> dict:
    """Compute market statistics from a list of listings."""
    prices = [l["price"] for l in listings if l.get("price", 0) > 50_000]
    if not prices:
        return {}

    by_type = {}
    for l in listings:
        t = l.get("type", "Other")
        by_type.setdefault(t, []).append(l["price"])

    new_7d  = [l for l in listings if l.get("days_on_market", 999) <= 7]
    new_1d  = [l for l in listings if l.get("days_on_market", 999) == 0]

    # Price segments
    entry   = [l for l in listings if 0 < l["price"] < 500_000]
    mid     = [l for l in listings if 500_000 <= l["price"] < 900_000]
    luxury  = [l for l in listings if l["price"] >= 900_000]

    return {
        "total":      len(listings),
        "median":     int(median(prices)),
        "average":    int(mean(prices)),
        "min_price":  min(prices),
        "max_price":  max(prices),
        "new_7d":     len(new_7d),
        "new_today":  len(new_1d),
        "by_type":    {k: {"count": len(v), "median": int(median(v))} for k, v in by_type.items()},
        "entry_count":   len(entry),
        "mid_count":     len(mid),
        "luxury_count":  len(luxury),
        "entry_min":     min([l["price"] for l in entry], default=0),
        "mid_min":       min([l["price"] for l in mid], default=0),
        "luxury_min":    min([l["price"] for l in luxury], default=0),
    }


def pick_property_of_day(listings: list[dict], stats: dict) -> dict | None:
    """Pick the most interesting listing to feature today."""
    if not listings:
        return None

    # Prefer: recent (≤5d), has image, has sqft — sorted by "interestingness"
    scored = []
    for l in listings:
        score = 0
        if l.get("image_url"):       score += 3
        if l.get("sqft"):            score += 2
        if l.get("days_on_market", 999) <= 3: score += 4
        if (l.get("beds") or 0) >= 4:   score += 1
        # Prefer mid-range (more relatable)
        p = l.get("price") or 0
        if 500_000 <= p <= 900_000:  score += 2
        scored.append((score, l))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else listings[0]


# ── GPT writers ───────────────────────────────────────────────────────────────

def gpt(prompt: str, system: str, max_tokens: int = 500) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.75,
    )
    return resp.choices[0].message.content.strip()


MAYA_SYSTEM = """You are Maya — a warm, sharp real estate expert and local guide for Mahogany, Calgary.
You write for a Telegram channel (@mahogany_calgary) — smart, concise, conversational English.
No corporate speak. Think knowledgeable friend who lives in Mahogany and loves data.
Use plain text only — no markdown, no asterisks, no hashtags (those go separately).
Keep it tight. Every sentence must earn its place."""


def _escape(text: str) -> str:
    """Escape HTML special chars in GPT-generated text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_market_insight(stats: dict, new_listings: list[dict], date_str: str) -> str:
    """GPT writes a short original market insight / observation."""
    context = f"""Today: {date_str}
Active listings: {stats['total']}
Median price: ${stats['median']:,}
New this week: {stats['new_7d']}
Entry-level (<$500K): {stats['entry_count']} homes (from ${stats['entry_min']:,})
Mid-range ($500K-$900K): {stats['mid_count']} homes
Luxury ($900K+): {stats['luxury_count']} homes (from ${stats['luxury_min']:,})

Recent new listings:
""" + "\n".join(
        f"- {l['address']}: ${l['price']:,} ({l['type']}, {l.get('beds',0)}bd, {l.get('days_on_market',0)}d old)"
        for l in new_listings[:6]
    )

    return gpt(
        f"Write a 3-4 sentence market insight for Mahogany real estate today. "
        f"Highlight one interesting pattern, trend, or observation from this data. "
        f"Be specific and opinionated — don't just list numbers back.\n\n{context}",
        MAYA_SYSTEM,
        max_tokens=180,
    )


def write_property_spotlight(listing: dict, stats: dict) -> str:
    """GPT writes a Property of the Day spotlight."""
    price      = listing.get("price", 0)
    median_p   = stats.get("median", 700_000)
    vs_median  = ((price - median_p) / median_p * 100) if median_p else 0
    vs_str     = f"{abs(vs_median):.0f}% {'above' if vs_median > 0 else 'below'} median"

    prompt = f"""Write a compelling 4-5 sentence spotlight for this Mahogany listing.
Be specific: mention price vs market, what makes it stand out, who it's ideal for.
Give an honest take — if it's overpriced, say so tactfully. If it's a deal, say why.

Listing:
Address: {listing['address']}
Price: ${price:,} ({vs_str})
Type: {listing['type']}
Beds: {listing.get('beds',0)} | Baths: {listing.get('baths',0)} | Sqft: {listing.get('sqft','N/A')}
Days on market: {listing.get('days_on_market', 0)}
URL: {listing['url']}"""

    return gpt(prompt, MAYA_SYSTEM, max_tokens=220)


def write_new_listings_summary(new_listings: list[dict]) -> str:
    """GPT writes a brief summary of new listings."""
    if not new_listings:
        return "No new listings appeared this week — inventory is tight."

    items = "\n".join(
        f"- {l['address']}: ${l['price']:,} ({l['type']}, {l.get('beds',0)}bd {l.get('baths',0)}ba"
        + (f", {l['sqft']:,} sqft" if l.get('sqft') else "") + ")"
        for l in new_listings[:5]
    )
    return gpt(
        f"Write 2 sentences summarizing what's new on the Mahogany market this week. "
        f"Mention price range, variety, or anything interesting. Be specific.\n\nNew listings:\n{items}",
        MAYA_SYSTEM,
        max_tokens=100,
    )


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(listings: list[dict], date_str: str) -> tuple[str, str | None]:
    """
    Build the full report text and pick a hero image URL.
    Returns (report_text, image_url).
    """
    stats = compute_stats(listings)
    if not stats:
        return ("No listing data available today.", None)

    new_7d    = [l for l in listings if l.get("days_on_market", 999) <= 7]
    new_today = [l for l in listings if l.get("days_on_market", 999) == 0]
    potd      = pick_property_of_day(listings, stats)

    logger.info("Generating GPT content…")

    # GPT sections (escape HTML in AI-generated text)
    insight    = _escape(write_market_insight(stats, new_7d, date_str))
    new_summary = _escape(write_new_listings_summary(new_7d))
    spotlight  = _escape(write_property_spotlight(potd, stats)) if potd else ""

    # Coloured emoji progress bars
    def price_bar(count, total, width=10, filled_emoji="🟩", empty_emoji="⬜"):
        filled = round(count / total * width) if total else 0
        return filled_emoji * filled + empty_emoji * (width - filled)

    entry_pct  = round(stats["entry_count"]  / stats["total"] * 100) if stats["total"] else 0
    mid_pct    = round(stats["mid_count"]    / stats["total"] * 100) if stats["total"] else 0
    luxury_pct = round(stats["luxury_count"] / stats["total"] * 100) if stats["total"] else 0

    # Build text
    lines = [
        f"📊 <b>Mahogany Market Report</b>",
        f"<i>{date_str}</i>",
        "",
        f"🏡 <b>{stats['total']}</b> active listings",
        f"🆕 <b>{stats['new_7d']}</b> new this week" + (f"  ·  <b>{stats['new_today']}</b> today" if stats['new_today'] else ""),
        f"💰 Median <b>${stats['median']:,}</b>  ·  Avg ${stats['average']:,}",
        f"📉 From <b>${stats['min_price']:,}</b>  →  📈 up to <b>${stats['max_price']:,}</b>",
        "",
        "🏷 <b>Price segments:</b>",
        f"🟢 Entry   &lt;$500K",
        f"{price_bar(stats['entry_count'], stats['total'], filled_emoji='🟩')}  <b>{stats['entry_count']}</b> homes · {entry_pct}%  (from ${stats['entry_min']:,})",
        f"🔵 Mid     $500–900K",
        f"{price_bar(stats['mid_count'], stats['total'], filled_emoji='🟦')}  <b>{stats['mid_count']}</b> homes · {mid_pct}%",
        f"🟡 Luxury  $900K+",
        f"{price_bar(stats['luxury_count'], stats['total'], filled_emoji='🟨')}  <b>{stats['luxury_count']}</b> homes · {luxury_pct}%",
        "",
        f"🔍 <b>New this week</b>",
        new_summary,
    ]

    if new_7d:
        for l in new_7d[:3]:
            badge = "🆕" if l.get("days_on_market", 1) == 0 else f"{l.get('days_on_market', '?')}d"
            addr = _escape(l['address'])
            lines.append(
                f"  · <a href=\"{l['url']}\">{addr}</a> — <b>${l['price']:,}</b> [{badge}]"
            )

    if potd and spotlight:
        potd_addr = _escape(potd['address'])
        lines += [
            "",
            f"🏆 <b>Property of the Day</b>",
            f"<a href=\"{potd['url']}\">{potd_addr}</a> — <b>${potd['price']:,}</b>",
            "",
            spotlight,
        ]

    lines += [
        "",
        f"💡 <b>Maya's take</b>",
        insight,
        "",
        "#MahoganyRealEstate #CalgaryMarket #MahoganyCalgary #YYC #CalgaryHomes",
    ]

    hero_image = potd.get("image_url") if potd else None
    return "\n".join(lines), hero_image


# ── Telegram sender ───────────────────────────────────────────────────────────

def _download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=15)
        if r.ok and "image" in r.headers.get("Content-Type", ""):
            return r.content
    except Exception:
        pass
    return None


def post_report(text: str, image_url: str | None = None) -> bool:
    img = _download_image(image_url)

    if img:
        resp = requests.post(
            f"{API_BASE}/sendPhoto",
            data={
                "chat_id":           GROUP_ID,
                "message_thread_id": NEWS_THREAD,
                "caption":           text[:1020],
                "parse_mode":        "HTML",
            },
            files={"photo": ("report.jpg", io.BytesIO(img), "image/jpeg")},
            timeout=30,
        )
    else:
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id":           GROUP_ID,
                "message_thread_id": NEWS_THREAD,
                "text":              text[:4096],
                "parse_mode":        "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

    result = resp.json()
    if result.get("ok"):
        logger.info(f"✅ Report posted → msg_id={result['result']['message_id']}")
        return True
    else:
        logger.error(f"❌ Telegram error: {result.get('description')}")
        # If photo failed, try text-only
        if img:
            logger.info("Retrying without photo…")
            return post_report(text, image_url=None)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not can_run_bot("market_report", min_interval_hours=20):
        return

    date_str = datetime.now().strftime("%A, %B %d %Y")
    logger.info(f"Building Mahogany market report for {date_str}…")

    listings = fetch_mahogany_listings(max_results=60)
    if not listings:
        logger.error("No listings fetched — aborting.")
        return

    logger.info(f"Fetched {len(listings)} listings. Computing stats…")
    text, hero_image = build_report(listings, date_str)

    logger.info("Posting report to News thread…")
    post_report(text, hero_image)

    mark_bot_ran("market_report")
    _save_cache({
        "last_run":    datetime.now(timezone.utc).isoformat(),
        "total":       len(listings),
        "date":        date_str,
    })
    logger.info("Done.")


if __name__ == "__main__":
    run()
