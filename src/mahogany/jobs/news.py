#!/usr/bin/env python3
"""
main.py — Mahogany Calgary Telegram Channel Bot
================================================
Scrapes news about Mahogany, Calgary → generates SMM content → posts to @mahogany_calgary.

Usage:
  python3 main.py                  # run one cycle (scrape → generate → post up to MAX_POSTS)
  python3 main.py --dry-run        # scrape + generate but DON'T post (preview only)
  python3 main.py --force 3        # force post N articles (ignore dedup, for testing)
  python3 main.py --original       # generate + post one original (non-news) creative post
  python3 main.py --original did_you_know  # specific type: did_you_know|insider_tip|comparison|seasonal|investment_angle
  python3 main.py --test           # post one test message to verify bot/channel connection
"""

from mahogany.config import data_path
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from mahogany import config  # noqa: F401 — loads .env

from mahogany.scrapers.news import fetch_all_articles, Article
from mahogany.content.content_gen import generate_post
from mahogany.content.original_content import generate_original, CONTENT_TYPES
from mahogany.telegram.poster import post_article, send_text_post, send_admin_message
from mahogany.state.dedup import is_seen, mark_seen, stats as dedup_stats

# ── Config ─────────────────────────────────────────────────────────────────────
MAX_POSTS_PER_RUN    = 2          # max news articles to post per scheduled run
DELAY_BETWEEN_POSTS  = 30        # seconds between posts (avoid Telegram flood)
# Set PREVIEW_CHAT_ID + PREVIEW_THREAD_ID in .env to enable preview-to-thread mode
LOG_FILE = data_path("mahogany.log")
ADMIN_CHAT_ID        = os.getenv("ADMIN_CHAT_ID", "504840411")

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_news_cycle(dry_run: bool = False, force: int = 0, preview: bool = False) -> int:
    """Scrape → generate → post news articles. Returns number posted."""
    logger.info("─" * 60)
    dest = "PREVIEW thread" if preview else "channel"
    logger.info(f"Mahogany Bot — news cycle → {dest} {'[DRY RUN]' if dry_run else ''}")
    logger.info(f"Dedup store: {dedup_stats()}")

    # 1. Scrape
    logger.info("Fetching articles from all sources…")
    try:
        articles = fetch_all_articles(fetch_images=True)
    except Exception as e:
        logger.error(f"Scraper failed: {e}")
        send_admin_message(f"⚠️ Mahogany Bot scraper error:\n<code>{e}</code>", ADMIN_CHAT_ID)
        return 0

    logger.info(f"Found {len(articles)} relevant articles total")

    # 2. Filter already-seen
    if not force:
        new_articles = [a for a in articles if not is_seen(a.url, a.title)]
        logger.info(f"{len(new_articles)} new (unseen) articles")
    else:
        new_articles = articles[:force]
        logger.info(f"FORCE mode: using first {len(new_articles)} articles")

    if not new_articles:
        logger.info("No new news articles — posting original content instead")
        return run_original_cycle(dry_run=dry_run, preview=preview)

    # 3. Generate + post
    posted = 0
    limit  = force if force else MAX_POSTS_PER_RUN

    for article in new_articles[:limit * 4]:
        if posted >= limit:
            break

        logger.info(f"Processing: [{article.source}] {article.title[:80]}")

        try:
            post = generate_post(article.to_dict())
        except Exception as e:
            logger.warning(f"GPT generation failed, skipping: {e}")
            continue

        if post.skipped:
            logger.info("  → GPT flagged as irrelevant, skipping")
            continue

        logger.info(f"  → Pillar: {post.pillar} | {len(post.full_text)} chars")
        for line in post.full_text.splitlines():
            logger.info(f"     {line}")

        if dry_run:
            logger.info("  → DRY RUN: not posting")
            posted += 1
            continue

        try:
            result = post_article(
                post.full_text,
                image_url=article.image_url,
                article_title=article.title,
                pillar=post.pillar,
                preview=preview,
            )
            if result.get("ok"):
                msg_id = result.get("result", {}).get("message_id", "?")
                logger.info(f"  → ✅ Posted! message_id={msg_id}")
                if not preview:   # only mark seen when posting to real channel
                    mark_seen(article.url, article.title, article.source)
                posted += 1
            else:
                logger.warning(f"  → ❌ Telegram error: {result}")
        except Exception as e:
            logger.error(f"  → Post failed: {e}")
            continue

        if posted < limit:
            logger.info(f"  Waiting {DELAY_BETWEEN_POSTS}s before next post…")
            time.sleep(DELAY_BETWEEN_POSTS)

    logger.info(f"News cycle complete. Posted {posted} article(s).")
    return posted


def run_original_cycle(content_type: str = None, dry_run: bool = False, preview: bool = False) -> int:
    """Generate and post one original (non-news) creative post."""
    logger.info("─" * 60)
    dest = "PREVIEW thread" if preview else "channel"
    logger.info(f"Mahogany Bot — original content → {dest} {'[DRY RUN]' if dry_run else ''} type={content_type or 'random'}")

    try:
        text = generate_original(content_type)
    except Exception as e:
        logger.error(f"Original content generation failed: {e}")
        return 0

    logger.info(f"Generated original post ({len(text)} chars):")
    for line in text.splitlines():
        logger.info(f"  {line}")

    if dry_run:
        logger.info("DRY RUN — not posting")
        return 1

    # Generate a DALL-E image for original posts too
    pillar_map = {
        "did_you_know": "lake",
        "insider_tip": "community",
        "comparison": "realestate",
        "seasonal": "lake",
        "investment_angle": "realestate",
    }
    pillar = pillar_map.get(content_type or "", "community")

    try:
        from mahogany.content.image_gen import generate_image
        img_bytes = generate_image(text[:100], pillar)
    except Exception:
        img_bytes = None

    try:
        if img_bytes:
            from mahogany.telegram.poster import _send_photo, CHANNEL, PREVIEW_CHAT_ID, PREVIEW_THREAD_ID
            chat_id   = PREVIEW_CHAT_ID if (preview and PREVIEW_CHAT_ID) else CHANNEL
            thread_id = PREVIEW_THREAD_ID if (preview and PREVIEW_CHAT_ID) else None
            result    = _send_photo(chat_id, text, img_bytes, thread_id)
        else:
            result = send_text_post(text, preview=preview)

        if result.get("ok"):
            logger.info(f"✅ Original post sent! message_id={result['result']['message_id']}")
            return 1
        else:
            logger.warning(f"❌ Telegram error: {result}")
            return 0
    except Exception as e:
        logger.error(f"Post failed: {e}")
        return 0


def run_test():
    """Send a test message to verify bot → channel connection."""
    logger.info("Sending test message to channel…")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    test_text = (
        f"<b>🏡 Mahogany Bot — Connection Test</b>\n\n"
        f"✅ Bot is running and connected to the channel!\n"
        f"🕐 Time: {now}\n\n"
        f"#Mahogany #MahoganyCalgary #Calgary #YYC"
    )
    result = send_text_post(test_text)
    if result.get("ok"):
        print(f"✅ Test message sent! message_id={result['result']['message_id']}")
    else:
        print(f"❌ Failed: {result}")


def main():
    parser = argparse.ArgumentParser(description="Mahogany Calgary Telegram Bot")
    parser.add_argument("--dry-run",  action="store_true", help="Generate but don't post")
    parser.add_argument("--force",    type=int, default=0, help="Force-post N news articles")
    parser.add_argument("--preview",  action="store_true",
                        help="Post to News thread in community group (for review), not the channel")
    parser.add_argument("--original", nargs="?", const="random", default=None,
                        metavar="TYPE",
                        help=f"Post original content. Types: {', '.join(CONTENT_TYPES)}, or omit for random")
    parser.add_argument("--test",     action="store_true", help="Send test message to channel")
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    if args.original is not None:
        content_type = None if args.original == "random" else args.original
        run_original_cycle(content_type=content_type, dry_run=args.dry_run, preview=args.preview)
        return

    run_news_cycle(dry_run=args.dry_run, force=args.force, preview=args.preview)


if __name__ == "__main__":
    main()
