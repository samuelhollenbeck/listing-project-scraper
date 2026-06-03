# main.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml python-dateutil

import re
import time
import requests
import sqlite3
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import dateutil.parser

BASE = "https://www.listingsproject.com"
PAGE_URL = BASE + "/real-estate/new-york-city/sublets?page={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; scraper/1.0)"}
DELAY = 1.0  # seconds between requests
MAX_PAGES = 5  # set x here (1..MAX_PAGES)

DB = "listings.db"

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS listings (
        id INTEGER PRIMARY KEY,
        url TEXT UNIQUE,
        raw_price_text TEXT,
        normalized_price_month REAL,
        price TEXT,
        title TEXT,
        location TEXT,
        date_range TEXT,
        start_date TEXT,
        end_date TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    return conn

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def months_from_days(days):
    return days / 30.44  # average month length

def parse_price(raw, start_iso=None, end_iso=None):
    """
    Returns (raw_text, monthly_value_or_None).
    - If raw contains /day, /week, /month -> convert accordingly.
    - If no unit, and start_iso & end_iso provided -> treat value as total for range and prorate to months.
    - If no unit and no dates -> assume monthly (fallback).
    """
    if not raw:
        return (None, None)
    s = raw.strip().replace("\xa0", " ")
    m = re.search(r"\$[\d,]+(?:\.\d+)?", s)
    if not m:
        return (s, None)
    val = float(m.group(0).replace("$", "").replace(",", ""))
    low = s.lower()

    unit = None
    if "/day" in low or " per day" in low or (("day" in low) and "/day" in low):
        unit = "day"
    elif "/week" in low or "week" in low:
        unit = "week"
    elif "/month" in low or "month" in low:
        unit = "month"
    else:
        unit = None

    if unit == "day":
        monthly = round(val * 365.0 / 12.0)
    elif unit == "week":
        monthly = round(val * 52.0 / 12.0)
    elif unit == "month":
        monthly = round(val)
    else:
        # no unit: treat val as total for the listing period if dates available
        monthly = None
        if start_iso and end_iso:
            try:
                start = datetime.fromisoformat(start_iso)
                end = datetime.fromisoformat(end_iso)
                days = (end - start).days
                if days <= 0:
                    # if same-day or invalid, fallback to monthly assumption
                    monthly = round(val)
                else:
                    months = months_from_days(days)
                    monthly = round(val / months)
            except Exception:
                monthly = round(val)  # fallback
        else:
            # fallback: assume monthly
            monthly = round(val)
    return (s, monthly)

def parse_date_range(raw):
    if not raw:
        return (None, None, None)
    txt = raw.strip()
    parts = [p.strip() for p in txt.split(" - ")]
    start = end = None
    try:
        if len(parts) >= 1 and parts[0]:
            start = dateutil.parser.parse(parts[0], fuzzy=True).date().isoformat()
        if len(parts) >= 2 and parts[1]:
            end = dateutil.parser.parse(parts[1], fuzzy=True).date().isoformat()
    except Exception:
        start = end = None
    return (txt, start, end)

def parse_listings(html):
    soup = BeautifulSoup(html, "lxml")
    results = []
    containers = soup.select("div.flex.flex-col.md\\:flex-row.mb-6")
    for c in containers:
        a = c.find("a", href=lambda h: h and h.startswith("/listings/"))
        if not a:
            continue
        link = urljoin(BASE, a["href"])

        # date range span: often another span with date text (not guaranteed)
        date_tag = None
        # try to find a span containing a month name and a hyphen
        for span in c.find_all("span"):
            txt = span.get_text(" ", strip=True)
            if re.search(r"[A-Za-z]{3,}\s+\d{1,2},\s*\d{4}", txt) and "-" in txt:
                date_tag = span
                break
        date_raw = date_tag.get_text(" ", strip=True) if date_tag else None
        date_range, start_date, end_date = parse_date_range(date_raw)

        # price span (first span that starts with $) and date span (looks like "June 20, 2026 - July 12, 2026")
        price_tag = c.find(lambda tag: tag.name == "span" and tag.get_text(strip=True).startswith("$"))
        raw_price = price_tag.get_text(" ", strip=True) if price_tag else None
        raw_price_text, normalized_price_month = parse_price(raw_price, start_date, end_date)

        title_tag = c.find("h4")
        title = title_tag.get_text(" ", strip=True) if title_tag else None

        loc_tag = c.find("div", class_="text-grey-dark font-semibold text-smish")
        location = loc_tag.get_text(" ", strip=True) if loc_tag else None

        results.append({
            "url": link,
            "raw_price_text": raw_price_text,
            "normalized_price_month": normalized_price_month,
            "price": raw_price,  # keep original price string too
            "title": title,
            "location": location,
            "date_range": date_range,
            "start_date": start_date,
            "end_date": end_date,
        })
    return results

def save_listing(conn, item):
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO listings
               (url, raw_price_text, normalized_price_month, price, title, location, date_range, start_date, end_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["url"],
                item["raw_price_text"],
                item["normalized_price_month"],
                item["price"],
                item["title"],
                item["location"],
                item["date_range"],
                item["start_date"],
                item["end_date"],
            )
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate

def main(max_pages=MAX_PAGES):
    conn = init_db()
    added = 0
    skipped = 0
    for page in range(1, max_pages + 1):
        url = PAGE_URL.format(page)
        try:
            html = fetch(url)
        except Exception as e:
            print(f"Failed to fetch page {page}: {e}")
            continue
        items = parse_listings(html)
        for it in items:
            if save_listing(conn, it):
                added += 1
                print(f"Added: ${it['normalized_price_month'] or 'N/A'}/month — {it['url']}")
            else:
                skipped += 1
        time.sleep(DELAY)
    print(f"Done. Added: {added}, Duplicates skipped: {skipped}")
    conn.close()

if __name__ == "__main__":
    main()
