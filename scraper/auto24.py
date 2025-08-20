import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from bs4 import BeautifulSoup

DESKTOP_URL = "https://www.auto24.ee/soidukid/kasutatud/"
MOBILE_URL  = "https://m.auto24.ee/soidukid/kasutatud/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

BRAND_LIST = [
    "Toyota","BMW","Mercedes","Mercedes-Benz","Skoda","Škoda","VW","Volkswagen","Audi",
    "Volvo","Honda","Ford","Nissan","Hyundai","Kia","Peugeot","Opel","Mazda","Renault"
]
CANON = {"vw":"Volkswagen","volkswagen":"Volkswagen","mercedes":"Mercedes-Benz","mercedes-benz":"Mercedes-Benz","škoda":"Skoda","skoda":"Skoda"}

def _norm_url(href: str) -> Optional[str]:
    if not href:
        return None
    if href.startswith("/"):
        return "https://www.auto24.ee" + href
    if href.startswith("http"):
        return href
    return None

def _canon_brand(raw: Optional[str]) -> Optional[str]:
    if not raw: return None
    s = raw.strip().lower()
    if s in CANON: return CANON[s]
    if "mercedes" in s: return "Mercedes-Benz"
    return raw.strip()

def _extract_int(pattern: str, text: str) -> Optional[int]:
    m = re.search(pattern, text, re.I)
    if not m: return None
    try:
        return int(m.group(1).replace(" ", "").replace("\u00a0", ""))
    except: return None

def _extract_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20\d{2}|19\d{2})\b", text)
    return int(m.group(1)) if m else None

def _guess_brand(text: str) -> Optional[str]:
    low = text.lower()
    for b in BRAND_LIST:
        if b.lower() in low:
            return _canon_brand(b)
    return None

def _parse_card_from_tag(tag) -> Dict[str, Any]:
    text = " ".join(tag.get_text(" ").split())
    a = tag.find("a", href=True) or tag
    url = _norm_url(a.get("href"))
    title = a.get_text(strip=True) or "Listing"
    price = _extract_int(r"(\d[\d\s]{2,})\s*€", text)
    km    = _extract_int(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
    year  = _extract_year(text)
    brand = _guess_brand(text)
    return title, url, price, km, year, brand

def _collect_from_soup(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # 1) Явные карточки с data-id
    for tag in soup.select("[data-id]"):
        ad_id = tag.get("data-id")
        if not ad_id or not str(ad_id).isdigit():
            continue
        title, url, price, km, year, brand = _parse_card_from_tag(tag)
        if not url or "/soidukid/" not in url:
            continue
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

    # 2) Любая ссылка с id= в URL
    for a in soup.find_all("a", href=True):
        url = _norm_url(a["href"])
        if not url or "/soidukid/" not in url:
            continue
        m = re.search(r"id=(\d+)", url)
        if not m:
            continue
        ad_id = m.group(1)

        # возьмём ближайший контейнер
        card = a.find_parent(["article","div","li"]) or a
        text = " ".join(card.get_text(" ").split())
        title = a.get_text(strip=True) or "Listing"
        price = _extract_int(r"(\d[\d\s]{2,})\s*€", text)
        km    = _extract_int(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
        year  = _extract_year(text)
        brand = _guess_brand(text)

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

    # дедуп
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    return uniq

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    """Пытаемся получить объявления с десктопа и мобилки; возвращаем до 60 уникальных."""
    all_items: List[Dict[str, Any]] = []

    # desktop
    try:
        async with session.get(DESKTOP_URL, headers=HEADERS) as resp:
            desktop_status = resp.status
            desktop_html = await resp.text()
        if desktop_status == 200 and desktop_html:
            soup = BeautifulSoup(desktop_html, "html.parser")
            all_items += _collect_from_soup(soup)
    except Exception:
        pass

    # mobile
    try:
        async with session.get(MOBILE_URL, headers=HEADERS) as resp:
            mobile_status = resp.status
            mobile_html = await resp.text()
        if mobile_status == 200 and mobile_html:
            soup = BeautifulSoup(mobile_html, "html.parser")
            all_items += _collect_from_soup(soup)
    except Exception:
        pass

    # ограничение
    uniq = []
    seen = set()
    for it in all_items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)

    return uniq[:60]

async def debug_fetch(session):
    """Диагностика сети/HTML: статусы, размеры и примеры ссылок"""
    out = {
        "desktop_status": None, "desktop_len": 0, "desktop_links": 0,
        "mobile_status": None, "mobile_len": 0, "mobile_links": 0,
        "sample_links": []
    }
    # desktop
    try:
        async with session.get(DESKTOP_URL, headers=HEADERS) as resp:
            out["desktop_status"] = resp.status
            html = await resp.text()
            out["desktop_len"] = len(html or "")
            if html:
                soup = BeautifulSoup(html, "html.parser")
                links = [a.get("href") for a in soup.find_all("a", href=True)]
                out["desktop_links"] = len(links)
                out["sample_links"] += [str(l) for l in links[:3]]
    except Exception as e:
        out["sample_links"].append(f"desktop error: {e}")

    # mobile
    try:
        async with session.get(MOBILE_URL, headers=HEADERS) as resp:
            out["mobile_status"] = resp.status
            html = await resp.text()
            out["mobile_len"] = len(html or "")
            if html:
                soup = BeautifulSoup(html, "html.parser")
                links = [a.get("href") for a in soup.find_all("a", href=True)]
                out["mobile_links"] = len(links)
                out["sample_links"] += [str(l) for l in links[:3]]
    except Exception as e:
        out["sample_links"].append(f"mobile error: {e}")

    # Уникальные первые ссылки
    seen = set()
    uniq = []
    for l in out["sample_links"]:
        if l in seen: continue
        seen.add(l)
        uniq.append(l)
    out["sample_links"] = uniq[:6]
    return out
