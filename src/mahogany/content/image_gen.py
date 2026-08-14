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


# Pillar-specific image style guidance for DALL-E
PILLAR_STYLES = {
    "lake": (
        "Beautiful lakeside photo of Mahogany Lake in Calgary, Alberta. "
        "Blue water, sandy beach, dock, sunny day, families enjoying the water. "
        "Photorealistic, vibrant colours, golden hour light."
    ),
    "realestate": (
        "Modern family home in Calgary, Alberta, Canada. "
        "New construction, well-maintained lawn, blue sky. "
        "Photorealistic real estate photography style, warm welcoming look."
    ),
    "community": (
        "Friendly neighbourhood community event in Calgary, Canada. "
        "Families, children, green parks, sunny day. "
        "Warm community atmosphere, photorealistic."
    ),
    "development": (
        "New residential construction in Calgary, Alberta. "
        "New homes being built, crane, sunny day, modern neighbourhood. "
        "Architectural/construction photography style."
    ),
    "safety": (
        "Calgary, Alberta neighbourhood street, daytime. "
        "Residential area, safe community feel. "
        "Photorealistic, neutral tones."
    ),
    "calgary": (
        "Downtown Calgary skyline with Bow River in the foreground, "
        "blue sky, Rockies visible in the background. "
        "Photorealistic, vibrant, golden hour."
    ),
}

DEFAULT_STYLE = (
    "Beautiful aerial view of Mahogany neighbourhood in SE Calgary, Canada. "
    "Lake visible, residential homes, green spaces, sunny day. "
    "Drone photography style, photorealistic."
)


def _cache_key(prompt: str) -> str:
    return hashlib.md5(prompt.encode()).hexdigest()[:16]


def generate_image(article_title: str, pillar: str = "community") -> bytes | None:
    """
    Generate a DALL-E image relevant to the article.
    Returns image bytes, or None on failure.
    Caches results to disk to avoid re-generating.
    """
    style = PILLAR_STYLES.get(pillar, DEFAULT_STYLE)

    # Build prompt: combine style with article topic
    title_words = " ".join(article_title.split()[:8])  # first 8 words
    prompt = (
        f"{style} "
        f"Related to: {title_words}. "
        f"NO text overlays, NO logos, NO people's faces visible. "
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
