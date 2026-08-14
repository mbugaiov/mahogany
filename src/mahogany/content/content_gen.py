"""
content_gen.py — GPT-4o powered SMM content generator for @mahogany_calgary.

Produces engaging, shareable Telegram posts with:
  - Content pillar detection (lake life / real estate / community / etc.)
  - Pillar-specific tone and hooks
  - Storytelling structure: hook → value → CTA
  - Emoji, formatting, hashtags
"""

import os
import logging
import re
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Content pillar detection ──────────────────────────────────────────────────

PILLARS = {
    "lake":        ["lake", "beach", "swim", "kayak", "skate", "waterfront", "pier", "mahogany lake"],
    "realestate":  ["real estate", "housing", "price", "sold", "listing", "mortgage", "condo", "detached",
                    "market", "appreciation", "investment", "rent", "buyer", "seller", "realtor"],
    "community":   ["community", "event", "school", "park", "playground", "festival", "resident",
                    "neighbour", "hoa", "mahogany village", "local business", "opening"],
    "development": ["development", "construction", "build", "new homes", "expansion", "infrastructure",
                    "transit", "lrt", "road", "permit", "zoning"],
    "safety":      ["fire", "flood", "police", "crime", "accident", "emergency", "drowning", "safety"],
    "calgary":     ["calgary", "alberta", "economy", "jobs", "immigration", "population", "growth"],
}

def detect_pillar(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    for pillar, kws in PILLARS.items():
        if any(kw in text for kw in kws):
            return pillar
    return "community"

# ── Pillar-specific prompts ───────────────────────────────────────────────────

PILLAR_INSTRUCTIONS = {
    "lake": """
Content pillar: 🌊 LAKE LIFE
Tone: dreamy, aspirational, "can you believe we live here?" energy.
Hook ideas: paint a vivid sensory picture of the lake, use "Imagine…", "This is why we chose Mahogany…"
Must feel like something a proud resident would share with friends.
""",
    "realestate": """
Content pillar: 🏡 REAL ESTATE INTEL
Tone: confident, data-forward but human. Like a trusted realtor friend giving you the real scoop.
Hook ideas: lead with a surprising number or % change. "Mahogany homes are up X%…", "Only X homes left under $Y…"
Include a question at the end that drives comments (e.g. "Thinking of buying? Drop a 🙋 below!")
""",
    "community": """
Content pillar: 🏘️ COMMUNITY PULSE
Tone: warm, excited neighbour sharing good news over the fence.
Hook ideas: "Big news for Mahogany residents 👀", "Something exciting is happening in our neighbourhood…"
Make it feel LOCAL and specific, not generic Calgary news.
""",
    "development": """
Content pillar: 🏗️ WHAT'S BEING BUILT
Tone: informed, slightly excited about what's coming. Future-focused.
Hook ideas: "Mahogany is growing — here's what's next 👇", "New development incoming that affects all of us…"
Explain what it means for RESIDENTS (traffic? amenities? property values?).
""",
    "safety": """
Content pillar: ⚠️ COMMUNITY SAFETY
Tone: serious, empathetic, community-focused. Never alarmist.
Hook ideas: Lead with the human impact, then the facts.
Always end with a positive community angle or call to action.
""",
    "calgary": """
Content pillar: 📊 CALGARY GROWTH
Tone: macro → local. Start with the big Calgary picture, bring it back to how it affects Mahogany specifically.
Hook ideas: "Why people keep choosing Calgary — and specifically SE communities like Mahogany…"
Make it relevant to someone considering moving here.
""",
}

DEFAULT_PILLAR_INSTRUCTION = PILLAR_INSTRUCTIONS["community"]

# ── Master system prompt ──────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """
You are the SMM manager for "Mahogany Life 🌊" — a Telegram channel about Mahogany, 
Calgary's premier award-winning lakeside neighbourhood in SE Calgary, Alberta, Canada.

CHANNEL FACTS TO WEAVE IN WHEN RELEVANT:
- Mahogany has Canada's largest freshwater lake in a residential community
- Private beach club with sandy beaches, year-round activities
- One of Calgary's fastest-growing and most in-demand neighbourhoods
- Consistently ranked top neighbourhood for families
- Mix of young families, professionals, and investors

YOUR WRITING RULES:
1. HOOK first — the first line must stop the scroll. No fluff. Be bold or curious.
2. VALUE middle — 2-3 sentences of real insight or story. No filler.
3. CTA end — 1 short sentence that drives engagement (share, comment, or visit link)
4. Emojis: 3-5 max, used purposefully not decoratorively
5. HTML formatting: use <b>bold</b> for the headline only, <i>italic</i> sparingly
6. Hashtags: exactly on the last line, 6-8 tags
7. Total length: 250-400 chars of body text (not counting hashtags/link line)
8. NEVER sound like a press release. Sound like a knowledgeable, enthusiastic neighbour.
9. Always include a 📰 source line with the URL as an HTML link

{pillar_instruction}

Output format (use exactly this structure):
<b>[HEADLINE — max 10 words, no period]</b>

[body text]

📰 <a href="[URL]">[Source Name]</a>

[hashtags on one line]

If the article is not about Mahogany Calgary at all, respond with: SKIP
"""

# ── Hashtag sets per pillar ───────────────────────────────────────────────────

PILLAR_HASHTAGS = {
    "lake":        "#LakeLiving #MahoganLake #LakesideLiving #BeachLife",
    "realestate":  "#CalgaryRealEstate #YYCRealEstate #BuyInCalgary #CalgaryHousing",
    "community":   "#CalgaryLife #CalgaryNeighbourhood #YYCLife #CommunityFirst",
    "development": "#CalgaryDevelopment #NewCalgary #YYCBuilds #CalgaryGrowth",
    "safety":      "#CalgaryNews #YYCSafety #CommunityMatters",
    "calgary":     "#CalgaryAlberta #MoveToAlberta #YYCLiving #CalgaryCanada",
}
BASE_HASHTAGS = "#Mahogany #MahoganyCalgary #Calgary #YYC"


@dataclass
class GeneratedPost:
    headline:    str
    body:        str
    hashtags:    str
    source:      str
    full_text:   str
    pillar:      str = "community"
    skipped:     bool = False


def generate_post(article: dict) -> GeneratedPost:
    title     = article.get("title", "")
    summary   = article.get("summary", "")
    url       = article.get("url", "")
    source    = article.get("source", "")
    published = article.get("published", "")

    pillar = detect_pillar(title, summary)
    pillar_instruction = PILLAR_INSTRUCTIONS.get(pillar, DEFAULT_PILLAR_INSTRUCTION)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(pillar_instruction=pillar_instruction)

    user_msg = f"""Article to turn into a channel post:

Title: {title}
Source: {source}
Published: {published}
Summary: {summary}
URL: {url}

Write the Telegram post now."""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",           # upgraded to gpt-4o for better quality
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.85,
            max_tokens=700,
        )
        raw = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT generation failed: {e}")
        raise

    if raw.strip().upper() == "SKIP":
        return GeneratedPost(headline="", body="", hashtags="", source=source,
                             full_text="", pillar=pillar, skipped=True)

    # Ensure base hashtags are always present
    pillar_tags = PILLAR_HASHTAGS.get(pillar, "")
    all_hashtags = f"{BASE_HASHTAGS} {pillar_tags}".strip()

    # If model didn't include hashtags, append them
    if "#Mahogany" not in raw:
        raw = raw.rstrip() + f"\n\n{all_hashtags}"

    return GeneratedPost(
        headline=title,
        body=raw,
        hashtags=all_hashtags,
        source=source,
        full_text=raw,
        pillar=pillar,
        skipped=False,
    )


if __name__ == "__main__":
    import json, sys
    logging.basicConfig(level=logging.INFO)

    test_article = {
        "title":     "Mahogany named one of Calgary's top neighbourhoods for families 2025",
        "source":    "Avenue Calgary",
        "published": "2026-03-16",
        "summary":   (
            "Mahogany, the award-winning lakeside community in SE Calgary, "
            "has been ranked among the best neighbourhoods for families. "
            "The community features Canada's largest private freshwater lake, "
            "a beach club, year-round activities, and top-rated schools. "
            "Real estate prices have appreciated 18% over the last 2 years."
        ),
        "url": "https://avenuecalgary.com/mahogany-top-neighbourhood",
    }

    post = generate_post(test_article)
    if post.skipped:
        print("SKIPPED")
    else:
        print(f"\nPillar: {post.pillar.upper()}")
        print("="*60)
        print(post.full_text)
