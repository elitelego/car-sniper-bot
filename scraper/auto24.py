import re
from typing import List, Dict, Any
from datetime import datetime, timezone
from bs4 import BeautifulSoup

AUTO24_SEARCH = "https://www.auto24.ee/soidukid/kasutatud/"
HEADERS = {
    # важен нормальный User-Agent
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    """
    Эвристический парсер первой страницы. Ищет ссылки с id= и вытаскивает базовые поля.
    Маркап может меняться — это MVP.
    """
    items: List[Dict[str, Any]] = []

    async with session.get(AUTO24_SEARCH, headers=HEADERS) as resp:
        status = resp.status
        html = await resp.text()

    if status != 200 or not html:
        return items

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # нормализуем абсолютную ссылку
        if href.startswith("/"):
            full = "https://www.auto24.ee" + href
        elif href.startswith("http"):
            full = href
        else:
            continue

        # интересуют карточки объявлений
        if "/soidukid/" not in full:
            continue

        m = re.search(r"id=(\d+)", full)
        if not m:
            continue
        ad_id = m.group(1)

        # Пытаемся взять контейнер текста
        card = a.find_parent(["article", "div", "li"]) or a
        text = " ".join(card.get_text(" ").split())
        title = a.get_text(strip=True) or "Listing"

        # Цена (в евро)
        price = None
        mprice = re.search(r"(\d[\d\s]{2,})\s*€", text)
        if mprice:
            try:
                price = int(mprice.group(1).replace(" ", ""))
            except:
                pass

        # Год
        year = None
        myear = re.search(r"\b(20\d{2}|19\d{2})\b", text)
        if myear:
            try:
                year = int(myear.group(1))
            except:
                pass

        # Пробег
        km = None
        mkm = re.search(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
        if mkm:
            try:
                km = int(mkm.group(1).replace(" ", ""))
            except:
                pass

        # Бренд (грубо по тексту)
        brand = None
        brands = ["Toyota","BMW","Mercedes","Mercedes-Benz","Skoda","Škoda","VW","Volkswagen","Audi",
                  "Volvo","Honda","Ford","Nissan","Hyundai","Kia","Peugeot","Opel","Mazda","Renault"]
        lower = text.lower()
        for b in brands:
            if b.lower() in lower:
                if b.lower() in ["vw","volkswagen"]:
                    brand = "Volkswagen"
                elif "mercedes" in b.lower():
                    brand = "Mercedes-Benz"
                else:
                    brand = b
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
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    # дедуп
    seen = set()
    uniq = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)

    # ограничим чтобы не спамить
    return uniq[:60]
