#!/usr/bin/env python3
"""
group_bot.py — Maya's interactive presence in the Mahogany community group.

Maya listens to messages in the group and:
  1. Answers questions about Mahogany (real estate, lake, community, events)
  2. Reacts to keywords with relevant info
  3. Welcomes new members
  4. Ignores irrelevant messages (keeps it clean)

Run with: python3 group_bot.py
Runs continuously via polling. Should be kept running on the Mac or DO server.
"""

from mahogany.config import data_path
import os
import sys
import time
import json
import logging
import requests
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

from mahogany import config  # noqa: F401 — loads .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(data_path("group_bot.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID  = os.getenv("PREVIEW_CHAT_ID", "-1002496756164")
API_BASE  = f"https://api.telegram.org/bot{TOKEN}"
client    = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Track last processed update ID
OFFSET_FILE = data_path(".group_bot_offset")

MAYA_SYSTEM = """
You are Maya, the community manager for Mahogany, Calgary — a warm, knowledgeable local guide.

ABOUT MAHOGANY (use this knowledge):
- SE Calgary, Alberta, Canada
- Home to Canada's largest freshwater lake in a residential community (63 acres)  
- Private Mahogany Beach Club — sandy beach, paddleboats, year-round activities
- ~15,000 residents, award-winning master-planned community by Hopewell Residential
- Top-ranked neighbourhood for families in Canada (multiple years)
- Mix of condos ($350K+) to estate homes ($1.5M+)
- Alberta has NO provincial income tax
- Key amenities: Mahogany Village Market (Sobeys, restaurants, Tim Hortons), schools, parks
- 25 min from downtown Calgary
- Forum topics in this group: General, News, Photos, Flood, Kids

RESPONSE RULES:
- Keep responses SHORT (2-4 sentences max for casual questions)
- Warm, friendly, helpful tone — like a knowledgeable neighbour
- For real estate questions: give ballpark figures but suggest contacting a local realtor
- For events/news: be honest if you don't have current data
- Don't respond to: spam, off-topic, one-word messages, other languages unless clearly about Mahogany
- If the message is clearly not about Mahogany or real estate: respond with IGNORE
- Always respond in the SAME LANGUAGE as the question (English/Ukrainian/Russian)
"""

TRIGGER_KEYWORDS = [
    "mahogany", "lake", "beach", "real estate", "house", "condo", "price",
    "school", "community", "calgary", "buy", "rent", "invest", "neighbourhood",
    "flood", "kids", "event", "welcome", "help", "question", "нерухомість",
    "озеро", "район", "купити", "оренда", "maya", "?",
]


def get_offset() -> int:
    if OFFSET_FILE.exists():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except Exception:
            pass
    return 0


def save_offset(offset: int):
    OFFSET_FILE.write_text(str(offset))


def get_updates(offset: int) -> list:
    try:
        r = requests.get(
            f"{API_BASE}/getUpdates",
            params={"timeout": 20, "offset": offset, "limit": 10,
                    "allowed_updates": json.dumps(["message", "chat_member"])},
            timeout=25,
        )
        if r.ok:
            return r.json().get("result", [])
    except Exception as e:
        logger.warning(f"getUpdates error: {e}")
    return []


def should_respond(text: str, is_reply_to_maya: bool) -> bool:
    """Decide if Maya should respond to this message."""
    if not text or len(text) < 3:
        return False
    if is_reply_to_maya:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in TRIGGER_KEYWORDS)


def generate_reply(user_name: str, text: str, thread_id: int | None) -> str | None:
    """Generate Maya's reply using GPT-4o. Returns None if should be ignored."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": MAYA_SYSTEM},
                {"role": "user", "content": f"{user_name}: {text}"},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        reply = resp.choices[0].message.content.strip()
        if reply.upper() == "IGNORE":
            return None
        return reply
    except Exception as e:
        logger.error(f"GPT error: {e}")
        return None


def send_reply(chat_id: str, text: str, reply_to_msg_id: int,
               thread_id: int | None = None) -> bool:
    payload = {
        "chat_id":             chat_id,
        "text":                text[:4000],
        "parse_mode":          "HTML",
        "reply_to_message_id": reply_to_msg_id,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    r = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
    return r.ok


def welcome_new_member(chat_id: str, name: str, thread_id: int | None = None):
    """Send a welcome message when someone joins."""
    text = (
        f"Welcome to Mahogany Life, {name}! 🌊\n\n"
        f"I'm Maya, your community guide here. Feel free to ask me anything about "
        f"Mahogany — real estate, lake activities, local events, schools, or anything else. "
        f"Happy to help! 🏡"
    )
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)


# Rate limiting: don't reply more than once per minute per user
_last_reply: dict[int, float] = {}
REPLY_COOLDOWN = 60  # seconds per user


def process_update(update: dict):
    update_id = update.get("update_id", 0)

    # Handle new chat member
    new_members = update.get("message", {}).get("new_chat_members", [])
    for member in new_members:
        if not member.get("is_bot"):
            name = member.get("first_name", "friend")
            logger.info(f"New member: {name}")
            thread_id = update["message"].get("message_thread_id")
            welcome_new_member(GROUP_ID, name, thread_id)
        return

    # Handle regular messages
    msg = update.get("message")
    if not msg:
        return

    chat = msg.get("chat", {})
    if str(chat.get("id")) != str(GROUP_ID):
        return   # only respond in our group

    text = msg.get("text", "").strip()
    user = msg.get("from", {})
    user_id = user.get("id", 0)
    user_name = user.get("first_name", "Someone")
    msg_id = msg.get("message_id")
    thread_id = msg.get("message_thread_id")

    # Don't respond to bots or our own messages
    if user.get("is_bot"):
        return

    # Check if this is a reply to Maya
    reply_to = msg.get("reply_to_message", {})
    is_reply_to_maya = reply_to.get("from", {}).get("is_bot") and \
                       reply_to.get("from", {}).get("first_name") == "Maya"

    if not should_respond(text, is_reply_to_maya):
        return

    # Rate limiting
    now = time.time()
    if now - _last_reply.get(user_id, 0) < REPLY_COOLDOWN:
        logger.debug(f"Rate limited for user {user_name}")
        return
    _last_reply[user_id] = now

    logger.info(f"Responding to [{user_name}] in thread={thread_id}: {text[:60]}")
    reply = generate_reply(user_name, text, thread_id)

    if reply:
        ok = send_reply(GROUP_ID, reply, msg_id, thread_id)
        logger.info(f"  → Reply sent: ok={ok} | {reply[:80]}")
    else:
        logger.info("  → Decided to IGNORE")


def main():
    logger.info("Maya group bot starting…")
    logger.info(f"Listening to group: {GROUP_ID}")
    offset = get_offset()

    while True:
        updates = get_updates(offset)
        for update in updates:
            try:
                process_update(update)
            except Exception as e:
                logger.error(f"Error processing update: {e}")
            offset = update.get("update_id", offset) + 1
            save_offset(offset)

        if not updates:
            time.sleep(1)  # brief pause when no updates


if __name__ == "__main__":
    main()
