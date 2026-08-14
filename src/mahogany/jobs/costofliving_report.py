"""
costofliving_report.py — Weekly Mahogany Cost of Living Report.

Posts every Monday at 8 AM to the News thread.
Covers: gas prices (NRCan), grocery flyer deals nearby, + GPT analysis.

Data sources:
  - Natural Resources Canada (nrcan.gc.ca) — official weekly fuel price data
  - Flipp.com — flyer deals at Superstore, Safeway, Costco near Mahogany
"""

from mahogany.config import data_path
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean

import requests
from bs4 import BeautifulSoup
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

TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID    = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
NEWS_THREAD = os.getenv("NEWS_THREAD_ID", "6")
OPENAI_KEY  = os.getenv("OPENAI_API_KEY")
API_BASE    = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

CACHE_FILE = data_path("costofliving_cache.json")
HTTP_HDR    = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# NRCan location IDs: 66=Calgary, Canada=National
NRCAN_CALGARY = "https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm?priceYear=0&productID=1&locationID=66&isEmpty=0"
NRCAN_CANADA  = "https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm?priceYear=0&productID=1&locationID=1&isEmpty=0"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Gas price scraper ─────────────────────────────────────────────────────────

def fetch_gas_prices() -> dict:
    """
    Fetch Calgary and Canada average gas prices from NRCan.
    Returns dict with keys: calgary, canada, last_date, trend.
    """
    result = {"calgary": None, "canada": None, "last_date": None, "trend": None}

    def parse_nrcan(url: str) -> tuple[float | None, str | None]:
        """Returns (most_recent_price_cents, date_str)."""
        try:
            r = requests.get(url, headers=HTTP_HDR, timeout=12)
            if not r.ok:
                return None, None
            soup = BeautifulSoup(r.text, "html.parser")
            # Look for table with date, price data
            rows = []
            for row in soup.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    # Date cell looks like 2026-03-14
                    if re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
                        try:
                            price = float(cells[1])
                            rows.append((cells[0], price))
                        except (ValueError, IndexError):
                            pass
            if rows:
                rows.sort(key=lambda x: x[0], reverse=True)
                return rows[0][1], rows[0][0]
        except Exception as e:
            logger.warning(f"NRCan parse failed: {e}")
        return None, None

    cal_price, cal_date = parse_nrcan(NRCAN_CALGARY)
    can_price, _        = parse_nrcan(NRCAN_CANADA)

    result["calgary"]   = cal_price
    result["canada"]    = can_price
    result["last_date"] = cal_date

    # Compare to cached previous price for trend
    cache = _load_cache()
    prev_price = cache.get("gas", {}).get("calgary")
    if prev_price and cal_price:
        diff = cal_price - prev_price
        if diff > 1.5:     result["trend"] = f"↑ up {diff:.1f}¢ from last week"
        elif diff < -1.5:  result["trend"] = f"↓ down {abs(diff):.1f}¢ from last week"
        else:              result["trend"] = "→ stable vs last week"

    return result


def fetch_nearby_flyers() -> list[dict]:
    """
    Fetch top grocery deals near Mahogany from Flipp.com.
    Returns list of {store, item, price, savings}.
    """
    deals = []
    try:
        r = requests.get(
            "https://backflipp.wishabi.com/flipp/flyers/search"
            "?locale=en-ca&postal_code=T3M0X1&channel=flipp",
            headers={**HTTP_HDR, "Accept": "application/json"},
            timeout=12,
        )
        if r.ok:
            flyers = r.json().get("flyers", [])
            # Target stores near Mahogany
            target_stores = ["superstore", "safeway", "costco", "sobeys", "no frills", "freshco"]
            for flyer in flyers:
                store_name = flyer.get("merchant_name", "").lower()
                if any(s in store_name for s in target_stores):
                    # Get flyer items
                    flyer_id = flyer.get("id")
                    if flyer_id:
                        r2 = requests.get(
                            f"https://backflipp.wishabi.com/flipp/flyers/{flyer_id}/items",
                            headers={**HTTP_HDR, "Accept": "application/json"},
                            timeout=10,
                        )
                        if r2.ok:
                            items = r2.json().get("flyer_items", [])
                            for item in items[:3]:
                                name  = item.get("name", "")
                                price = item.get("current_price")
                                orig  = item.get("pre_price_text", "")
                                if name and price:
                                    deals.append({
                                        "store":   flyer.get("merchant_name", ""),
                                        "item":    name[:40],
                                        "price":   price,
                                        "savings": orig,
                                    })
                    if len(deals) >= 6:
                        break
    except Exception as e:
        logger.debug(f"Flipp fetch failed (non-critical): {e}")

    return deals[:6]


# ── Cost of living calculations ───────────────────────────────────────────────

def calc_monthly_gas_cost(price_cents: float) -> dict:
    """Estimate monthly gas cost for a typical Mahogany household."""
    # Average Calgary commute: ~40 km/day, 5 days/week = 800 km/month
    # Average SUV/truck: 12L/100km — common in AB
    km_month    = 800
    efficiency  = 12  # L/100km
    litres      = km_month * efficiency / 100
    cost        = litres * price_cents / 100
    return {
        "litres":   round(litres, 1),
        "cost":     round(cost, 2),
        "km":       km_month,
    }


# ── GPT writer ────────────────────────────────────────────────────────────────

MAYA_SYSTEM = """You are Maya — a sharp, warm local expert for Mahogany, Calgary.
You write for a community Telegram channel. Plain text, conversational English, 
like a neighbour who actually checks the flyers and tracks gas prices.
No markdown, no asterisks. Be specific and useful."""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_cost_take(gas: dict, gas_cost: dict, deals: list[dict]) -> str:
    price_str = f"{gas['calgary']:.1f}¢/L" if gas["calgary"] else "N/A"
    trend_str = gas.get("trend", "")
    deals_str = ", ".join(f"{d['store']}: {d['item']} ${d['price']}" for d in deals[:3]) if deals else "No deals data"

    prompt = f"""Write 2-3 sentences with a practical take on this week's cost of living in Mahogany/Calgary.
Be specific — mention gas, a tip to save money, or comment on the price trend.
If gas is going up, say something empathetic but practical.

Data:
Gas price: {price_str} {trend_str}
Monthly gas cost estimate: ${gas_cost['cost']:.0f} (based on {gas_cost['km']} km/month)
Canada average: {gas['canada']:.1f}¢/L if gas['canada'] else 'N/A'
Nearby deals: {deals_str}"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=130, temperature=0.75,
    )
    return resp.choices[0].message.content.strip()


def write_saving_tips(gas: dict) -> list[str]:
    price_str = f"{gas['calgary']:.1f}¢/L" if gas["calgary"] else "N/A"
    prompt = f"""Give 3 very specific money-saving tips for Mahogany residents this week.
Focus on: fuel efficiency, grocery shopping, or local deals.
Current gas: {price_str}. Near Mahogany: Superstore on Mahogany Blvd, Safeway, Costco Auburn Bay.
Format: one tip per line, no bullet points, no numbers. Be specific (store names, strategies)."""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=150, temperature=0.7,
    )
    raw   = resp.choices[0].message.content.strip()
    lines = [l.lstrip("•*-–0123456789. ").strip() for l in raw.split("\n") if l.strip()]
    return lines[:3]


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(gas: dict, deals: list[dict]) -> str:
    now = datetime.now()

    calgary_price = gas.get("calgary")
    canada_price  = gas.get("canada")
    trend         = gas.get("trend", "")
    gas_cost      = calc_monthly_gas_cost(calgary_price) if calgary_price else {}

    # GPT content
    logger.info("Generating GPT content…")
    take  = _escape(write_cost_take(gas, gas_cost, deals))
    tips  = write_saving_tips(gas)

    # Price comparison indicator
    if calgary_price and canada_price:
        diff = calgary_price - canada_price
        if diff < -3:   vs_canada = f"🟢 {abs(diff):.1f}¢ below national avg"
        elif diff > 3:  vs_canada = f"🔴 {abs(diff):.1f}¢ above national avg"
        else:           vs_canada = f"🟡 near national avg ({canada_price:.1f}¢)"
    else:
        vs_canada = ""

    # Price trend arrow
    trend_icon = "↑" if trend and "up" in trend else "↓" if trend and "down" in trend else "→"

    lines = [
        f"⛽ <b>Mahogany Cost of Living</b>",
        f"<i>Week of {now.strftime('%B %d, %Y')}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⛽ <b>Gas — Calgary SE</b>",
    ]

    if calgary_price:
        lines += [
            f"Regular:  <b>{calgary_price:.1f}¢/L</b>  {trend_icon}  {trend}",
            vs_canada,
            f"",
            f"🚗 Typical month ({gas_cost.get('km', 800)} km):",
            f"  Midsize SUV (12L/100km) → <b>${gas_cost.get('cost', 0):.0f}/month</b>",
            f"  Sedan (8L/100km) → <b>${gas_cost.get('cost', 0) * 8 / 12:.0f}/month</b>",
        ]
    else:
        lines.append("Gas price data unavailable this week.")

    if deals:
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "🛒 <b>Flyer deals near Mahogany</b>",
        ]
        for d in deals[:5]:
            savings_str = f" <i>was {d['savings']}</i>" if d.get("savings") else ""
            lines.append(f"  · <b>{d['store']}</b>: {_escape(d['item'])} — ${d['price']}{savings_str}")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 <b>3 ways to save this week</b>",
    ]
    for tip in tips:
        lines.append(f"  · {_escape(tip)}")

    lines += [
        "",
        f"💬 <b>Maya's take</b>",
        take,
        "",
        "#MahoganyCalgary #CalgaryLiving #CostOfLiving #YYC #CalgaryGas",
    ]

    return "\n".join(l for l in lines if l is not None)


# ── Telegram sender ───────────────────────────────────────────────────────────

def post_report(text: str) -> bool:
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={
            "chat_id":                  GROUP_ID,
            "message_thread_id":        NEWS_THREAD,
            "text":                     text[:4096],
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    result = resp.json()
    if result.get("ok"):
        logger.info(f"✅ Cost of living report posted → msg_id={result['result']['message_id']}")
        return True
    logger.error(f"❌ Error: {result.get('description')}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not can_run_bot("costofliving_report", min_interval_hours=20):
        return

    logger.info("Fetching gas prices (NRCan)…")
    gas = fetch_gas_prices()
    logger.info(f"  Calgary: {gas.get('calgary')}¢/L  Canada: {gas.get('canada')}¢/L  Trend: {gas.get('trend')}")

    logger.info("Fetching grocery flyer deals…")
    deals = fetch_nearby_flyers()
    logger.info(f"  Found {len(deals)} deals")

    text = build_report(gas, deals)

    logger.info("Posting cost of living report…")
    post_report(text)
    mark_bot_ran("costofliving_report")

    # Cache current prices for next week's trend comparison
    cache = _load_cache()
    cache["gas"] = {"calgary": gas.get("calgary"), "date": gas.get("last_date")}
    _save_cache(cache)

    logger.info("Done.")


if __name__ == "__main__":
    run()
