import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

URL = "https://www.listingsproject.com/real-estate/new-york-city/sublets?page=19"
BASE = "https://www.listingsproject.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; scraper/1.0)"}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def parse_listings(html):
    soup = BeautifulSoup(html, "lxml")
    results = []
    containers = soup.select("div.flex.flex-col.md\\:flex-row.mb-6")
    for c in containers:
        # find link to listing; skip if none (likely an ad)
        a = c.find("a", href=lambda h: h and h.startswith("/listings/"))
        if not a:
            continue
        link = urljoin(BASE, a["href"])
        # find price string (span starting with $)
        price_tag = c.find(lambda tag: tag.name == "span" and tag.get_text(strip=True).startswith("$"))
        price = price_tag.get_text(strip=True) if price_tag else None
        results.append({"price": price, "link": link})
    return results

if __name__ == "__main__":
    html = fetch(URL)
    items = parse_listings(html)
    for i, it in enumerate(items, 1):
        print(f"{i}. {it['price'] or 'N/A'} — {it['link']}")
