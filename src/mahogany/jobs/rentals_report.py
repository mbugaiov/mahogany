"""
rentals_report.py — Weekly Mahogany rental market report.

Mirrors market_report.py but for rental listings from Kijiji.

Report sections:
  1. Rental snapshot    — total active, new this week, rent stats
  2. Bedroom segments   — Studio / 1BR / 2BR / 3BR+ with emoji bars
  3. New this week      — GPT-curated summary of freshest listings
  4. Rental of the Day  — one highlighted rental with GPT deep-dive
  5. Maya's rental take — GPT-written market insight
"""

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

from mahogany.scrapers.rentals import fetch_mahogany_rentals
from mahogany.state.dedup import can_run_bot, mark_bot_ran

TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID       = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
RENTALS_THREAD = os.getenv("RENTALS_THREAD_ID", "")
OPENAI_KEY     = os.getenv("OPENAI_API_KEY")
API_BASE       = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36"}


# ── Stats ─────────────────────────────────────────────────────────────────────

def compute_rental_stats(listings: list[dict]) -> dict:
    rents = [l["rent"] for l in listings if l.get("rent", 0) > 0]
    if not rents:
        return {}

    new_7d = [l for l in listings if l.get("days_on_market", 999) <= 7]
    new_1d = [l for l in listings if l.get("days_on_market", 999) == 0]

    # Bedroom segments
    def _beds(l):
        return l.get("beds") or 0

    studio  = [l for l in listings if _beds(l) == 0]
    one_br  = [l for l in listings if _beds(l) == 1]
    two_br  = [l for l in listings if _beds(l) == 2]
    three_plus = [l for l in listings if _beds(l) >= 3]

    def _med_rent(lst):
        r = [l["rent"] for l in lst if l.get("rent", 0) > 0]
        return int(median(r)) if r else 0

    return {
        "total":         len(listings),
        "median_rent":   int(median(rents)),
        "avg_rent":      int(mean(rents)),
        "min_rent":      min(rents),
        "max_rent":      max(rents),
        "new_7d":        len(new_7d),
        "new_today":     len(new_1d),
        # Bedroom segments
        "studio_count":     len(studio),
        "one_br_count":     len(one_br),
        "two_br_count":     len(two_br),
        "three_plus_count": len(three_plus),
        "studio_med":       _med_rent(studio),
        "one_br_med":       _med_rent(one_br),
        "two_br_med":       _med_rent(two_br),
        "three_plus_med":   _med_rent(three_plus),
    }


def pick_rental_of_day(listings: list[dict]) -> dict | None:
    if not listings:
        return None
    scored = []
    for l in listings:
        score = 0
        if l.get("image_url"):                       score += 3
        if l.get("sqft"):                            score += 2
        if l.get("days_on_market", 999) <= 3:        score += 4
        beds = l.get("beds") or 0
        if beds >= 2:                                score += 1
        # Prefer mid-range (more relatable)
        r = l.get("rent", 0)
        if 1_500 <= r <= 2_800:                      score += 2
        scored.append((score, l))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else listings[0]


# ── GPT writers ───────────────────────────────────────────────────────────────

MAYA_SYSTEM = """You are Maya — a warm, sharp real estate expert and local guide for Mahogany, Calgary.
You write for a Telegram channel (@mahogany_calgary) — smart, concise, conversational English.
No corporate speak. Think knowledgeable friend who lives in Mahogany and loves data.
Use plain text only — no markdown, no asterisks, no hashtags (those go separately).
Keep it tight. Every sentence must earn its place."""


def gpt(prompt: str, max_tokens: int = 200) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.75,
    )
    return resp.choices[0].message.content.strip()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_rental_insight(stats: dict, new_listings: list[dict], date_str: str) -> str:
    context = f"""Today: {date_str}
Active rental listings: {stats['total']}
Median rent: ${stats['median_rent']:,}/mo  |  Avg: ${stats['avg_rent']:,}/mo
Range: ${stats['min_rent']:,} – ${stats['max_rent']:,}/mo
New this week: {stats['new_7d']}

By bedrooms:
- Studio:    {stats['studio_count']} listings  (med ${stats['studio_med']:,}/mo)
- 1 Bedroom: {stats['one_br_count']} listings  (med ${stats['one_br_med']:,}/mo)
- 2 Bedroom: {stats['two_br_count']} listings  (med ${stats['two_br_med']:,}/mo)
- 3+ Bedrooms: {stats['three_plus_count']} listings  (med ${stats['three_plus_med']:,}/mo)

Recent new listings:
""" + "\n".join(
        f"- {l['address']}: ${l['rent']:,}/mo ({l.get('type','')}, "
        f"{l.get('beds') or 0}bd, {l.get('days_on_market',0)}d old)"
        for l in new_listings[:5]
    )

    return gpt(
        f"Write a 3-4 sentence market insight about the Mahogany rental market today. "
        f"Highlight one interesting pattern or trend renters should know about. "
        f"Be specific and opinionated — don't just list numbers back.\n\n{context}",
        max_tokens=180,
    )


def write_rental_of_day(listing: dict, stats: dict) -> str:
    rent       = listing.get("rent", 0)
    med_rent   = stats.get("median_rent", 1800)
    vs_med     = ((rent - med_rent) / med_rent * 100) if med_rent else 0
    vs_str     = f"{abs(vs_med):.0f}% {'above' if vs_med > 0 else 'below'} median"

    prompt = f"""Write a compelling 4-5 sentence spotlight for this Mahogany rental listing.
Be specific: mention price vs market, what makes it stand out, who it's ideal for.
Be honest — if it's overpriced, say so tactfully. If it's a deal, say why.

Listing:
Address: {listing['address']}
Rent: ${rent:,}/mo ({vs_str})
Type: {listing.get('type', 'Rental')}
Beds: {listing.get('beds') or 0} | Baths: {listing.get('baths') or 0} | Sqft: {listing.get('sqft') or 'N/A'}
Days posted: {listing.get('days_on_market', 0)}
URL: {listing['url']}"""

    return gpt(prompt, max_tokens=220)


def write_new_rentals_summary(new_listings: list[dict]) -> str:
    if not new_listings:
        return "No new rentals appeared this week — inventory is very tight right now."
    items = "\n".join(
        f"- {l['address']}: ${l['rent']:,}/mo ({l.get('type','')}, "
        f"{l.get('beds') or 0}bd {l.get('baths') or 0}ba)"
        for l in new_listings[:5]
    )
    return gpt(
        f"Write 2 sentences summarizing what's new in Mahogany rentals this week. "
        f"Mention rent range, variety, or anything interesting for renters. Be specific.\n\nNew listings:\n{items}",
        max_tokens=100,
    )


# ── Report builder ────────────────────────────────────────────────────────────

def build_rental_report(listings: list[dict], date_str: str) -> tuple[str, str | None]:
    stats = compute_rental_stats(listings)
    if not stats:
        return ("No rental data available today.", None)

    new_7d  = [l for l in listings if l.get("days_on_market", 999) <= 7]
    rotd    = pick_rental_of_day(listings)

    logger.info("Generating GPT content…")
    insight      = _escape(write_rental_insight(stats, new_7d, date_str))
    new_summary  = _escape(write_new_rentals_summary(new_7d))
    spotlight    = _escape(write_rental_of_day(rotd, stats)) if rotd else ""

    # Coloured emoji progress bars (by bedroom count)
    total = stats["total"] or 1
    def rent_bar(count, width=10, filled_emoji="🟩", empty_emoji="⬜"):
        filled = round(count / total * width)
        return filled_emoji * filled + empty_emoji * (width - filled)

    studio_pct     = round(stats["studio_count"]     / total * 100)
    one_br_pct     = round(stats["one_br_count"]     / total * 100)
    two_br_pct     = round(stats["two_br_count"]     / total * 100)
    three_plus_pct = round(stats["three_plus_count"] / total * 100)

    lines = [
        "🏠 <b>Mahogany Rental Report</b>",
        f"<i>{date_str}</i>",
        "",
        f"🔑 <b>{stats['total']}</b> active rentals",
        f"🆕 <b>{stats['new_7d']}</b> new this week" + (f"  ·  <b>{stats['new_today']}</b> today" if stats['new_today'] else ""),
        f"💰 Median <b>${stats['median_rent']:,}/mo</b>  ·  Avg ${stats['avg_rent']:,}/mo",
        f"📉 From <b>${stats['min_rent']:,}/mo</b>  →  📈 up to <b>${stats['max_rent']:,}/mo</b>",
        "",
        "🛏 <b>By bedrooms:</b>",
    ]

    if stats["studio_count"]:
        lines += [
            f"⚪ Studio",
            f"{rent_bar(stats['studio_count'], filled_emoji='🟣')}  <b>{stats['studio_count']}</b> listings · {studio_pct}%"
            + (f"  (med ${stats['studio_med']:,}/mo)" if stats['studio_med'] else ""),
        ]
    if stats["one_br_count"]:
        lines += [
            f"🟢 1 Bedroom",
            f"{rent_bar(stats['one_br_count'], filled_emoji='🟩')}  <b>{stats['one_br_count']}</b> listings · {one_br_pct}%"
            + (f"  (med ${stats['one_br_med']:,}/mo)" if stats['one_br_med'] else ""),
        ]
    if stats["two_br_count"]:
        lines += [
            f"🔵 2 Bedrooms",
            f"{rent_bar(stats['two_br_count'], filled_emoji='🟦')}  <b>{stats['two_br_count']}</b> listings · {two_br_pct}%"
            + (f"  (med ${stats['two_br_med']:,}/mo)" if stats['two_br_med'] else ""),
        ]
    if stats["three_plus_count"]:
        lines += [
            f"🟡 3+ Bedrooms",
            f"{rent_bar(stats['three_plus_count'], filled_emoji='🟨')}  <b>{stats['three_plus_count']}</b> listings · {three_plus_pct}%"
            + (f"  (med ${stats['three_plus_med']:,}/mo)" if stats['three_plus_med'] else ""),
        ]

    lines += ["", "🔍 <b>New this week</b>", new_summary]

    if new_7d:
        for l in new_7d[:3]:
            badge = "🆕" if l.get("days_on_market", 1) == 0 else f"{l.get('days_on_market','?')}d"
            addr = _escape(l['address'])
            lines.append(
                f"  · <a href=\"{l['url']}\">{addr}</a> — <b>${l['rent']:,}/mo</b> [{badge}]"
            )

    if rotd and spotlight:
        rotd_addr = _escape(rotd['address'])
        lines += [
            "",
            "🏆 <b>Rental of the Day</b>",
            f"<a href=\"{rotd['url']}\">{rotd_addr}</a> — <b>${rotd['rent']:,}/mo</b>",
            "",
            spotlight,
        ]

    lines += [
        "",
        "💡 <b>Maya's take</b>",
        insight,
        "",
        "#MahoganyRentals #CalgaryRentals #MahoganyCalgary #YYC #CalgaryApartments",
    ]

    hero_image = rotd.get("image_url") if rotd else None
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
                "message_thread_id": RENTALS_THREAD,
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
                "chat_id":                GROUP_ID,
                "message_thread_id":      RENTALS_THREAD,
                "text":                   text[:4096],
                "parse_mode":             "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

    result = resp.json()
    if result.get("ok"):
        logger.info(f"✅ Rental report posted → msg_id={result['result']['message_id']}")
        return True
    else:
        logger.error(f"❌ Telegram error: {result.get('description')}")
        if img:
            logger.info("Retrying without photo…")
            return post_report(text, image_url=None)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not can_run_bot("rentals_report", min_interval_hours=20):
        return

    date_str = datetime.now().strftime("%A, %B %d %Y")
    logger.info(f"Building Mahogany rental report for {date_str}…")

    listings = fetch_mahogany_rentals(max_results=60)
    if not listings:
        logger.error("No rental listings fetched — aborting.")
        return

    logger.info(f"Fetched {len(listings)} rentals. Computing stats…")
    text, hero_image = build_rental_report(listings, date_str)

    logger.info("Posting rental report to Rentals thread…")
    post_report(text, hero_image)
    mark_bot_ran("rentals_report")
    logger.info("Done.")


if __name__ == "__main__":
    run()
