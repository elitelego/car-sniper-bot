import os
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Используем мобильную выдачу как основную — она у тебя даёт 200 OK
MOBILE_URL  = "https://m.auto24.ee/soidukid/kasutatud/"
DESKTOP_URL = "https://www.auto24.ee/soidukid/kasutatud/"  # запасной

# Если задан SCRAPER_URL_TMPL, все запросы пойдут через него:
# пример для ScraperAPI:
# SCRAPER_URL_TMPL = "https://api.scraperapi.com/?api_key=XXX&country_code=EE&keep_headers=true&url={url}"
SCRAPER_URL_TMPL = os.getenv("SCRAPER_URL_TMPL")

HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "et-EE,et;q=0.9,en;q=0.8,ru;q=0.7",
    "Referer": "https://m.auto24.ee/",
    "Cache-Control": "no-cache",
}

BRAND_LIST = [
    "Toyota","BMW","Mercedes","Mercedes-Benz","Skoda","Škoda","VW","Volkswagen","Audi",
    "Volvo","Honda","Ford","Nissan","Hyundai","Kia","Peugeot","Opel","Mazda","Renault"
]
CANON = {"vw":"Volkswagen","volkswagen":"Volkswagen","mercedes":"Mercedes-Benz","mercedes-benz":"Mercedes-Benz","škoda":"Skoda","skoda":"Skoda"}

def _prox(url: str) -> str:
    return SCRAPER_URL_TMPL.format(url=url) if SCRAPER_URL_TMPL else url

def _norm_url(href: str) -> Optional[str]:
    if not href:
        return None
    if href.startswith("/"):
        # мобилка всегда под доменом m.auto24.ee
        return "https://m.auto24.ee" + href
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

def _parse_card_text(tag) -> Dict[str, Any]:
    """Извлекаем данные из ближайшего контейнера карточки."""
    card = tag.find_parent(["article","div","li"]) or tag
    text = " ".join(card.get_text(" ").split())
    title = tag.get_text(strip=True) or "Listing"
    price = _extract_int(r"(\d[\d\s]{2,})\s*€", text)
    km    = _extract_int(r"(\d[\d\s]{2,})\s*(?:km|KM)", text)
    year  = _extract_year(text)
    brand = _guess_brand(text)
    return title, price, year, km, brand

def _extract_ad_id(url: str) -> Optional[str]:
    """
    Поддержим несколько вариантов:
    - ...id=123456...
    - .../kuulutus/123456...
    - .../id/123456...
    """
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{5,})($|/|\?)", url)  # любое число 5+ знаков в path
    if m:
        return m.group(1)
    return None

def _collect_from_mobile(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # 1) Карточки с data-id (если есть)
    for tag in soup.select("[data-id]"):
        ad_id = tag.get("data-id")
        if not ad_id or not str(ad_id).isdigit():
            continue
        a = tag.find("a", href=True) or tag
        url = _norm_url(a.get("href"))
        if not url: continue
        title, price, year, km, brand = _parse_card_text(a)
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

    # 2) Любая ссылка, похожая на объявление
    for a in soup.find_all("a", href=True):
        url = _norm_url(a["href"])
        if not url:
            continue
        # отсекаем явные служебные ссылки
        if "session.php" in url or "login.php" in url:
            continue
        if "soidukid" not in url:
            continue

        ad_id = _extract_ad_id(url)
        if not ad_id:
            continue

        title, price, year, km, brand = _parse_card_text(a)
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

async def _fetch_html(session, url: str) -> tuple[int, str]:
    # Возврат: (status, html)
    prox_url = _prox(url)
    async with session.get(prox_url, headers=HDRS) as resp:
        status = resp.status
        html = await resp.text()
    return status, html or ""

async def fetch_latest_listings(session) -> List[Dict[str, Any]]:
    """Берём мобильную выдачу (при 200) и парсим карточки. Десктоп — запасной."""
    all_items: List[Dict[str, Any]] = []

    # mobile — приоритетно (у тебя 200 и много ссылок)
    try:
        st, html = await _fetch_html(session, MOBILE_URL)
        if st == 200 and html:
            soup = BeautifulSoup(html, "html.parser")
            all_items += _collect_from_mobile(soup)
    except Exception:
        pass

    # desktop — как дополнительный источник (может быть 403)
    try:
        st, html = await _fetch_html(session, DESKTOP_URL)
        if st == 200 and html:
            soup = BeautifulSoup(html, "html.parser")
            all_items += _collect_from_mobile(soup)  # мобильный сборщик тоже справится
    except Exception:
        pass

    # ограничение
    uniq: List[Dict[str, Any]] = []
    seen = set()
    for it in all_items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)

    return uniq[:60]

async def debug_fetch(session):
    """Диагностика сети/HTML: статусы, размеры и примеры ссылок с учётом прокси."""
    out = {
        "desktop_status": None, "desktop_len": 0, "desktop_links": 0,
        "mobile_status": None, "mobile_len": 0, "mobile_links": 0,
        "sample_links": []
    }

    # desktop
    try:
        st, html = await _fetch_html(session, DESKTOP_URL)
        out["desktop_status"] = st
        out["desktop_len"] = len(html or "")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            links = [a.get("href") for a in soup.find_all("a", href=True)]
            out["desktop_links"] = len(links)
            out["sample_links"] += [str(_norm_url(l) or l) for l in links[:3]]
    except Exception as e:
        out["sample_links"].append(f"desktop error: {e}")

    # mobile
    try:
        st, html = await _fetch_html(session, MOBILE_URL)
        out["mobile_status"] = st
        out["mobile_len"] = len(html or "")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            links = [a.get("href") for a in soup.find_all("a", href=True)]
            out["mobile_links"] = len(links)
            out["sample_links"] += [str(_norm_url(l) or l) for l in links[:3]]
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
