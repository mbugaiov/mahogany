"""
insider_bot.py — Mahogany Insider Tips for the community.

Posts to "Mahogany Insider 💡" thread (id=99).
Schedule: Tuesday + Thursday at 11 AM.

Content mix:
  - Hidden gems & local knowledge (GPT with rich Mahogany context)
  - Reddit r/Calgary mentions of Mahogany (real community discussions)
  - Seasonal tips (lake, winter, events)
  - Newcomer guides ("Things to know if you just moved to Mahogany")
  - Neighbourhood hacks (parking, shortcuts, locals-only spots)
"""

from mahogany.config import data_path
import json
import logging
import os
import re
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import requests
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

TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID        = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
INSIDER_THREAD  = os.getenv("INSIDER_THREAD_ID", "99")
OPENAI_KEY      = os.getenv("OPENAI_API_KEY")
API_BASE        = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

CACHE_FILE = data_path("insider_cache.json")
HEADERS    = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36", "Accept": "application/json"}

# ── Mahogany knowledge base ───────────────────────────────────────────────────
# Rich local knowledge fed to GPT so it gives specific, accurate tips.

MAHOGANY_KNOWLEDGE = """
ABOUT MAHOGANY, CALGARY:
- Southeast Calgary neighbourhood, built around 63-acre freshwater lake (Mahogany Lake)
- Private beach club for residents: Mahogany Beach (main beach + west beach)
- Beach Club amenities: sandy beach, paddleboards, kayaks, volleyball, fire pits
- Beach open June through September. Membership via HOA (MRVCA)
- Winter: the lake sometimes freezes for skating (depends on temperatures)
- Skating rink maintained at the Beach Club in winter
- Main entrance off Mahogany Blvd SE and 52 St SE
- Direct access to 52 St SE & Stoney Trail (ring road)
- Nearby shopping: Superstore on Mahogany Blvd SE, Seton Urban District (5 min away)
- Seton amenities: South Health Campus hospital, Cineplex VIP theatre, YMCA (largest in Canada)
- Great proximity to Deerfoot Trail and Highway 22X
- South Health Campus is the newest Calgary hospital - 3 minutes from Mahogany
- Auburn Bay: neighbouring lake community with its own lake access
- McKenzie Towne: nearby established community with Heritage Dr shops
- Wetlands & pathways: extensive pathway system, Mahogany wetlands nature area
- Community garden near the lake
- Multiple parks: Mahogany Park, playground areas throughout
- HOA: Mahogany Residents Village Corporation Association (MRVCA)
- Annual HOA fee: covers beach club, pathway maintenance, community events
- Popular annual events: Beach Bash (summer), Movies at the Beach, outdoor concerts
- Good schools: Divine Mercy Catholic (K-6), Joane Cardinal-Schubert HS nearby
- Bus routes: limited, many residents drive. BRT on 52 St planned
- Pet-friendly: dog park near the lake, many families with pets
- Strong Facebook community: "Mahogany Community, Calgary" group (thousands of members)
- Coyotes are common in evenings - don't leave pets unattended at dusk
- Best sunrise views: east-facing homes toward the lake
- Best sunset: west beach of the lake
- Real estate: premium lakeside streets = Masters/Marquis. More affordable = inland streets
- Builders: Jayman, Morrison, Hopewell, Calbridge common in the area
- Newer areas: Mahogany Bay (lakefront estates), Mahogany Estate homes

INSIDER TIPS (verified local knowledge):
- The west beach is less crowded than main beach on summer weekends
- Pathways around the full lake perimeter = 4-5 km loop
- Free visitor parking at the main beach (limited)
- Canada geese at the lake in spring/fall — keep dogs on leash
- Wildlife: herons, pelicans, ducks, coyotes, foxes occasionally
- Friday nights in summer: often informal gatherings at the fire pits
- Ice cream truck comes to the beach in summer
- Best photo spots: sunrise from east shore, sunset from west shore
- Storm pond north of the neighbourhood: good for wildlife walks
- YMCA South Health: world's largest YMCA, excellent value for families
- Cineplex VIP in Seton: adults-only screens, recliners, in-seat service
- Heritage Drive McKenzie Towne: good local restaurant strip, 10 min away
- Gas stations: fastest fill-up at Costco Auburn Bay (cheapest too but lineups on weekends)
- New SE LRT/BRT planned: will connect Seton/Mahogany to downtown eventually
- Flooding concern: lower-lying areas near the wetlands had drainage issues in past
- Community Facebook group: best place for local contractor recommendations
- Property tax: City of Calgary. Budget for ~$5K-8K/year for typical home
"""

# Post type rotation — keeps content varied
POST_TYPES = [
    "hidden_gem",
    "newcomer_tip",
    "seasonal_tip",
    "local_hack",
    "community_event",
    "reddit_insight",
    "did_you_know",
    "vs_comparison",
]

SEASON_MAP = {
    1: "winter", 2: "winter", 3: "early spring",
    4: "spring", 5: "spring", 6: "summer",
    7: "summer", 8: "summer", 9: "fall",
    10: "fall", 11: "fall", 12: "winter",
}

# ── Reddit scraper ─────────────────────────────────────────────────────────────

def fetch_reddit_mahogany() -> list[dict]:
    """Fetch recent Reddit posts/comments mentioning Mahogany from r/Calgary."""
    posts = []
    try:
        r = requests.get(
            "https://www.reddit.com/r/Calgary/search.json",
            params={"q": "mahogany", "sort": "new", "limit": 15, "t": "month"},
            headers={"User-Agent": "MahoganyBot/1.0"},
            timeout=10,
        )
        if r.ok:
            data = r.json()
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                title = post.get("title", "")
                body  = post.get("selftext", "")[:300]
                score = post.get("score", 0)
                url   = "https://reddit.com" + post.get("permalink", "")
                if "mahogany" in (title + body).lower() and score > 1:
                    posts.append({
                        "title": title,
                        "body":  body,
                        "score": score,
                        "url":   url,
                    })
    except Exception as e:
        logger.debug(f"Reddit fetch failed: {e}")
    return posts[:5]


# ── GPT writer ────────────────────────────────────────────────────────────────

MAYA_SYSTEM = f"""You are Maya — a warm, knowledgeable long-time Mahogany resident and community guide.
You know every corner of the neighbourhood. You write insider tips for the Mahogany Telegram community.
Conversational English. Specific, useful, occasionally surprising. No fluff.
No markdown, no asterisks. Use plain text only.

Community context:
{MAHOGANY_KNOWLEDGE}"""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_post(post_type: str, month: int, reddit_posts: list[dict] = None) -> dict:
    """Generate an insider tip post. Returns {title, body, hashtags}."""
    season = SEASON_MAP.get(month, "spring")

    prompts = {
        "hidden_gem": f"""Write a short insider tip about a hidden gem or underrated spot in or near Mahogany.
It's {season}. Be very specific — name the exact location, what makes it special, and when to go.
Format: one punchy title line, then 2-3 sentences of detail. Keep it under 150 words total.""",

        "newcomer_tip": f"""Write a must-know tip for someone who just moved to Mahogany.
Season: {season}. Pick ONE specific thing they probably don't know yet.
Format: one punchy title line, then 2-3 sentences. Practical and specific.""",

        "seasonal_tip": f"""Write a seasonal tip for Mahogany residents for {season}.
Something specific to do, see, or know right now. Could be lake, pathways, events, or practical.
Format: one punchy title line, then 2-3 sentences.""",

        "local_hack": f"""Write a local life hack for Mahogany residents.
Could be about: parking, shopping, traffic, community shortcuts, or neighbourhood services.
Season: {season}. Be very specific and actionable.
Format: one punchy title line, then 2-3 sentences.""",

        "did_you_know": f"""Write a surprising "did you know" fact about Mahogany or the surrounding area.
Make it genuinely interesting and specific — not generic. Season: {season}.
Format: "Did you know..." as the opener, then 2-3 sentences of context.""",

        "vs_comparison": f"""Write a friendly comparison of two options for Mahogany residents.
Examples: main beach vs west beach, Superstore vs Co-op, Costco fuel vs gas station, etc.
Season: {season}. Give a clear recommendation with reasoning.
Format: "🆚 [Option A] vs [Option B]" as title, then 3-4 sentences.""",

        "reddit_insight": f"""Based on these real Reddit discussions from r/Calgary about Mahogany,
write a useful community insight or tip for Mahogany residents.
Be helpful and add your own local knowledge to the discussion.

Reddit posts:
{chr(10).join(f'- {p["title"]}: {p["body"][:150]}' for p in (reddit_posts or [])[:3])}

Format: one punchy title line, then 2-3 sentences of insight. Under 150 words.""",

        "community_event": f"""Write about something happening or worth doing in Mahogany this {season}.
Could be the beach club, community events, nearby Seton attractions, or seasonal activities.
Be specific about timing and location.
Format: one punchy title line, then 2-3 sentences.""",
    }

    prompt = prompts.get(post_type, prompts["hidden_gem"])

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=200, temperature=0.85,
    )
    raw = resp.choices[0].message.content.strip()

    # Split title from body (first line = title)
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    title = lines[0] if lines else "Mahogany Insider Tip"
    body  = "\n".join(lines[1:]) if len(lines) > 1 else raw

    # Hashtags by type
    base_tags = "#MahoganyInsider #MahoganyCalgary #YYC"
    type_tags = {
        "hidden_gem":    "#HiddenGem #CalgaryLife",
        "newcomer_tip":  "#NewToMahogany #CalgaryMoveIn",
        "seasonal_tip":  f"#Mahogany{season.replace(' ','').title()}",
        "local_hack":    "#LocalTips #CalgaryHacks",
        "did_you_know":  "#DidYouKnow #MahoganyFacts",
        "vs_comparison": "#MahoganyLife #CalgaryComparison",
        "reddit_insight":"#Calgary #CommunityTips",
        "community_event":"#MahoganyEvents #CalgaryEvents",
    }.get(post_type, "")

    return {
        "title":    title,
        "body":     body,
        "hashtags": f"{base_tags} {type_tags}".strip(),
    }


# ── Post builder ──────────────────────────────────────────────────────────────

def build_post(post_type: str, month: int, reddit_posts: list) -> str:
    post = generate_post(post_type, month, reddit_posts)

    title = _escape(post["title"])
    body  = _escape(post["body"])
    tags  = post["hashtags"]

    # Type-specific header emoji
    emojis = {
        "hidden_gem":      "🔍",
        "newcomer_tip":    "🏡",
        "seasonal_tip":    "🌿",
        "local_hack":      "⚡",
        "did_you_know":    "💡",
        "vs_comparison":   "🆚",
        "reddit_insight":  "💬",
        "community_event": "🎉",
    }
    em = emojis.get(post_type, "💡")

    lines = [
        f"{em} <b>{title}</b>",
        "",
        body,
        "",
        tags,
    ]
    return "\n".join(lines)


# ── Telegram sender ───────────────────────────────────────────────────────────

def post_to_telegram(text: str) -> bool:
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={
            "chat_id":                  GROUP_ID,
            "message_thread_id":        INSIDER_THREAD,
            "text":                     text[:4096],
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    result = resp.json()
    if result.get("ok"):
        logger.info(f"✅ Insider tip posted → msg_id={result['result']['message_id']}")
        return True
    logger.error(f"❌ Error: {result.get('description')}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def _pick_post_type(cache: dict) -> str:
    """Pick post type that hasn't been used recently."""
    used = cache.get("recent_types", [])
    available = [t for t in POST_TYPES if t not in used[-4:]]
    if not available:
        available = POST_TYPES
    return random.choice(available)


def run(post_type: str | None = None):
    if not can_run_bot("insider_bot", min_interval_hours=4):
        return

    month = datetime.now().month
    cache = _load_cache()

    if not post_type:
        post_type = _pick_post_type(cache)

    logger.info(f"Generating '{post_type}' insider post for {SEASON_MAP.get(month)} season…")

    # Fetch Reddit data if needed
    reddit_posts = []
    if post_type == "reddit_insight":
        logger.info("Fetching Reddit r/Calgary data…")
        reddit_posts = fetch_reddit_mahogany()
        if not reddit_posts:
            logger.info("No Reddit posts found — switching to hidden_gem")
            post_type = "hidden_gem"

    text = build_post(post_type, month, reddit_posts)
    post_to_telegram(text)

    # Update cache
    recent = cache.get("recent_types", [])
    recent.append(post_type)
    cache["recent_types"] = recent[-10:]
    cache["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_cache(cache)
    mark_bot_ran("insider_bot")

    logger.info("Done.")


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=POST_TYPES, help="Post type to generate")
    args = parser.parse_args()
    run(post_type=args.type)
