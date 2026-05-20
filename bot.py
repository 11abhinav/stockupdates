# bot.py


# =========================================================
# NSE + INTERNET NEWS TELEGRAM BOT
# GITHUB + RENDER READY VERSION
# =========================================================

import requests
import time
import feedparser
import json
import os

from datetime import datetime
from nsepython import nsefetch

# =========================================================
# TELEGRAM CONFIG (FROM ENV VARIABLES)
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# =========================================================
# CUSTOM WATCHLIST
# =========================================================

WATCHLIST = sorted(list(set([

    "ADANIENT",
    "ADANIGREEN",
    "ADANIPORTS",
    "AKZOINDIA",
    "ATGL",
    "AFCONS",
    "ATL",
    "ANANTRAJ",
    "ANTHEM",
    "ARIHANTCAP",
    "ASIANPAINT",
    "BAJAJFINSV",
    "BEL",
    "BLUEDART",
    "BLS",
    "CASTROLIND",
    "CGPOWER",
    "CLEAN",
    "DBL",
    "EID PARRY",
    "FILATEX",
    "FORTIS",
    "GILLETTE",
    "GLOBUSSPR",
    "GSFC",
    "HDFCBANK",
    "HINDCOPPER",
    "HINDUNILVR",
    "HYUNDAI",
    "ITBEES",
    "ICICIAMC",
    "ICICIBANK",
    "IDBI",
    "IFCI",
    "INDUSTOWER",
    "CCAVENUE",
    "INFY",
    "IRB",
    "IRCTC",
    "JIOFIN",
    "JPASSOCIAT",
    "JSWENERGY",
    "KWIL",
    "LATENTVIEW",
    "LGEINDIA",
    "LOTUSDEV",
    "LLOYDSENGG",
    "LT",
    "MARUTI",
    "MAZDOCK",
    "MIRZAINT",
    "MENON PISTON",
    "NATCOPHARM",
    "ONGC",
    "ORIENTCEM",
    "PIDILITIND",
    "POONAWALA",
    "PVRINOX",
    "RTNPOWER",
    "RELIANCE",
    "RELINFRA",
    "RVNL",
    "SANGHI IND",
    "SBIN",
    "SRHHYPOLTD",
    "SUVIDHAA INFO",
    "SUPREMEIND",
    "SUZLON",
    "SWIGGY",
    "SYMPHONY",
    "TATATECH",
    "TITAN",
    "TRENT",
    "VBL"

])))

print("======================================")
print("TOTAL UNIQUE STOCKS:", len(WATCHLIST))
print("======================================")

CHECK_INTERVAL = 120

IMPORTANT_KEYWORDS = [

    "order",
    "acquisition",
    "results",
    "board meeting",
    "dividend",
    "fund raising",
    "buyback",
    "merger",
    "credit rating",
    "contract",
    "stake",
    "investment",
    "approval",
    "expansion",
    "guidance",
    "profit",
    "loss",
    "sebi",
    "penalty",
    "bankruptcy",
    "default",
    "allotment",
    "bonus",
    "split",
    "rights issue",
    "joint venture"

]

SEEN_FILE = "seen_alerts.json"

# =========================================================
# LOAD PREVIOUS ALERTS
# =========================================================

if os.path.exists(SEEN_FILE):

    with open(SEEN_FILE, "r") as f:

        seen_alerts = set(json.load(f))

else:

    seen_alerts = set()

print("Previously stored alerts:", len(seen_alerts))

# =========================================================
# SAVE ALERTS
# =========================================================

def save_seen_alerts():

    with open(SEEN_FILE, "w") as f:

        json.dump(list(seen_alerts), f)

# =========================================================
# TELEGRAM FUNCTION
# =========================================================

def send_telegram(message):

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        payload = {

            "chat_id": CHAT_ID,
            "text": message

        }

        response = requests.post(url, data=payload)

        print("Telegram Status:", response.status_code)

    except Exception as e:

        print("Telegram Error:", e)

# =========================================================
# SIMPLE NEWS COMMENT ENGINE
# =========================================================

def generate_comment(headline):

    headline = headline.lower()

    positive_keywords = [

        "order",
        "contract",
        "profit",
        "acquisition",
        "approval",
        "growth",
        "expansion",
        "investment",
        "buyback",
        "dividend",
        "upgrade",
        "partnership",
        "deal"

    ]

    negative_keywords = [

        "loss",
        "penalty",
        "fraud",
        "default",
        "bankruptcy",
        "downgrade",
        "sebi action",
        "decline",
        "fall",
        "warning",
        "investigation"

    ]

    for word in positive_keywords:

        if word in headline:

            return "Positive News → Possible bullish impact"

    for word in negative_keywords:

        if word in headline:

            return "Negative News → Possible bearish impact"

    return "Neutral News → Monitor further developments"

# =========================================================
# STARTUP MESSAGE
# =========================================================

startup_message = f"""
✅ STOCK BOT STARTED

Time:
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Stocks Loaded:
{len(WATCHLIST)}

Stored Alerts:
{len(seen_alerts)}
"""

send_telegram(startup_message)

# =========================================================
# FETCH NSE ANNOUNCEMENTS
# =========================================================

def fetch_nse_announcements():

    try:

        url = "https://www.nseindia.com/api/corporate-announcements?index=equities"

        data = nsefetch(url)

        return data

    except Exception as e:

        print("NSE Fetch Error:", e)

        return []

# =========================================================
# PROCESS NSE ANNOUNCEMENTS
# =========================================================

def process_nse_announcements():

    print("\nChecking NSE announcements...")

    data = fetch_nse_announcements()

    print("Total NSE announcements:", len(data))

    for item in data:

        try:

            symbol = item.get("symbol", "").strip().upper()

            if symbol not in WATCHLIST:
                continue

            headline = item.get("subject", "").strip()

            if not headline:
                continue

            headline_lower = headline.lower()

            matched = any(
                keyword in headline_lower
                for keyword in IMPORTANT_KEYWORDS
            )

            if not matched:
                continue

            unique_key = f"NSE-{symbol}-{headline}"

            if unique_key in seen_alerts:
                continue

            seen_alerts.add(unique_key)

            save_seen_alerts()

            attachment = item.get("attchmntFile", "")

            nse_link = ""

            if attachment:
                nse_link = f"https://www.nseindia.com{attachment}"

            comment = generate_comment(headline)

            message = f"""
🚨 NSE ANNOUNCEMENT

Stock:
{symbol}

Headline:
{headline}

Comment:
{comment}

Source:
{nse_link}

Time:
{datetime.now().strftime('%H:%M:%S')}
"""

            print(message)

            send_telegram(message)

        except Exception as e:

            print("NSE Processing Error:", e)

# =========================================================
# FETCH GOOGLE NEWS
# =========================================================

def fetch_google_news(stock):

    try:

        rss_url = f"https://news.google.com/rss/search?q={stock}+stock"

        feed = feedparser.parse(rss_url)

        return feed.entries

    except Exception as e:

        print("News Fetch Error:", e)

        return []

# =========================================================
# PROCESS INTERNET NEWS
# =========================================================

def process_internet_news():

    print("\nChecking Internet News...")

    for stock in WATCHLIST:

        try:

            entries = fetch_google_news(stock)

            for entry in entries[:3]:

                headline = entry.title.strip()

                if not headline:
                    continue

                headline_lower = headline.lower()

                matched = any(
                    keyword in headline_lower
                    for keyword in IMPORTANT_KEYWORDS
                )

                if not matched:
                    continue

                unique_key = f"NEWS-{stock}-{headline}"

                if unique_key in seen_alerts:
                    continue

                seen_alerts.add(unique_key)

                save_seen_alerts()

                news_link = entry.link

                comment = generate_comment(headline)

                message = f"""
📰 INTERNET NEWS

Stock:
{stock}

Headline:
{headline}

Comment:
{comment}

Source:
{news_link}

Time:
{datetime.now().strftime('%H:%M:%S')}
"""

                print(message)

                send_telegram(message)

        except Exception as e:

            print("Internet News Error:", e)

# =========================================================
# HEARTBEAT MESSAGE
# =========================================================

def send_heartbeat():

    message = f"""
🤖 BOT RUNNING

Time:
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Stocks:
{len(WATCHLIST)}

Stored Alerts:
{len(seen_alerts)}

Next Check:
{CHECK_INTERVAL} sec
"""

    send_telegram(message)

# =========================================================
# MAIN LOOP
# =========================================================

print("======================================")
print("BOT STARTED")
print("======================================")

while True:

    try:

        print("\n======================================")
        print("NEW CYCLE")
        print(datetime.now())
        print("======================================")

        process_nse_announcements()

        process_internet_news()

        send_heartbeat()

        print(f"\nSleeping {CHECK_INTERVAL} sec...\n")

    except Exception as e:

        error_message = f"""
❌ BOT ERROR

{str(e)}

Time:
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        print(error_message)

        send_telegram(error_message)

    time.sleep(CHECK_INTERVAL)
```
