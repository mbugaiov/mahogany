"""
dedup.py — Deduplication store for posted articles + bot run-rate guard.

Tracks seen article URLs + title hashes in seen_articles.json.
Prevents reposting the same story even if it appears in multiple sources.

Also provides can_run_bot() / mark_bot_ran() to prevent report bots
from posting duplicates when triggered multiple times in a short window.
"""

import json
import hashlib
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from mahogany.config import data_path

logger = logging.getLogger(__name__)

STORE_FILE    = data_path("seen_articles.json")
BOT_RUN_FILE  = data_path("bot_runs.json")
MAX_AGE_DAYS  = 30   # purge article entries older than this

# High-signal event words: a single match is enough to consider articles duplicates
_HIGH_SIGNAL_EVENTS = {
    "explosion", "exploded", "explodes", "fire", "blaze", "burning",
    "flood", "flooding", "flooded", "drowning", "drowned", "drowns",
    "crash", "collision", "accident", "fatality", "fatal", "killed",
    "shooting", "stabbing", "murder", "homicide", "death", "deaths",
    "missing", "arrested", "charges", "evacuation", "emergency",
    "outbreak", "closure", "closed", "recall", "warning", "alert",
}

# Common words to ignore when extracting event keywords
_STOP_WORDS = {
    "a","an","the","in","on","at","to","of","for","and","or","but","is","are",
    "was","were","be","been","has","have","had","with","from","by","as","into",
    "after","before","about","up","out","its","it","this","that","they","their",
    "community","calgary","mahogany","yyc","news","local","new","one","two",
    "three","four","five","man","men","woman","women","person","people","says",
    "said","after","over","just","more","than","also","amid","amid","amid",
}


# ── Bot run-rate guard ────────────────────────────────────────────────────────

def _load_bot_runs() -> dict:
    if BOT_RUN_FILE.exists():
        try:
            return json.loads(BOT_RUN_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_bot_runs(runs: dict):
    BOT_RUN_FILE.write_text(json.dumps(runs, indent=2))


def can_run_bot(bot_name: str, min_interval_hours: float = 20) -> bool:
    """
    Return True if the bot is allowed to run now.
    Blocks if it already ran within `min_interval_hours`.
    """
    runs = _load_bot_runs()
    last_str = runs.get(bot_name)
    if not last_str:
        return True
    try:
        last = datetime.fromisoformat(last_str)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        if elapsed < min_interval_hours:
            logger.info(
                f"⏭  Skipping {bot_name} — already ran {elapsed:.1f}h ago "
                f"(min interval: {min_interval_hours}h)"
            )
            return False
    except Exception:
        pass
    return True


def mark_bot_ran(bot_name: str):
    """Record that the bot ran right now."""
    runs = _load_bot_runs()
    runs[bot_name] = datetime.now(timezone.utc).isoformat()
    _save_bot_runs(runs)
    logger.debug(f"Marked {bot_name} as ran at {runs[bot_name]}")


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _title_key(title: str) -> str:
    """Normalize title for fuzzy dedup (lowercase, strip punctuation)."""
    import re
    clean = re.sub(r"[^a-z0-9 ]", "", title.lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def _event_keywords(title: str) -> set[str]:
    """Extract significant event words from a title (for cross-source dedup)."""
    import re
    words = re.sub(r"[^a-zA-Z0-9 ]", " ", title.lower()).split()
    return {w for w in words if w not in _STOP_WORDS and len(w) > 3}


def _load() -> dict:
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save(store: dict):
    STORE_FILE.write_text(json.dumps(store, indent=2))


def _purge_old(store: dict) -> dict:
    """Remove entries older than MAX_AGE_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    return {k: v for k, v in store.items() if v.get("seen_at", "") >= cutoff}


def is_seen(url: str, title: str) -> bool:
    """
    Return True if this article has already been posted.
    Checks:
      1. Exact URL match
      2. Normalized title match
      3. Event-level match: >= 3 shared keywords with a recent post (last 3 days)
    """
    import re
    store = _load()

    # Fast checks first
    if _url_key(url) in store or _title_key(title) in store:
        return True

    # Event-level dedup: same incident covered by multiple sources
    my_keywords = _event_keywords(title)
    if len(my_keywords) < 2:
        return False

    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    for entry in store.values():
        if entry.get("seen_at", "") < cutoff:
            continue
        stored_keywords = set(entry.get("keywords", []))
        if not stored_keywords:
            continue
        overlap = my_keywords & stored_keywords
        if not overlap:
            continue
        # One high-signal event word is enough (explosion, fire, flood, etc.)
        high_signal_match = overlap & _HIGH_SIGNAL_EVENTS
        if high_signal_match or len(overlap) >= 2:
            logger.info(
                f"Event dedup: '{title[:50]}' matches '{entry.get('title','')[:50]}' "
                f"via keywords: {overlap}"
            )
            return True

    return False


def mark_seen(url: str, title: str, source: str = ""):
    """Mark an article as posted."""
    store = _load()
    now   = datetime.now(timezone.utc).isoformat()
    keywords = list(_event_keywords(title))

    store[_url_key(url)] = {
        "url":      url,
        "title":    title[:100],
        "source":   source,
        "seen_at":  now,
        "type":     "url",
        "keywords": keywords,
    }
    store[_title_key(title)] = {
        "url":      url,
        "title":    title[:100],
        "source":   source,
        "seen_at":  now,
        "type":     "title",
        "keywords": keywords,
    }

    store = _purge_old(store)
    _save(store)
    logger.debug(f"Marked as seen: {title[:60]}")


def stats() -> dict:
    store = _load()
    return {"total_keys": len(store), "file": str(STORE_FILE)}


if __name__ == "__main__":
    print(stats())
