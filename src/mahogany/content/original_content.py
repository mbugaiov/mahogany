"""
original_content.py — Generate original (non-news) content for @mahogany_calgary.

These posts don't rely on external articles — they're generated purely from
community knowledge and creativity. High shareability, drives engagement.

Types:
  - did_you_know   : surprising facts about Mahogany
  - insider_tip    : local resident tips
  - comparison     : Mahogany vs other neighbourhoods
  - market_snapshot: weekly real estate summary
  - poll_post      : engagement-driving question
  - seasonal       : season-appropriate content
"""

import os
import logging
import random
from datetime import date
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_HASHTAGS = "#Mahogany #MahoganyCalgary #Calgary #YYC"

CONTENT_TYPES = [
    "did_you_know",
    "insider_tip",
    "comparison",
    "seasonal",
    "investment_angle",
]

SYSTEM_BASE = """
You write original content for "Mahogany Life 🌊" — a Telegram channel about Mahogany, 
Calgary's premier lakeside neighbourhood in SE Calgary, Alberta.

KEY FACTS ABOUT MAHOGANY:
- Home to Canada's largest freshwater lake in a residential community
- Private beach club (Mahogany Beach Club) — residents only, sandy beach, paddleboats
- ~15,000+ residents, master-planned by Hopewell Residential
- Award-winning: best community in Canada (multiple years)
- SE Calgary, ~25 min from downtown
- Mix of single-family homes, townhouses, condos
- Price range: ~$350K (condo) to $1.5M+ (estate)
- Great schools, parks, Mahogany Village Market (Sobeys, Tim Hortons, restaurants)
- Young families + professionals dominate demographics
- Alberta has NO provincial income tax — huge draw for newcomers

WRITING STYLE:
- First line MUST be a scroll-stopper (bold statement, surprising fact, or question)
- 3-5 emojis used purposefully
- Warm, knowledgeable, slightly proud tone
- Use <b>bold</b> for headline only
- End with a short engagement hook (question or "Share this with someone who…")
- 6-8 hashtags on last line, always include: #Mahogany #MahoganyCalgary #Calgary #YYC
"""

def _call_gpt(prompt: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_BASE},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.9,
        max_tokens=600,
    )
    return resp.choices[0].message.content.strip()


def did_you_know() -> str:
    prompt = """Write a "Did you know? 🤔" post about a surprising or little-known 
fact about Mahogany Calgary. Could be about:
- The lake (size, history, fish, activities)
- Community records or awards
- Real estate milestones  
- Population growth
- The beach club
- Wildlife near the lake

Make it genuinely surprising and shareable. End with "Drop a 💙 if you knew this!"
Include hashtags: #Mahogany #MahoganyCalgary #Calgary #YYC #MahoganyLife #DidYouKnow"""
    return _call_gpt(prompt)


def insider_tip() -> str:
    topics = [
        "the best time to visit Mahogany Beach Club (avoid crowds)",
        "hidden walking trails around the lake most residents don't know about",
        "the best coffee/brunch spots within walking distance in Mahogany",
        "how to get the best view of the lake at sunset",
        "the best streets to buy in Mahogany for value + appreciation",
        "what to do on a rainy day in Mahogany with kids",
        "how the private beach club actually works (access, rules, amenities)",
        "the fastest routes to downtown Calgary from Mahogany",
    ]
    topic = random.choice(topics)
    prompt = f"""Write an "Insider Tips 💡" post for Mahogany residents about: {topic}

Format as a listicle OR a short narrative. Be specific and practical.
End with: "Save this post — you'll thank us later 🔖"
Include hashtags: #Mahogany #MahoganyCalgary #Calgary #YYC #InsiderTips #YYCLife"""
    return _call_gpt(prompt)


def comparison_post() -> str:
    comparisons = [
        ("Auburn Bay", "Mahogany's neighbour to the north — also a lake community"),
        ("Aspen Woods", "SW Calgary's affluent community"),
        ("McKenzie Towne", "SE Calgary heritage-style community"),
        ("Downtown Calgary", "urban condo life vs lake living"),
        ("Toronto", "why people leave Toronto for Calgary/Mahogany"),
        ("Cranston", "Mahogany's SE neighbour along the Bow"),
    ]
    other, description = random.choice(comparisons)
    prompt = f"""Write a comparison post: "Mahogany vs. {other}" ({description}).

Compare on:
- Lifestyle / vibe
- Price point (be realistic)
- Who it's best for
- 1-2 unique advantages of Mahogany

Be honest, not promotional. Mahogany isn't perfect for everyone — say that!
End with: "Which one would you choose? 👇 Tell us below!"
Include hashtags: #Mahogany #MahoganyCalgary #Calgary #YYC #CalgaryRealEstate #YYCLife"""
    return _call_gpt(prompt)


def seasonal_post() -> str:
    month = date.today().month
    if month in [12, 1, 2]:
        season_context = "winter in Mahogany — lake skating, cozy vibes, snow"
    elif month in [3, 4, 5]:
        season_context = "spring arriving in Mahogany — lake thaw, first days at the beach, new listings"
    elif month in [6, 7, 8]:
        season_context = "summer at Mahogany Beach Club — peak lake season, why residents love it"
    else:
        season_context = "fall in Mahogany — colours around the lake, back to school, cozy season"

    prompt = f"""Write a seasonal lifestyle post about: {season_context}

Paint a vivid picture — sensory details, what residents are actually doing right now.
Make it feel like a postcard from the neighbourhood.
End with "What's your favourite season in Mahogany? ❄️☀️🍂🌸"
Include hashtags: #Mahogany #MahoganyCalgary #Calgary #YYC #LakeLiving #MahoganyLife"""
    return _call_gpt(prompt)


def investment_angle() -> str:
    angles = [
        "why Mahogany is one of Calgary's best long-term real estate investments",
        "Alberta's no-provincial-income-tax advantage for Mahogany homeowners",
        "how Mahogany's lake adds $50K-$100K premium to property values",
        "rent vs buy in Mahogany 2026 — the numbers",
        "why remote workers are choosing Mahogany over Toronto/Vancouver",
        "Mahogany new construction vs resale — pros and cons",
    ]
    angle = random.choice(angles)
    prompt = f"""Write a real estate / investment insight post about: {angle}

Use real-sounding numbers (approximate, clearly labelled as estimates).
Tone: helpful financial friend, not a salesperson.
End with: "Questions about Mahogany real estate? Drop them below 👇"
Include hashtags: #Mahogany #MahoganyCalgary #Calgary #YYC #CalgaryRealEstate #AlbertaRealEstate #Investing"""
    return _call_gpt(prompt)


GENERATORS = {
    "did_you_know":     did_you_know,
    "insider_tip":      insider_tip,
    "comparison":       comparison_post,
    "seasonal":         seasonal_post,
    "investment_angle": investment_angle,
}


def generate_original(content_type: str = None) -> str:
    """Generate an original post. content_type=None picks randomly."""
    if content_type is None:
        content_type = random.choice(CONTENT_TYPES)
    generator = GENERATORS.get(content_type, seasonal_post)
    logger.info(f"Generating original content: {content_type}")
    return generator()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    ctype = sys.argv[1] if len(sys.argv) > 1 else None
    print(generate_original(ctype))
