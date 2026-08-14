"""
scraper.py — Multi-source news scraper for Mahogany, Calgary.

Sources:
  1. Google News RSS  (broadest coverage)
  2. Reddit r/Calgary (community voice)
  3. CBC Calgary      (local CBC)
  4. CTV News Calgary (local CTV)
  5. Calgary Herald   (local Herald)

Returns a list of Article dicts:
  {
    "title":     str,
    "url":       str,
    "source":    str,
    "published": datetime | None,
    "summary":   str,          # raw excerpt / description
    "image_url": str | None,
  }
"""

import re
import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

import socket
import feedparser
import requests
from bs4 import BeautifulSoup

# Global socket timeout prevents feedparser from hanging indefinitely
socket.setdefaulttimeout(8)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 8

# Must match BOTH "mahogany" AND a Calgary/neighbourhood context signal
KEYWORDS_PRIMARY   = ["mahogany"]
KEYWORDS_CONTEXT   = ["calgary", "yyc", "calgary se", "se calgary", "lake mahogany",
                       "mahogany lake", "mahogany village", "mahogany beach",
                       "mahogany community", "hopewell", "jayman", "genstar"]
KEYWORDS_DIRECT    = ["mahogany calgary", "mahogany lake calgary",
                       "mahogany village market", "mahogany beach club"]


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    summary: str = ""
    image_url: Optional[str] = None

    def is_relevant(self) -> bool:
        """
        True if the article is about Mahogany the Calgary neighbourhood.
        Requires 'mahogany' PLUS a Calgary/community context signal,
        OR one of the direct compound phrases.
        """
        haystack = (self.title + " " + self.summary + " " + self.url).lower()
        # Direct compound phrases are sufficient on their own
        if any(phrase in haystack for phrase in KEYWORDS_DIRECT):
            return True
        # Otherwise need both primary + context
        has_primary = any(kw in haystack for kw in KEYWORDS_PRIMARY)
        has_context = any(kw in haystack for kw in KEYWORDS_CONTEXT)
        return has_primary and has_context

    def to_dict(self) -> dict:
        return {
            "title":     self.title,
            "url":       self.url,
            "source":    self.source,
            "published": self.published.isoformat() if self.published else None,
            "summary":   self.summary,
            "image_url": self.image_url,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_rss_date(entry) -> Optional[datetime]:
    """Parse feedparser published_parsed into aware datetime."""
    t = entry.get("published_parsed")
    if t:
        try:
            return datetime(*t[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _extract_image_from_html(html: str) -> Optional[str]:
    """Try to find the main article image from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")
    # og:image is the most reliable
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"]
    # Twitter card
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return tw["content"]
    # First <img> with a src that looks like a photo
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("http") and any(ext in src for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return src
    return None


_BAD_IMAGE_DOMAINS = (
    "news.google.com",
    "google.com/s2",
    "gstatic.com",
    "googleusercontent.com",
    "facebook.com/tr",
    "pixel",
    "1x1",
    "spacer",
    "logo",
    "icon",
)


def _is_bad_image(url: str) -> bool:
    """Return True if this URL is a logo / tracker / news-aggregator icon."""
    if not url:
        return True
    url_lower = url.lower()
    return any(bad in url_lower for bad in _BAD_IMAGE_DOMAINS)


def _decode_google_news_url(encoded: str) -> Optional[str]:
    """
    Decode a Google News article token (CBMi...) to the real article URL.
    Google News embeds the URL as a protobuf field inside a base64url payload.
    """
    import base64
    try:
        # Strip URL prefix, keep only the base64url token
        token = encoded.split("/rss/articles/")[-1].split("?")[0]
        # Pad to multiple of 4
        token += "=" * (-len(token) % 4)
        data = base64.urlsafe_b64decode(token)
        # Scan for https:// in the bytes (URL is a protobuf string field)
        idx = data.find(b"https://")
        if idx == -1:
            idx = data.find(b"http://")
        if idx != -1:
            # Read until a non-printable character that isn't part of a URL
            end = idx
            while end < len(data) and data[end] >= 0x20 and data[end] < 0x7F:
                end += 1
            candidate = data[idx:end].decode("ascii", errors="ignore").strip()
            # Sanity check
            if candidate.startswith("http") and "." in candidate and len(candidate) > 15:
                return candidate
    except Exception:
        pass
    return None


def _resolve_google_news_url(url: str) -> str:
    """Decode Google News encoded URL to the real article URL."""
    if "news.google.com" not in url:
        return url
    # Try protobuf decoding first (no HTTP request needed)
    decoded = _decode_google_news_url(url)
    if decoded:
        return decoded
    # Fallback: follow HTTP redirect
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if "news.google.com" not in r.url:
            return r.url
    except Exception:
        pass
    return url


def _fetch_image(url: str) -> Optional[str]:
    """Fetch page HTML and extract image URL. Follows Google News redirects."""
    try:
        real_url = _resolve_google_news_url(url)
        r = requests.get(real_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.ok:
            img = _extract_image_from_html(r.text)
            if img and not _is_bad_image(img):
                return img
    except Exception as e:
        logger.debug(f"Image fetch failed for {url}: {e}")
    return None


def _clean_summary(raw: str) -> str:
    """Strip HTML tags and excessive whitespace from a summary."""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()[:500]


# ── Source scrapers ───────────────────────────────────────────────────────────

def scrape_google_news() -> list[Article]:
    """Google News RSS — broad English-language coverage."""
    url = (
        "https://news.google.com/rss/search"
        '?q="mahogany"+calgary+neighbourhood'
        "&hl=en-CA&gl=CA&ceid=CA:en"
    )
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            # Google News wraps source in title like "Title - Source"
            title = entry.get("title", "")
            source_match = re.search(r" - ([^-]+)$", title)
            source = source_match.group(1).strip() if source_match else "Google News"
            clean_title = re.sub(r" - [^-]+$", "", title).strip()

            summary = _clean_summary(entry.get("summary", ""))

            # Google News links redirect — resolve to real URL immediately
            raw_link = entry.get("link", "")
            real_link = _resolve_google_news_url(raw_link) if raw_link else raw_link

            # Never use images from the RSS entry for Google News (they're logos)
            art = Article(
                title=clean_title or title,
                url=real_link,
                source=source,
                published=_parse_rss_date(entry),
                summary=summary,
                image_url=None,  # will be fetched from real article page
            )
            if art.is_relevant():
                articles.append(art)
    except Exception as e:
        logger.warning(f"Google News scrape failed: {e}")
    logger.info(f"Google News: {len(articles)} relevant articles")
    return articles


def scrape_reddit() -> list[Article]:
    """Reddit r/Calgary — community posts about Mahogany."""
    url = (
        "https://www.reddit.com/r/Calgary/search.json"
        "?q=mahogany+neighbourhood&sort=new&t=month&limit=25&restrict_sr=1"
    )
    articles = []
    try:
        r = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=TIMEOUT)
        if not r.ok:
            return articles
        data = r.json()
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            title   = p.get("title", "")
            link    = "https://reddit.com" + p.get("permalink", "")
            selftext = p.get("selftext", "")[:400]
            created = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)

            # Image: Reddit preview (high-res) preferred over thumbnail
            img = None
            preview = p.get("preview", {})
            images  = preview.get("images", [])
            if images:
                candidate = images[0].get("source", {}).get("url", "").replace("&amp;", "&")
                if candidate and not _is_bad_image(candidate):
                    img = candidate
            if not img:
                thumb = p.get("thumbnail", "")
                if thumb.startswith("http") and not _is_bad_image(thumb):
                    img = thumb

            art = Article(
                title=title,
                url=link,
                source="Reddit r/Calgary",
                published=created,
                summary=selftext or title,
                image_url=img,
            )
            if art.is_relevant():
                articles.append(art)
    except Exception as e:
        logger.warning(f"Reddit scrape failed: {e}")
    logger.info(f"Reddit: {len(articles)} relevant posts")
    return articles


def scrape_cbc_calgary() -> list[Article]:
    """CBC Calgary RSS feed."""
    url = "https://www.cbc.ca/cmlink/rss-canada-calgary"
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:30]:
            title   = entry.get("title", "")
            summary = _clean_summary(entry.get("summary", ""))
            art = Article(
                title=title,
                url=entry.get("link", ""),
                source="CBC Calgary",
                published=_parse_rss_date(entry),
                summary=summary,
            )
            if art.is_relevant():
                articles.append(art)
    except Exception as e:
        logger.warning(f"CBC Calgary scrape failed: {e}")
    logger.info(f"CBC Calgary: {len(articles)} relevant articles")
    return articles


def scrape_ctv_calgary() -> list[Article]:
    """CTV News Calgary RSS."""
    url = "https://calgary.ctvnews.ca/rss/ctv-news-calgary-1.822292"
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:30]:
            title   = entry.get("title", "")
            summary = _clean_summary(entry.get("summary", ""))
            art = Article(
                title=title,
                url=entry.get("link", ""),
                source="CTV News Calgary",
                published=_parse_rss_date(entry),
                summary=summary,
            )
            if art.is_relevant():
                articles.append(art)
    except Exception as e:
        logger.warning(f"CTV Calgary scrape failed: {e}")
    logger.info(f"CTV Calgary: {len(articles)} relevant articles")
    return articles


def scrape_calgary_herald() -> list[Article]:
    """Calgary Herald RSS — real estate and community news."""
    urls = [
        "https://calgaryherald.com/feed",
        "https://calgaryherald.com/category/news/local-news/feed",
    ]
    articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                title   = entry.get("title", "")
                summary = _clean_summary(entry.get("summary", ""))
                art = Article(
                    title=title,
                    url=entry.get("link", ""),
                    source="Calgary Herald",
                    published=_parse_rss_date(entry),
                    summary=summary,
                )
                if art.is_relevant():
                    articles.append(art)
        except Exception as e:
            logger.warning(f"Calgary Herald scrape failed ({url}): {e}")
    logger.info(f"Calgary Herald: {len(articles)} relevant articles")
    return articles


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_all_articles(fetch_images: bool = True) -> list[Article]:
    """
    Run all scrapers, merge results, deduplicate by URL.
    Optionally fetch full-page images for articles missing them.
    """
    all_articles: list[Article] = []

    scrapers = [
        scrape_google_news,
        scrape_reddit,
        scrape_cbc_calgary,
        scrape_ctv_calgary,
        scrape_calgary_herald,
    ]

    for scraper in scrapers:
        try:
            all_articles.extend(scraper())
        except Exception as e:
            logger.error(f"Scraper {scraper.__name__} crashed: {e}")
        time.sleep(0.5)  # polite delay

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[Article] = []
    for art in all_articles:
        if art.url not in seen_urls:
            seen_urls.add(art.url)
            unique.append(art)

    # Sort by published date (newest first)
    unique.sort(key=lambda a: a.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    # Fetch missing or bad images — for top 10 articles
    if fetch_images:
        for art in unique[:10]:
            if (not art.image_url or _is_bad_image(art.image_url)) and art.url.startswith("http"):
                try:
                    art.image_url = _fetch_image(art.url)
                except Exception:
                    pass
                time.sleep(0.3)

    logger.info(f"Total unique relevant articles: {len(unique)}")
    return unique


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    articles = fetch_all_articles()
    for a in articles:
        print(f"\n{'='*60}")
        print(f"[{a.source}] {a.title}")
        print(f"URL: {a.url}")
        print(f"Published: {a.published}")
        print(f"Image: {a.image_url}")
        print(f"Summary: {a.summary[:120]}…")
