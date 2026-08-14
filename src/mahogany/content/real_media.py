"""Prefer real Mahogany listing photos — never invent homes with DALL·E."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


def download_image(url: str | None, timeout: int = 20) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "MahoganyBot/1.0 (+https://mahogany-calgary.com)"},
        )
        if r.status_code == 200 and r.content and len(r.content) > 2000:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "image" in ctype or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                return r.content
        logger.debug("Bad image response: %s %s", r.status_code, url[:80])
    except Exception as e:
        logger.debug("Image download failed %s: %s", url[:80], e)
    return None


def _first_image(listings: list[dict[str, Any]]) -> tuple[bytes | None, dict[str, Any] | None]:
    for listing in listings:
        img = download_image(listing.get("image_url"))
        if img:
            return img, listing
    return None, None


def fetch_real_listing_image(
    *,
    prefer: str = "sale",
    max_results: int = 24,
) -> tuple[bytes | None, dict[str, Any] | None]:
    """
    Return (image_bytes, listing_dict) from live Kijiji scrape.
    prefer: "sale" | "rental" | "any"
    Falls back across sale↔rental when images fail to download, not only when
    the scrape returns zero rows.
    """
    sale: list[dict[str, Any]] = []
    rentals: list[dict[str, Any]] = []
    try:
        if prefer in ("sale", "any"):
            from mahogany.scrapers.listings import fetch_mahogany_listings

            sale = fetch_mahogany_listings(max_results=max_results) or []
        if prefer in ("rental", "any"):
            from mahogany.scrapers.rentals import fetch_mahogany_rentals

            rentals = fetch_mahogany_rentals(max_results=max_results) or []
    except Exception as e:
        logger.warning("Real listing scrape failed: %s", e)
        return None, None

    if prefer == "sale":
        order = (sale, rentals)
    elif prefer == "rental":
        order = (rentals, sale)
    else:
        order = (sale, rentals)

    for bucket in order:
        img, listing = _first_image(bucket)
        if img:
            return img, listing

    # If prefer was sale/rental and the other side was not fetched yet
    if prefer == "sale" and not rentals:
        try:
            from mahogany.scrapers.rentals import fetch_mahogany_rentals

            rentals = fetch_mahogany_rentals(max_results=max_results) or []
            return _first_image(rentals)
        except Exception as e:
            logger.warning("Rental fallback scrape failed: %s", e)
    if prefer == "rental" and not sale:
        try:
            from mahogany.scrapers.listings import fetch_mahogany_listings

            sale = fetch_mahogany_listings(max_results=max_results) or []
            return _first_image(sale)
        except Exception as e:
            logger.warning("Sale fallback scrape failed: %s", e)

    logger.info("No real listing images available")
    return None, None
