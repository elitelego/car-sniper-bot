import re
from typing import List, Dict, Any
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Первая страница раздела б/у авто
AUTO24_SEARCH = "https://www.auto24.ee/soidukid/kasutatud/"
HEADERS = {
    # Правдоподобный user-agent сильно помогает
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

def _norm_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("/"):
        return "https://www.auto24.ee" + href
    if href.startswith("http"):
        return href
    return None

def _extract_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(" ", ""))
    except Exception:
        return None

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    """
    Эвристический парсер: идём по всем ссылкам на странице и ищем те, где есть id=123456.
    Извлекаем базовые поля (цена, год, пробег, бренд) из близлежащего текста.
    Это MVP — разметка сайта может меняться.
    """
    items: List[Dict[str, Any]] = []

    async with session.get(AUTO24_SEARCH, headers=HEADERS) as resp:
        status = resp.status
        html = await resp.text()

    if status != 200 or not html:
        return items

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        full = _norm_url(a["href"])
        if not full or "/soidukid/" not in full:
            continue

        # Нужны только конкретные карточки с id=
        m = re.search(r"id=(\d+)", full)
        if not m:
            continue
        ad_id = m.group(1)

        # Возьмём ближайший контейнер с текстом
        card = a.find_parent(["article", "div", "li"]) or a
        text = " ".join(card.get_text(" ").split())
        title = a.get_text(strip=True) or "Listing"

        # Цена (в евро)
        price = _extract_int(r"(\d[\d\s]{2,})\s*€", text)
        # Год (любой 19xx или 20xx)
        year = _extract_int(r"\b(20\d{2}|19\d{2})\b", text)
        # Пробег
        km = _extract_int(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)

        # Бренд (по вхождению в текст)
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

    # Дедупликация + ограничение
    seen = set()
    uniq = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)

    return uniq[:60]
