# scraper for auto24.ee
import re
from typing import List, Dict, Any
from datetime import datetime, timezone
from bs4 import BeautifulSoup

AUTO24_SEARCH = "https://www.auto24.ee/soidukid/kasutatud/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    items = []
    async with session.get(AUTO24_SEARCH, headers=HEADERS) as resp:
        html = await resp.text()
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/soidukid/" not in href: continue
        full = "https://www.auto24.ee"+href if href.startswith("/") else href
        items.append({
            "id": full,
            "site": "auto24.ee",
            "url": full,
            "title": a.get_text(strip=True),
            "price_eur": None,
            "year": None,
            "odometer_km": None,
            "brand": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    return items[:20]
