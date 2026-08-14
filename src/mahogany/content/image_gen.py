"""
image_gen.py — DALL-E image generation fallback for Mahogany bot.

When a news article has no usable photo, this module generates a relevant,
beautiful image using DALL-E 3 (standard quality, 1024x1024).

Cost: ~$0.04/image (standard). Cached to disk to avoid re-generating same topic.
"""

from mahogany.config import data_path
import hashlib
import logging
import os
from pathlib import Path

import requests
from openai import OpenAI

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client

CACHE_DIR = data_path(".image_cache")
CACHE_DIR.mkdir(exist_ok=True)


# Home / neighbourhood pillars must use real Kijiji photos (mahogany#9) — never DALL·E.
BLOCKED_PILLARS = frozenset({"lake", "realestate", "community", "development"})

# Non-home news only (skyline / abstract city — no synthetic houses)
PILLAR_STYLES = {
    "safety": (
        "Calgary downtown street scene, daytime, no residential houses in frame. "
        "Urban photography, neutral tones, NO single-family homes, NO real-estate listing look."
    ),
    "calgary": (
        "Downtown Calgary skyline with Bow River in the foreground, "
        "blue sky, Rockies visible in the background. "
        "Photorealistic, vibrant, golden hour. NO suburban houses in the frame."
    ),
}

DEFAULT_STYLE = PILLAR_STYLES["calgary"]


def _cache_key(prompt: str) -> str:
    return hashlib.md5(prompt.encode()).hexdigest()[:16]


def generate_image(article_title: str, pillar: str = "community") -> bytes | None:
    """
    Generate a DALL-E image relevant to the article.
    Returns image bytes, or None on failure.
    Caches results to disk to avoid re-generating.
    """
    if pillar in BLOCKED_PILLARS:
        logger.info("DALL-E blocked for home pillar=%s (use real listing photos)", pillar)
        return None

    style = PILLAR_STYLES.get(pillar, DEFAULT_STYLE)

    # Build prompt: combine style with article topic
    title_words = " ".join(article_title.split()[:8])  # first 8 words
    prompt = (
        f"{style} "
        f"Related to: {title_words}. "
        f"NO text overlays, NO logos, NO people's faces visible. "
        f"NO houses, NO real-estate listing style. "
        f"Professional photography quality."
    )

    cache_path = CACHE_DIR / f"{_cache_key(prompt)}.jpg"
    if cache_path.exists():
        logger.info(f"Image cache hit: {cache_path.name}")
        return cache_path.read_bytes()

    logger.info(f"Generating DALL-E image for pillar={pillar}: {title_words}…")
    try:
        client = _get_client()
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",   # standard = $0.04, hd = $0.08
            n=1,
        )
        image_url = resp.data[0].url
        img_bytes = requests.get(image_url, timeout=30).content
        cache_path.write_bytes(img_bytes)
        logger.info(f"DALL-E image generated and cached ({len(img_bytes):,} bytes)")
        return img_bytes
    except Exception as e:
        logger.warning(f"DALL-E generation failed: {e}")
        return None


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    pillar = sys.argv[1] if len(sys.argv) > 1 else "lake"
    title  = sys.argv[2] if len(sys.argv) > 2 else "Mahogany Lake summer activities"
    data = generate_image(title, pillar)
    if data:
        out = Path(f"test_image_{pillar}.jpg")
        out.write_bytes(data)
        print(f"Saved to {out}")
