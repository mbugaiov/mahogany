"""
weather_report.py — Weekly Mahogany Lake & Weekend Weather Report.

Posts every Friday at 4 PM to the News thread.
Data source: wttr.in (free, no API key).

Report includes:
  - Current conditions
  - Weekend forecast (Sat + Sun)
  - Lake Day Score (0–10) based on temp/wind/precipitation
  - Activity recommendations
  - Maya's take (GPT-written)
"""

from mahogany.config import data_path
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from mahogany.state.dedup import can_run_bot, mark_bot_ran
from openai import OpenAI

from mahogany import config  # noqa: F401 — loads .env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID    = os.getenv("GROUP_ID", os.getenv("TELEGRAM_CHANNEL", ""))
NEWS_THREAD = os.getenv("NEWS_THREAD_ID", "6")
OPENAI_KEY  = os.getenv("OPENAI_API_KEY")
API_BASE    = f"https://api.telegram.org/bot{TOKEN}"

client = OpenAI(api_key=OPENAI_KEY)

WTTR_URL     = "https://wttr.in/Mahogany+Calgary?format=j1"
LAKE_CACHE = data_path("weather_cache.json")

MAHOGANY_LAKE_OPEN_MONTHS = list(range(6, 10))   # June–September beach season
SKATING_MONTHS            = [12, 1, 2]           # Dec–Feb skating

WTTR_HEADERS = {"User-Agent": "curl/7.79.1"}


# ── Weather data ──────────────────────────────────────────────────────────────

def fetch_weather() -> dict | None:
    try:
        r = requests.get(WTTR_URL, headers=WTTR_HEADERS, timeout=10)
        if r.ok:
            return r.json()
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
    return None


def parse_day(day_data: dict, hour_index: int = 4) -> dict:
    """Parse a wttr.in day object at noon-ish (hour_index=4 = 12:00)."""
    h = day_data["hourly"][hour_index]
    return {
        "date":     day_data["date"],
        "max_c":    int(day_data["maxtempC"]),
        "min_c":    int(day_data["mintempC"]),
        "desc":     h["weatherDesc"][0]["value"],
        "precip":   float(h.get("precipMM", 0)),
        "wind":     int(h.get("windspeedKmph", 0)),
        "humidity": int(h.get("humidity", 50)),
        "uv":       int(h.get("uvIndex", 0)),
        "cloud":    int(h.get("cloudcover", 0)),
        "feel_c":   int(h.get("FeelsLikeC", day_data["maxtempC"])),
    }


def lake_day_score(day: dict, month: int) -> tuple[int, str]:
    """
    Compute a Lake Day Score (0–10) and a short reason string.
    Considers: temperature, wind, precipitation, UV, season.
    """
    score = 0
    reasons = []

    # Season modifier
    in_beach = month in MAHOGANY_LAKE_OPEN_MONTHS
    in_skate = month in SKATING_MONTHS

    temp = day["max_c"]
    wind = day["wind"]
    precip = day["precip"]

    if in_beach:
        # Summer beach scoring
        if temp >= 28:    score += 4; reasons.append(f"{temp}°C — perfect beach weather")
        elif temp >= 22:  score += 3; reasons.append(f"{temp}°C — great for the lake")
        elif temp >= 17:  score += 2; reasons.append(f"{temp}°C — decent for active water sports")
        elif temp >= 12:  score += 1; reasons.append(f"{temp}°C — chilly for swimming")
        else:             score += 0; reasons.append(f"{temp}°C — too cold for beach")

        if wind <= 10:    score += 2; reasons.append("calm winds — perfect for kayaking")
        elif wind <= 20:  score += 1; reasons.append(f"{wind} km/h breeze")
        else:             reasons.append(f"{wind} km/h wind — choppy water")

        if precip == 0:   score += 2; reasons.append("no rain expected")
        elif precip < 2:  score += 1
        else:             reasons.append(f"{precip}mm rain expected")

        if day["uv"] >= 3: score += 1; reasons.append(f"UV {day['uv']} — sunscreen required")
        if day["cloud"] < 30: score += 1

    elif in_skate:
        # Winter skating scoring
        if -15 <= temp <= -2: score += 4; reasons.append(f"{temp}°C — ideal skating conditions")
        elif temp < -15:      score += 2; reasons.append(f"{temp}°C — very cold, dress warmly")
        elif temp > 0:        score += 1; reasons.append(f"{temp}°C — ice may be soft")

        if wind <= 15:  score += 3; reasons.append("light wind — comfortable on the ice")
        elif wind <= 25: score += 1
        else:           reasons.append(f"{wind} km/h wind chill")

        if precip == 0: score += 2; reasons.append("clear skies")
        else:           reasons.append("snowfall expected — check ice conditions")
        score += 1  # bonus: winter activities are fun

    else:
        # Shoulder season — general outdoor
        if temp >= 15:  score += 3
        elif temp >= 8: score += 2
        elif temp >= 2: score += 1

        if wind <= 20: score += 2
        if precip == 0: score += 2
        else: reasons.append("rain expected")

        if day["cloud"] < 50: score += 1
        reasons.append(f"{temp}°C, {day['desc'].lower()}")

    return min(score, 10), " · ".join(reasons[:3])


def score_emoji(score: int) -> str:
    if score >= 8: return "🔥"
    if score >= 6: return "✅"
    if score >= 4: return "🙂"
    if score >= 2: return "🌥"
    return "❄️"


def weather_emoji(desc: str, precip: float) -> str:
    d = desc.lower()
    if precip > 5: return "🌧"
    if "thunder" in d: return "⛈"
    if "snow" in d: return "❄️"
    if "rain" in d or "drizzle" in d: return "🌦"
    if "overcast" in d or "cloud" in d: return "☁️"
    if "clear" in d or "sunny" in d: return "☀️"
    if "partly" in d: return "⛅"
    return "🌤"


def day_label(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A %b %d")
    except Exception:
        return date_str


# ── GPT writer ────────────────────────────────────────────────────────────────

MAYA_SYSTEM = """You are Maya — a warm, witty local guide for Mahogany, Calgary.
You write for a Telegram community channel. Conversational English, like a fun neighbour.
No markdown, no asterisks. Short, punchy, specific. Max 3 sentences."""


def write_weather_take(current: dict, weekend: list[dict], month: int,
                       sat_score: int, sun_score: int) -> str:
    season = "summer" if month in MAHOGANY_LAKE_OPEN_MONTHS else \
             "winter" if month in SKATING_MONTHS else "shoulder season"
    prompt = f"""Write a fun 2-3 sentence weekend weather take for Mahogany residents.
Be specific — mention the lake, beach, or ice rink depending on the season ({season}).
Give one concrete activity recommendation for the best day.

Data:
Right now: {current['max_c']}°C, {current['desc']}, wind {current['wind']} km/h
Saturday: {weekend[0]['min_c']}°–{weekend[0]['max_c']}°C, {weekend[0]['desc']}, precip {weekend[0]['precip']}mm, Lake Score {sat_score}/10
Sunday: {weekend[1]['min_c']}°–{weekend[1]['max_c']}°C, {weekend[1]['desc']}, precip {weekend[1]['precip']}mm, Lake Score {sun_score}/10
Season: {season}"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=120, temperature=0.8,
    )
    return resp.choices[0].message.content.strip()


def write_activity_tips(weekend: list[dict], month: int) -> str:
    best_day = "Saturday" if weekend[0]["max_c"] >= weekend[1]["max_c"] else "Sunday"
    temp     = max(weekend[0]["max_c"], weekend[1]["max_c"])
    season   = "beach/lake" if month in MAHOGANY_LAKE_OPEN_MONTHS else \
               "ice skating" if month in SKATING_MONTHS else "outdoor"

    prompt = f"""List 3 specific weekend activity ideas for Mahogany residents.
Format as short bullet points (one line each, no emoji, no markdown).
Best day: {best_day}, {temp}°C, season: {season}.
Be specific to Mahogany — mention the lake, beach club, or community areas."""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": MAYA_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=120, temperature=0.7,
    )
    raw = resp.choices[0].message.content.strip()
    # Clean up any stray markdown
    lines = [l.lstrip("•*-– ").strip() for l in raw.split("\n") if l.strip()]
    return lines[:3]


# ── Report builder ────────────────────────────────────────────────────────────

def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_report(data: dict) -> str:
    now     = datetime.now()
    month   = now.month
    days    = data["weather"]         # 0=today, 1=tomorrow, 2=day after
    current = data["current_condition"][0]
    cur_day = parse_day(days[0])
    weekend = [parse_day(days[1]), parse_day(days[2])]

    sat_score, sat_reason = lake_day_score(weekend[0], month)
    sun_score, sun_reason = lake_day_score(weekend[1], month)
    best_score  = max(sat_score, sun_score)

    # Season label
    if month in MAHOGANY_LAKE_OPEN_MONTHS:
        lake_label = "🏖 Lake Day Score"
        season_tag = "#MahoganyBeach #MahoganyLake"
    elif month in SKATING_MONTHS:
        lake_label = "⛸ Skate Day Score"
        season_tag = "#MahoganyLake #WinterInMahogany"
    else:
        lake_label = "🌿 Outdoor Score"
        season_tag = "#MahoganyLake"

    # GPT content
    logger.info("Generating GPT content…")
    cur_parsed = {
        "max_c": int(current["temp_C"]),
        "desc":  current["weatherDesc"][0]["value"],
        "wind":  int(current["windspeedKmph"]),
    }
    maya_take  = _escape(write_weather_take(cur_parsed, weekend, month, sat_score, sun_score))
    activities = write_activity_tips(weekend, month)

    def score_bar(s: int) -> str:
        """Colored emoji bar — red→yellow→green gradient, empty = ⬜."""
        if s <= 3:   filled = "🟥"
        elif s <= 5: filled = "🟧"
        elif s <= 7: filled = "🟨"
        else:        filled = "🟩"
        return filled * s + "⬜" * (10 - s) + f"  <b>{s}/10</b>"

    # Report text
    lines = [
        f"🌤 <b>Mahogany Weekend Weather</b>",
        f"<i>{now.strftime('%A, %B %d')}</i>",
        "",
        f"🌡 Right now: <b>{current['temp_C']}°C</b>  ·  feels {current['FeelsLikeC']}°C",
        f"{weather_emoji(cur_parsed['desc'], 0)}  {cur_parsed['desc']}",
        f"💨 Wind: {current['windspeedKmph']} km/h  ·  💧 Humidity: {current['humidity']}%",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{weather_emoji(weekend[0]['desc'], weekend[0]['precip'])} <b>{day_label(weekend[0]['date'])}</b>",
        f"🌡 {weekend[0]['min_c']}° → <b>{weekend[0]['max_c']}°C</b>  ·  {weekend[0]['desc']}",
        (f"🌧 Rain: {weekend[0]['precip']}mm" if weekend[0]['precip'] > 0 else "☀️ No rain"),
        f"💨 Wind: {weekend[0]['wind']} km/h",
        f"{lake_label}:",
        score_bar(sat_score),
        "",
        f"{weather_emoji(weekend[1]['desc'], weekend[1]['precip'])} <b>{day_label(weekend[1]['date'])}</b>",
        f"🌡 {weekend[1]['min_c']}° → <b>{weekend[1]['max_c']}°C</b>  ·  {weekend[1]['desc']}",
        (f"🌧 Rain: {weekend[1]['precip']}mm" if weekend[1]['precip'] > 0 else "☀️ No rain"),
        f"💨 Wind: {weekend[1]['wind']} km/h",
        f"{lake_label}:",
        score_bar(sun_score),
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🎯 <b>Weekend picks:</b>",
    ]

    for act in activities:
        lines.append(f"  · {_escape(act)}")

    lines += [
        "",
        f"💬 <b>Maya's take</b>",
        maya_take,
        "",
        f"#MahoganyWeekend {season_tag} #YYC #Calgary",
    ]

    return "\n".join(lines)


# ── Telegram sender ───────────────────────────────────────────────────────────

def post_report(text: str) -> bool:
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={
            "chat_id":                  GROUP_ID,
            "message_thread_id":        NEWS_THREAD,
            "text":                     text[:4096],
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    result = resp.json()
    if result.get("ok"):
        logger.info(f"✅ Weather report posted → msg_id={result['result']['message_id']}")
        return True
    logger.error(f"❌ Telegram error: {result.get('description')}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not can_run_bot("weather_report", min_interval_hours=20):
        return

    logger.info("Fetching weather data…")
    data = fetch_weather()
    if not data:
        logger.error("Failed to fetch weather data.")
        return

    text = build_report(data)
    logger.info("Posting weather report…")
    post_report(text)
    mark_bot_ran("weather_report")


if __name__ == "__main__":
    run()
