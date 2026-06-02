# main.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import sqlite3

BASE = "https://www.listingsproject.com"
PAGE_URL = BASE + "/real-estate/new-york-city/sublets?page={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; scraper/1.0)"}
DELAY = 1.0  # seconds between requests
MAX_PAGES = 5  # set x here (1..MAX_PAGES)

# Persist results and dedupe using SQLite
DB = "listings.db"

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS listings (
        id INTEGER PRIMARY KEY,
        url TEXT UNIQUE,
        price TEXT,
        title TEXT,
        location TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    return conn

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def parse_listings(html):
    soup = BeautifulSoup(html, "lxml")
    results = []
    containers = soup.select("div.flex.flex-col.md\\:flex-row.mb-6")
    for c in containers:
        a = c.find("a", href=lambda h: h and h.startswith("/listings/"))
        if not a:
            continue
        link = urljoin(BASE, a["href"])
        price_tag = c.find(lambda tag: tag.name == "span" and tag.get_text(strip=True).startswith("$"))
        price = price_tag.get_text(strip=True) if price_tag else None
        # optional: extract title and location if present
        title_tag = c.find("h4")
        title = title_tag.get_text(strip=True) if title_tag else None
        loc_tag = c.find("div", class_="text-grey-dark font-semibold text-smish")
        location = loc_tag.get_text(strip=True) if loc_tag else None
        results.append({"url": link, "price": price, "title": title, "location": location})
    return results

def save_listing(conn, item):
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO listings (url, price, title, location) VALUES (?, ?, ?, ?)",
            (item["url"], item["price"], item["title"], item["location"])
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
                print(f"Added: {it['price'] or 'N/A'} — {it['url']}")
            else:
                skipped += 1
        time.sleep(DELAY)
    print(f"Done. Added: {added}, Duplicates skipped: {skipped}")
    conn.close()

if __name__ == "__main__":
    main()
