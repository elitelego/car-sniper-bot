import re
from typing import List, Dict, Any
from datetime import datetime, timezone

from bs4 import BeautifulSoup

AUTO24_SEARCH = "https://www.auto24.ee/soidukid/kasutatud/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CarSniperBot/0.1; +https://example.com)"
}

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    """
    Minimalistic parser that tries to discover latest listings
    on the first page of Auto24 used cars list.
    NOTE: This is a heuristic and may break if markup changes.
    """
    url = AUTO24_SEARCH
    async with session.get(url, headers=HEADERS) as resp:
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Heuristics: find anchors pointing to detail pages that look like '/soidukid/used/...id=XXXX'
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "auto24.ee" not in href:
            full = "https://www.auto24.ee" + href if href.startswith("/") else None
        else:
            full = href

        if not full or "/soidukid/" not in full:
            continue

        # Normalize id
        m = re.search(r"id=(\d+)", full)
        if not m:
            continue
        ad_id = m.group(1)

        # Try to grab the card container to extract text (title/price/year/km/brand)
        card = a.find_parent(["article", "div", "li"]) or a
        text = " ".join(card.get_text(" ").split())
        title = a.get_text(strip=True) or "Auto24 Listing"

        # Extract numbers
        price = None
        mprice = re.search(r"(\d[\d\s]{2,})\s*€", text)
        if mprice:
            price = int(mprice.group(1).replace(" ", ""))

        year = None
        myear = re.search(r"\b(20\d{2}|19\d{2})\b", text)
        if myear:
            year = int(myear.group(1))

        km = None
        mkm = re.search(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
        if mkm:
            km = int(mkm.group(1).replace(" ", ""))

        # crude brand from title
        brand = None
        for b in ["Toyota","BMW","Mercedes","Mercedes-Benz","Skoda","Škoda","VW","Volkswagen","Audi"]:
            if b.lower() in text.lower():
                brand = "Volkswagen" if b.lower() in ["vw","volkswagen"] else b
                break

        items.append({
            "id": f"auto24:{ad_id}",
            "site": "auto24.ee",
            "url": full,
            "title": title,
            "price_eur": price,
            "year": year,
            "odometer_km": km,
            "brand": brand,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        })

    # Deduplicate by id
    seen = set()
    uniq = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)

    # Only keep a reasonable number
    return uniq[:60]
