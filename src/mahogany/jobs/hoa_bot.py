"""
hoa_bot.py — Monitor MahoganyHOA.com and post new updates to the HOA thread.

Sources (WordPress REST API):
  - "What's Up Mahogany?" bi-weekly newsletter  (cat 13)
  - Ice / Lake updates                           (cat 44)
  - Flooding updates                             (cat 43)
  - General news                                 (cat 11)

Run manually:  python3 hoa_bot.py --post N        (post N latest items)
Run as cron:   python3 hoa_bot.py                  (post only new items)
               python3 hoa_bot.py --create-topic   (create Telegram topic)
"""

from mahogany.config import data_path
import argparse
import html
import json
import logging
import os
import re
import sys
import time
import io
from datetime import datetime, timezone
from pathlib import Path

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

TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID   = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
HOA_THREAD = os.getenv("HOA_THREAD_ID", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
API_BASE   = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

MAYA_SYSTEM = """You are Maya — a warm, friendly local guide for Mahogany, Calgary.
You write for a Telegram community channel. Smart, concise, conversational English.
No corporate speak. Write like a helpful neighbour summarising HOA news for busy residents.
Plain text only — no markdown, no asterisks. Keep it to 2-3 sentences max."""

SEEN_FILE = data_path("hoa_seen.json")

# WordPress REST API
WP_API     = "https://mahoganyhoa.com/wp-json/wp/v2"
WP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MahoganyBot/1.0)"}

# Categories we care about (id → (label, emoji))
CATEGORIES = {
    13:  ("What's Up Mahogany?", "📰"),
    44:  ("Ice & Lake Update",   "❄️"),
    43:  ("Flooding Update",     "🌊"),
    11:  ("Community News",      "📢"),
    1:   ("HOA Update",          "🏘"),
}

HEADERS_HTTP = {"User-Agent": "Mozilla/5.0"}


# ── Seen tracking ─────────────────────────────────────────────────────────────

def _load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


# ── WordPress fetching ────────────────────────────────────────────────────────

def _clean_html(raw: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", "", raw or "")
    return html.unescape(text).strip()


def fetch_recent_posts(max_results: int = 20) -> list[dict]:
    """Fetch recent posts from all tracked HOA categories."""
    cat_ids = ",".join(str(c) for c in CATEGORIES)
    try:
        r = requests.get(
            f"{WP_API}/posts",
            params={
                "per_page":   max_results,
                "categories": cat_ids,
                "_fields":    "id,title,date,link,excerpt,content,categories,featured_media",
                "orderby":    "date",
                "order":      "desc",
            },
            headers=WP_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"HOA fetch failed: {e}")
        return []


def _gpt_summary(title: str, label: str, raw_text: str) -> str:
    """Ask GPT to write a 2-3 sentence resident-friendly summary of the HOA post."""
    # Trim raw text to avoid huge token usage
    content = raw_text[:1200].strip()
    if not content:
        return ""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": MAYA_SYSTEM},
                {"role": "user", "content": (
                    f"Summarise this HOA update for Mahogany residents in 2-3 sentences. "
                    f"Focus on what actually matters to people living here — dates, actions, impacts.\n\n"
                    f"Post type: {label}\n"
                    f"Title: {title}\n\n"
                    f"Content:\n{content}"
                )},
            ],
            max_tokens=120,
            temperature=0.6,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"GPT summary failed: {e}")
        return ""


def _fetch_image(media_id: int) -> str | None:
    """Get featured image URL for a post."""
    if not media_id:
        return None
    try:
        r = requests.get(
            f"{WP_API}/media/{media_id}",
            params={"_fields": "source_url"},
            headers=WP_HEADERS,
            timeout=10,
        )
        if r.ok:
            return r.json().get("source_url")
    except Exception:
        pass
    return None


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


# ── Formatting ────────────────────────────────────────────────────────────────

def format_post(post: dict) -> str:
    title    = _clean_html(post["title"]["rendered"])
    link     = post["link"]
    date_raw = post.get("date", "")
    cats     = post.get("categories", [])

    # Pick best matching category
    cat_id = next((c for c in cats if c in CATEGORIES), cats[0] if cats else 1)
    label, emoji = CATEGORIES.get(cat_id, ("HOA Update", "🏘"))

    # Format date
    try:
        dt = datetime.fromisoformat(date_raw)
        date_str = dt.strftime("%B %d, %Y")
    except Exception:
        date_str = date_raw[:10]

    # GPT summary from full post content
    raw_content = _clean_html(post.get("content", {}).get("rendered", "")) or \
                  _clean_html(post.get("excerpt", {}).get("rendered", ""))
    summary = _gpt_summary(title, label, raw_content)

    # Build message
    text = (
        f"{emoji} <b>{title}</b>\n"
        f"<i>{label}  ·  {date_str}</i>\n"
        f"\n"
    )

    if summary:
        text += f"{summary}\n\n"

    text += (
        f"🔗 <a href=\"{link}\">Read on MahoganyHOA.com</a>\n"
        f"\n"
        f"#MahoganyHOA #MahoganyCalgary #CommunityUpdates #YYC"
    )

    return text


# ── Posting ───────────────────────────────────────────────────────────────────

def post_hoa_update(post: dict) -> bool:
    if not HOA_THREAD:
        logger.error("HOA_THREAD_ID not set — run --create-topic first!")
        return False

    text = format_post(post)

    # Try to get featured image
    img_bytes = None
    media_id = post.get("featured_media")
    if media_id:
        img_url = _fetch_image(media_id)
        img_bytes = _download_image(img_url)

    if img_bytes:
        resp = requests.post(
            f"{API_BASE}/sendPhoto",
            data={
                "chat_id":           GROUP_ID,
                "message_thread_id": HOA_THREAD,
                "caption":           text[:1020],
                "parse_mode":        "HTML",
            },
            files={"photo": ("hoa.jpg", io.BytesIO(img_bytes), "image/jpeg")},
            timeout=30,
        )
    else:
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id":                GROUP_ID,
                "message_thread_id":      HOA_THREAD,
                "text":                   text[:4000],
                "parse_mode":             "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )

    result = resp.json()
    ok = result.get("ok", False)
    title = _clean_html(post["title"]["rendered"])
    if ok:
        msg_id = result.get("result", {}).get("message_id", "?")
        logger.info(f"✅ Posted: {title[:60]} → msg_id={msg_id}")
    else:
        logger.warning(f"❌ Failed: {result.get('description', '')} | {title[:40]}")
    return ok


def create_hoa_topic() -> int | None:
    """Create the HOA forum topic and return its thread ID."""
    resp = requests.post(
        f"{API_BASE}/createForumTopic",
        json={
            "chat_id":    GROUP_ID,
            "name":       "HOA Updates 🏘",
            "icon_color": 0xFF93B2,  # pink
        },
        timeout=15,
    )
    result = resp.json()
    if result.get("ok"):
        thread_id = result["result"]["message_thread_id"]
        logger.info(f"✅ Created 'HOA Updates 🏘' topic → thread_id={thread_id}")
        return thread_id
    else:
        logger.error(f"Failed to create topic: {result.get('description', '')}")
        return None


# ── Main logic ────────────────────────────────────────────────────────────────

MAX_PER_RUN = 3  # Max new posts per cycle (avoid flooding)


def run_check():
    """Fetch recent posts, post only new ones."""
    logger.info("Checking MahoganyHOA.com for new posts…")
    posts = fetch_recent_posts(max_results=20)
    if not posts:
        logger.info("No posts fetched.")
        return 0

    seen = _load_seen()
    new_posts = [p for p in posts if str(p["id"]) not in seen]
    new_posts = new_posts[:MAX_PER_RUN]

    if not new_posts:
        logger.info("No new HOA posts since last run.")
        return 0

    logger.info(f"Found {len(new_posts)} new posts. Posting to HOA thread…")
    posted = 0
    for post in reversed(new_posts):  # oldest first
        if post_hoa_update(post):
            posted += 1
            seen.add(str(post["id"]))
        time.sleep(3)

    _save_seen(seen)
    logger.info(f"Done. Posted {posted} HOA updates.")
    return posted


def run_manual_post(n: int):
    """Post N most recent HOA posts (ignores seen status)."""
    logger.info(f"Fetching {n} most recent HOA posts…")
    posts = fetch_recent_posts(max_results=n)
    if not posts:
        logger.warning("No posts found.")
        return

    # Welcome header
    requests.post(f"{API_BASE}/sendMessage", json={
        "chat_id":           GROUP_ID,
        "message_thread_id": HOA_THREAD,
        "text": (
            "🏘 <b>Mahogany HOA — Official Updates</b>\n"
            "News, newsletters and community announcements from "
            "<a href='https://mahoganyhoa.com'>MahoganyHOA.com</a>"
        ),
        "parse_mode":             "HTML",
        "disable_web_page_preview": True,
    }, timeout=10)
    time.sleep(2)

    seen = _load_seen()
    posted = 0
    for post in reversed(posts[:n]):  # oldest first
        title = _clean_html(post["title"]["rendered"])
        logger.info(f"Posting: {title[:70]}")
        if post_hoa_update(post):
            posted += 1
            seen.add(str(post["id"]))
        time.sleep(4)

    _save_seen(seen)
    logger.info(f"✅ Posted {posted}/{n} HOA updates.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post",         type=int, default=0,
                        help="Post N latest HOA items manually")
    parser.add_argument("--create-topic", action="store_true",
                        help="Create the HOA Updates forum topic")
    parser.add_argument("--check",        action="store_true",
                        help="Check for new posts only (default)")
    args = parser.parse_args()

    if args.create_topic:
        thread_id = create_hoa_topic()
        if thread_id:
            print(f"\nAdd to .env:\n  HOA_THREAD_ID={thread_id}")
    elif args.post:
        run_manual_post(args.post)
    else:
        run_check()
