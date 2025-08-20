import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Основная страница б/у авто
AUTO24_SEARCH = "https://www.auto24.ee/soidukid/kasutatud/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

BRAND_CANON = {
    "vw": "Volkswagen", "volkswagen": "Volkswagen",
    "mercedes": "Mercedes-Benz", "mercedes-benz": "Mercedes-Benz",
    "škoda": "Skoda", "skoda": "Skoda",
}
BRAND_LIST = [
    "Toyota","BMW","Mercedes","Mercedes-Benz","Skoda","Škoda","VW","Volkswagen","Audi",
    "Volvo","Honda","Ford","Nissan","Hyundai","Kia","Peugeot","Opel","Mazda","Renault"
]

def _norm_url(href: str) -> Optional[str]:
    if not href:
        return None
    if href.startswith("/"):
        return "https://www.auto24.ee" + href
    if href.startswith("http"):
        return href
    return None

def _canon_brand(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().lower()
    if s in BRAND_CANON:
        return BRAND_CANON[s]
    for b in ["toyota","bmw","audi","volvo","honda","ford","nissan","hyundai","kia","peugeot","opel","mazda","renault"]:
        if s == b:
            return raw.strip().title()
    # попытка “Mercedes-Benz”
    if "mercedes" in s:
        return "Mercedes-Benz"
    return raw.strip()

def _extract_int(pattern: str, text: str) -> Optional[int]:
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    try:
        return int(m.group(1).replace(" ", "").replace("\u00a0", ""))
    except Exception:
        return None

def _extract_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", text)
    return int(m.group(1)) if m else None

def _guess_brand(text: str) -> Optional[str]:
    low = text.lower()
    for b in BRAND_LIST:
        if b.lower() in low:
            return _canon_brand(b)
    return None

def _parse_card_generic(a_tag) -> Dict[str, Any]:
    """Запасной универсальный парсер карточки вокруг ссылки."""
    card = a_tag.find_parent(["article","div","li"]) or a_tag
    text = " ".join(card.get_text(" ").split())
    title = a_tag.get_text(strip=True) or "Listing"
    price = _extract_int(r"(\d[\d\s]{2,})\s*€", text)
    km = _extract_int(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
    year = _extract_year(text)
    brand = _guess_brand(text)
    return title, price, year, km, brand

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    """
    Многослойный парсер:
    1) Ищем <a> со ссылками на /soidukid/... c id=123456
    2) Если найдены “карты” с data-id/role/article — парсим оттуда
    3) Если нет — эвристика по ближайшему контейнеру
    Возвращаем до 60 уникальных объявлений.
    """
    items: List[Dict[str, Any]] = []

    async with session.get(AUTO24_SEARCH, headers=HEADERS) as resp:
        status = resp.status
        html = await resp.text()

    if status != 200 or not html:
        return items

    soup = BeautifulSoup(html, "html.parser")

    # Попытка 1: карточки с data-id (часто встречается)
    cards = []
    for tag in soup.select("[data-id]"):
        try:
            ad_id = tag.get("data-id")
            if ad_id and ad_id.isdigit():
                cards.append(tag)
        except Exception:
            pass

    if cards:
        for tag in cards:
            # ищем ссылку внутри
            a = tag.find("a", href=True)
            if not a:
                continue
            url = _norm_url(a["href"])
            if not url or "/soidukid/" not in url:
                continue

            title = a.get_text(strip=True) or "Listing"
            # текст всей карточки
            text = " ".join(tag.get_text(" ").split())
            price = _extract_int(r"(\d[\d\s]{2,})\s*€", text)
            km = _extract_int(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
            year = _extract_year(text)
            brand = _guess_brand(text)

            items.append({
                "id": f"auto24:{tag.get('data-id')}",
                "site": "auto24.ee",
                "url": url,
                "title": title,
                "price_eur": price,
                "year": year,
                "odometer_km": km,
                "brand": brand,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })

    # Попытка 2: любые ссылки с id= в URL
    links = soup.find_all("a", href=True)
    for a in links:
        url = _norm_url(a["href"])
        if not url or "/soidukid/" not in url:
            continue
        m = re.search(r"id=(\d+)", url)
        if not m:
            continue
        ad_id = m.group(1)

        title, price, year, km, brand = _parse_card_generic(a)

        items.append({
            "id": f"auto24:{ad_id}",
            "site": "auto24.ee",
            "url": url,
            "title": title,
            "price_eur": price,
            "year": year,
            "odometer_km": km,
            "brand": brand,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    # Дедупликация по id + ограничение
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)

    return uniq[:60]
