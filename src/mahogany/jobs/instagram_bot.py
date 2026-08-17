"""
instagram_bot.py — Auto-post Mahogany Calgary content to Instagram.

Uses instagrapi (unofficial Instagram private API).
Session is cached to avoid re-login every run.

Content sources (mirrors Telegram bots):
  - New real estate listings (for sale)
  - New rental listings
  - News articles
  - Market report (weekly)
  - HOA updates
  - Insider tips

Run:
  python3 instagram_bot.py --post listing   # post 1 new listing
  python3 instagram_bot.py --post rental    # post 1 new rental
  python3 instagram_bot.py --post news      # post 1 news item
  python3 instagram_bot.py --post tip       # post 1 insider tip
  python3 instagram_bot.py --post market    # post market stats
  python3 instagram_bot.py                  # auto (rotate content types)
"""

import argparse
import io
import json
import logging
import os
import random
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from mahogany.config import data_path

import requests
from openai import OpenAI
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, BadPassword, TwoFactorRequired

from mahogany import config  # noqa: F401 — loads .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

IG_USERNAME  = os.getenv("INSTAGRAM_USERNAME", "mahogany.calgary")
IG_PASSWORD  = os.getenv("INSTAGRAM_PASSWORD", "")
OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")
SESSION_FILE = data_path("ig_session.json")
IG_SEEN_FILE = data_path("ig_seen.json")

_client_oai: OpenAI | None = None
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36"}


def _oai() -> OpenAI:
    global _client_oai
    if _client_oai is None:
        _client_oai = OpenAI(api_key=OPENAI_KEY or None)
    return _client_oai


# ── Instagram client ──────────────────────────────────────────────────────────

def get_ig_client() -> Client:
    """Return authenticated instagrapi Client, using cached session if available."""
    cl = Client()
    cl.delay_range = [2, 5]  # human-like delays between requests

    if SESSION_FILE.exists():
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(IG_USERNAME, IG_PASSWORD)
            logger.info("✅ Instagram: logged in via cached session")
            return cl
        except LoginRequired:
            logger.info("Session expired — re-logging in…")
            SESSION_FILE.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Session load failed: {e} — re-logging in…")
            SESSION_FILE.unlink(missing_ok=True)

    logger.info(f"Logging in to Instagram as @{IG_USERNAME}…")
    try:
        cl.login(IG_USERNAME, IG_PASSWORD)
        cl.dump_settings(SESSION_FILE)
        logger.info("✅ Instagram: logged in fresh, session saved")
        return cl
    except BadPassword:
        logger.error("❌ Instagram: wrong password")
        sys.exit(1)
    except TwoFactorRequired:
        logger.error("❌ Instagram: 2FA required — disable 2FA or handle manually")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Instagram login failed: {e}")
        sys.exit(1)


# ── Seen tracking ─────────────────────────────────────────────────────────────

def _load_ig_seen() -> set:
    if IG_SEEN_FILE.exists():
        try:
            return set(json.loads(IG_SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_ig_seen(seen: set):
    IG_SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def _is_ig_seen(key: str) -> bool:
    return key in _load_ig_seen()


def _mark_ig_seen(key: str):
    seen = _load_ig_seen()
    seen.add(key)
    _save_ig_seen(seen)


# ── Image helpers ─────────────────────────────────────────────────────────────

def _download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=15)
        if r.ok and "image" in r.headers.get("Content-Type", ""):
            return r.content
    except Exception as e:
        logger.debug(f"Image download failed: {e}")
    return None


def _save_temp_image(img_bytes: bytes) -> str:
    """Save image bytes to a temp file, return path. Caller must delete."""
    suffix = ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(img_bytes)
        return f.name


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


# ── GPT caption writer ────────────────────────────────────────────────────────

MAYA_IG_SYSTEM = """You are Maya — a warm local guide for Mahogany, Calgary.
You write Instagram captions for the @mahogany.calgary community account.

Primary voice: neighbourhood life — lake, pathways, Seton, family weekends,
seasonal living, quiet community tips. Real-estate listings are secondary,
never pushy sales copy.

Style: conversational, friendly, specific to SE Calgary / Mahogany. 2-4 sentences.
End with 5-8 relevant hashtags on a new line.
1-2 emojis max. Plain readable text."""


def _gpt_caption(prompt: str, max_tokens: int = 200) -> str:
    resp = _oai().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_IG_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.75,
    )
    return resp.choices[0].message.content.strip()


# ── Post types ────────────────────────────────────────────────────────────────

def post_listing(cl: Client) -> bool:
    """Post one new for-sale listing to Instagram."""
    from mahogany.scrapers.listings import fetch_mahogany_listings
    from mahogany.state.dedup import can_run_bot, mark_bot_ran

    listings = fetch_mahogany_listings(max_results=20)
    seen = _load_ig_seen()
    new = [l for l in listings if f"listing_{l['mls_id']}" not in seen]

    if not new:
        logger.info("No new listings to post to Instagram.")
        return False

    l = new[0]
    price  = f"${l['price']:,}"
    beds   = l.get("beds") or 0
    baths  = l.get("baths") or 0
    addr   = l["address"]
    url    = l["url"]

    caption = _gpt_caption(
        f"Write an Instagram caption for this Mahogany Calgary home for sale:\n"
        f"Address: {addr}\nPrice: {price}\nBeds: {beds} | Baths: {baths}\n"
        f"Type: {l.get('type','Home')}\nLink: {url}\n"
        f"Make it feel exciting but honest. Include the price and address."
    )

    # Real listing photo only — never invent homes with DALL·E (mahogany#9)
    img_bytes = _download_image(l.get("image_url"))
    if not img_bytes:
        logger.warning("No real listing photo — skipping Instagram listing post")
        return False

    img_path = _save_temp_image(img_bytes)
    try:
        cl.photo_upload(img_path, caption)
        logger.info(f"✅ Instagram: posted listing {addr} {price}")
        _mark_ig_seen(f"listing_{l['mls_id']}")
        return True
    except Exception as e:
        logger.error(f"❌ Instagram post failed: {e}")
        return False
    finally:
        Path(img_path).unlink(missing_ok=True)


def post_rental(cl: Client) -> bool:
    """Post one new rental listing to Instagram."""
    from mahogany.scrapers.rentals import fetch_mahogany_rentals

    listings = fetch_mahogany_rentals(max_results=20)
    seen = _load_ig_seen()
    new = [l for l in listings if f"rental_{l['id']}" not in seen]

    if not new:
        logger.info("No new rentals to post to Instagram.")
        return False

    l = new[0]
    rent  = f"${l['rent']:,}/mo"
    beds  = l.get("beds") or 0
    addr  = l["address"]
    url   = l["url"]

    caption = _gpt_caption(
        f"Write an Instagram caption for this Mahogany Calgary rental:\n"
        f"Address: {addr}\nRent: {rent}\nBeds: {beds}\n"
        f"Type: {l.get('type','Rental')}\nLink: {url}\n"
        f"Make it feel helpful and direct. Include rent price."
    )

    img_bytes = _download_image(l.get("image_url"))
    if not img_bytes:
        logger.warning("No real rental photo — skipping Instagram rental post")
        return False

    img_path = _save_temp_image(img_bytes)
    try:
        cl.photo_upload(img_path, caption)
        logger.info(f"✅ Instagram: posted rental {addr} {rent}")
        _mark_ig_seen(f"rental_{l['id']}")
        return True
    except Exception as e:
        logger.error(f"❌ Instagram post failed: {e}")
        return False
    finally:
        Path(img_path).unlink(missing_ok=True)


def post_insider_tip(cl: Client) -> bool:
    """Post community / lifestyle tip (primary Instagram theme)."""
    season_map = {
        1:"winter",2:"winter",3:"early spring",4:"spring",5:"spring",
        6:"summer",7:"summer",8:"summer",9:"fall",10:"fall",11:"fall",12:"winter"
    }
    season = season_map.get(datetime.now().month, "spring")

    tip_types = [
        f"Write a short Mahogany lake / boardwalk tip for {season} in SE Calgary. "
        "Specific and useful for residents — not a real-estate ad. Under 3 sentences.",
        f"Write a pathways / walkability tip for Mahogany + nearby Seton in {season}. "
        "Something a local would actually do this week. Under 3 sentences.",
        f"Write a family weekend idea in or near Mahogany for {season} "
        "(lake, parks, Seton amenities). Warm community voice. Under 3 sentences.",
        f"Write a 'new to Mahogany' settling-in tip for {season} — "
        "neighbours, quiet streets, daily life — not homebuying advice. Under 3 sentences.",
        f"Write a seasonal living tip for Mahogany Calgary in {season} "
        "(weather, lake freeze/thaw, evening walks). Under 3 sentences.",
    ]
    prompt = random.choice(tip_types)
    caption = _gpt_caption(prompt)

    from mahogany.content.real_media import fetch_real_listing_image

    img_bytes, _listing = fetch_real_listing_image(prefer="any")
    if not img_bytes:
        logger.warning("No real listing photo for tip — skipping (no AI homes)")
        return False

    img_path = _save_temp_image(img_bytes)
    try:
        cl.photo_upload(img_path, caption)
        logger.info("✅ Instagram: posted insider tip")
        return True
    except Exception as e:
        logger.error(f"❌ Instagram post failed: {e}")
        return False
    finally:
        Path(img_path).unlink(missing_ok=True)


def post_market_snapshot(cl: Client) -> bool:
    """Post a quick market stats snapshot."""
    from mahogany.scrapers.listings import fetch_mahogany_listings
    from statistics import median, mean

    listings = fetch_mahogany_listings(max_results=40)
    if not listings:
        return False

    prices = [l["price"] for l in listings if l.get("price", 0) > 50_000]
    if not prices:
        return False

    med  = int(median(prices))
    avg  = int(mean(prices))
    total = len(listings)
    new_7d = len([l for l in listings if l.get("days_on_market", 999) <= 7])

    caption = _gpt_caption(
        f"Write an Instagram caption for a Mahogany Calgary real estate market update:\n"
        f"Active listings: {total}\nNew this week: {new_7d}\n"
        f"Median price: ${med:,}\nAvg price: ${avg:,}\n"
        f"Make it informative and engaging for homebuyers and investors.",
        max_tokens=180,
    )

    from mahogany.content.real_media import fetch_real_listing_image

    # Prefer photo from the live set we just scraped
    img_bytes = None
    for l in listings:
        img_bytes = _download_image(l.get("image_url"))
        if img_bytes:
            break
    if not img_bytes:
        img_bytes, _ = fetch_real_listing_image(prefer="sale")
    if not img_bytes:
        logger.warning("No real listing photo for market snapshot — skipping")
        return False

    img_path = _save_temp_image(img_bytes)
    try:
        cl.photo_upload(img_path, caption)
        logger.info(f"✅ Instagram: posted market snapshot (median ${med:,})")
        return True
    except Exception as e:
        logger.error(f"❌ Instagram post failed: {e}")
        return False
    finally:
        Path(img_path).unlink(missing_ok=True)


# ── Auto rotation ─────────────────────────────────────────────────────────────

# Community/lifestyle first; listings & rentals secondary (was listing-heavy).
ROTATION = [
    "tip",
    "tip",
    "listing",
    "tip",
    "rental",
    "tip",
    "market",
    "tip",
]
ROTATION_FILE = data_path("ig_rotation.json")


def _next_post_type() -> str:
    if ROTATION_FILE.exists():
        try:
            data = json.loads(ROTATION_FILE.read_text())
            idx = (data.get("idx", 0) + 1) % len(ROTATION)
        except Exception:
            idx = 0
    else:
        idx = 0
    ROTATION_FILE.write_text(json.dumps({"idx": idx}))
    return ROTATION[idx]


# ── Main ──────────────────────────────────────────────────────────────────────

def run(post_type: str = "auto", *, force: bool = False) -> bool:
    from mahogany.state.dedup import can_run_bot, mark_bot_ran

    if not force and not can_run_bot("instagram_bot", min_interval_hours=3):
        return False

    cl = get_ig_client()

    if post_type == "auto":
        post_type = _next_post_type()

    logger.info(f"Instagram: posting type '{post_type}'…")

    ok = False
    if post_type == "listing":
        ok = post_listing(cl)
    elif post_type == "rental":
        ok = post_rental(cl)
    elif post_type in {"tip", "community"}:
        ok = post_insider_tip(cl)
    elif post_type == "market":
        ok = post_market_snapshot(cl)
    else:
        logger.warning(f"Unknown post type: {post_type}")

    if ok:
        mark_bot_ran("instagram_bot")
    logger.info("Done.")
    return ok


def main(argv: list[str] | None = None) -> None:
    """CLI entry for `mahogany instagram` (required by mahogany.cli)."""
    parser = argparse.ArgumentParser(prog="instagram")
    parser.add_argument(
        "--post",
        choices=["listing", "rental", "tip", "community", "market", "auto"],
        default="auto",
        help="What to post (default: auto-rotate; tip/community = lifestyle)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass min-interval guard (manual / smoke posts)",
    )
    args = parser.parse_args(argv)
    ok = run(post_type=args.post, force=args.force)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
