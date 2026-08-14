"""
poster.py — Telegram poster for @mahogany_calgary.

Supports:
  - post to channel (@mahogany_calgary)
  - post to a forum thread (News thread in community group, for preview/review)
  - DALL-E image generation when article has no image
  - sendPhoto with caption, fallback to sendMessage
"""

import io
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BOT_TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID             = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
NEWS_THREAD_ID       = os.getenv("NEWS_THREAD_ID", "6")
REALESTATE_THREAD_ID = os.getenv("REALESTATE_THREAD_ID", "56")
PREVIEW_CHAT_ID      = os.getenv("PREVIEW_CHAT_ID", GROUP_ID)
PREVIEW_THREAD_ID    = os.getenv("PREVIEW_THREAD_ID", NEWS_THREAD_ID)
# Legacy alias
CHANNEL              = GROUP_ID
API_BASE             = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 20


class PostingError(Exception):
    pass


def _download_image(url: str) -> bytes | None:
    """Download image bytes from URL. Returns None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
        content_type = r.headers.get("Content-Type", "")
        if r.ok and "image" in content_type:
            data = r.content
            if len(data) < 10 * 1024 * 1024:  # Telegram limit: 10 MB
                return data
            logger.debug(f"Image too large ({len(data)} bytes): {url}")
        else:
            logger.debug(f"Bad image response: {r.status_code} {content_type} {url[:80]}")
    except Exception as e:
        logger.debug(f"Failed to download image {url}: {e}")
    return None


def _get_image_bytes(image_url: str | None, article_title: str = "", pillar: str = "community") -> bytes | None:
    """
    Get image bytes: try original URL first, fall back to DALL-E generation.
    """
    # 1. Try the scraped image URL
    if image_url:
        data = _download_image(image_url)
        if data:
            return data
        logger.info("Original image failed, falling back to DALL-E…")

    # 2. DALL-E fallback
    try:
        from mahogany.content.image_gen import generate_image
        return generate_image(article_title, pillar)
    except Exception as e:
        logger.warning(f"DALL-E fallback failed: {e}")
        return None


def _truncate_caption(text: str, max_len: int = 1020) -> str:
    """Truncate to Telegram caption limit, keeping hashtags intact."""
    if len(text) <= max_len:
        return text
    parts = text.rsplit("\n\n", 1)
    if len(parts) == 2 and parts[1].startswith("#"):
        body, tags = parts
        available = max_len - len(tags) - 6
        return body[:available].rstrip() + "…\n\n" + tags
    return text[:max_len - 1] + "…"


def _send_photo(chat_id: str, caption: str, img_bytes: bytes,
                thread_id: str | None = None) -> dict:
    data = {
        "chat_id":    chat_id,
        "caption":    _truncate_caption(caption),
        "parse_mode": "HTML",
    }
    if thread_id:
        data["message_thread_id"] = thread_id

    resp = requests.post(
        f"{API_BASE}/sendPhoto",
        data=data,
        files={"photo": ("image.jpg", io.BytesIO(img_bytes), "image/jpeg")},
        timeout=30,
    )
    return resp.json()


def _send_message(chat_id: str, text: str, thread_id: str | None = None) -> dict:
    # Suppress link preview if URL is a news aggregator (shows logo instead of article)
    bad_preview_domains = ("news.google.com", "google.com/rss", "reddit.com/r/")
    suppress_preview = any(d in text for d in bad_preview_domains)

    payload = {
        "chat_id":                  chat_id,
        "text":                     text[:4090],
        "parse_mode":               "HTML",
        "disable_web_page_preview": suppress_preview,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json=payload,
        timeout=20,
    )
    if not resp.ok:
        raise PostingError(f"sendMessage failed {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def post_article(
    full_text: str,
    image_url: str | None = None,
    article_title: str = "",
    pillar: str = "community",
    preview: bool = False,
    thread_id_override: str | None = None,
) -> dict:
    """
    Post an article to the group.

    Args:
        full_text:          Formatted HTML text.
        image_url:          Scraped image URL (may be None or broken).
        article_title:      Used for DALL-E fallback prompt.
        pillar:             Content pillar (affects DALL-E style).
        preview:            If True, post to preview/News thread (no dedup mark).
        thread_id_override: Force a specific thread_id (e.g. for Real Estate thread).

    Returns:
        Telegram API response dict.
    """
    # Determine destination thread
    if thread_id_override:
        chat_id   = GROUP_ID
        thread_id = thread_id_override
        dest_label = f"thread={thread_id}"
    elif preview:
        chat_id   = PREVIEW_CHAT_ID or GROUP_ID
        thread_id = PREVIEW_THREAD_ID or NEWS_THREAD_ID
        dest_label = f"preview thread={thread_id}"
    else:
        # Default: post to News thread
        chat_id   = GROUP_ID
        thread_id = NEWS_THREAD_ID
        dest_label = f"News thread={thread_id}"

    # Get image
    img_bytes = _get_image_bytes(image_url, article_title, pillar)

    if img_bytes:
        result = _send_photo(chat_id, full_text, img_bytes, thread_id)
        if result.get("ok"):
            logger.info(f"Photo posted to {dest_label}")
            return result
        logger.warning(f"sendPhoto failed, falling back to text: {result.get('description','')}")

    # Fallback: text post
    result = _send_message(chat_id, full_text, thread_id)
    logger.info(f"Text post sent to {dest_label}")
    return result


def send_text_post(text: str, preview: bool = False,
                   thread_id_override: str | None = None) -> dict:
    """Send a plain text post (defaults to News thread)."""
    if thread_id_override:
        return _send_message(GROUP_ID, text, thread_id_override)
    if preview:
        return _send_message(PREVIEW_CHAT_ID or GROUP_ID, text,
                             PREVIEW_THREAD_ID or NEWS_THREAD_ID)
    # Default: News thread
    return _send_message(GROUP_ID, text, NEWS_THREAD_ID)


def send_to_realestate(text: str, img_bytes: bytes | None = None) -> dict:
    """Post directly to Real Estate thread."""
    if img_bytes:
        return _send_photo(GROUP_ID, text, img_bytes, REALESTATE_THREAD_ID)
    return _send_message(GROUP_ID, text, REALESTATE_THREAD_ID)


def send_admin_message(text: str, admin_chat_id: str | None = None):
    """Send a notification to the admin (not the channel)."""
    chat_id = admin_chat_id or os.getenv("ADMIN_CHAT_ID")
    if not chat_id:
        return
    requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"},
        timeout=10,
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    mode = sys.argv[1] if len(sys.argv) > 1 else "channel"
    preview = mode == "preview"
    test_text = (
        "<b>🏡 Mahogany Bot — Test Post</b>\n\n"
        "Testing image generation + posting pipeline.\n"
        "Beautiful lakeside living in SE Calgary! 🌊\n\n"
        "📰 <a href='https://mahogany.ca'>Mahogany</a>\n\n"
        "#Mahogany #MahoganyCalgary #Calgary #YYC"
    )
    print(f"Posting to {'preview thread' if preview else 'channel'}…")
    result = post_article(test_text, image_url=None,
                          article_title="Mahogany lakeside community Calgary",
                          pillar="lake", preview=preview)
    print(f"Result: ok={result.get('ok')} id={result.get('result',{}).get('message_id')}")
