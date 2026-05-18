"""
SS.lv -> Telegram pazinojumu bots (v2)
Seko 3-4 istabu dzivokliem rajonos: Agenskalns, Imanta, Zolitude, Ilguciems
Parbauda ik pec 1 stundas un suta tikai JAUNUS sludinajumus.
"""

import os
import json
import time
import logging
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# === KONFIGURACIJA ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "IELIEC_SAVU_TOKENU_SEIT")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "IELIEC_SAVU_CHAT_ID_SEIT")

# Viens URL katram rajonam - filtru pa istabam veicam koda
SEARCH_URLS = {
    "Agenskalns": "https://www.ss.com/lv/real-estate/flats/riga/agenskalns/sell/",
    "Imanta":     "https://www.ss.com/lv/real-estate/flats/riga/imanta/sell/",
    "Zolitude":   "https://www.ss.com/lv/real-estate/flats/riga/zolitude/sell/",
    "Ilguciems":  "https://www.ss.com/lv/real-estate/flats/riga/ilguciems/sell/",
}

# Istabu skaits, ko meklejam
WANTED_ROOMS = {"3", "4"}

CHECK_INTERVAL_SECONDS = 60 * 60  # 1 stunda
SEEN_FILE = Path("seen_ads.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            log.warning(f"Nevareja nolasit {SEEN_FILE}: {e}")
    return set()


def save_seen(seen: set) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def fetch_page(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "lv,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.error(f"Nevareja iegut {url}: {e}")
        return None


def parse_ads(html: str) -> list[dict]:
    """
    Parse sludinajumu sarakstu no ss.lv HTML lapas.

    Tabulas kolonas pec saites:
    [Iela] [Istabas] [m^2] [Stavs] [Serija] [Cena/m2] [Cena]
    """
    soup = BeautifulSoup(html, "html.parser")
    ads = []

    for tr in soup.find_all("tr", id=lambda x: x and x.startswith("tr_")):
        tr_id = tr.get("id", "")
        if "bnr" in tr_id.lower():
            continue

        link_tag = tr.find("a", id=lambda x: x and x.startswith("dm_"))
        if not link_tag:
            continue

        ad_id = link_tag.get("id", "").replace("dm_", "")
        href = link_tag.get("href", "")
        ad_url = "https://www.ss.com" + href if href.startswith("/") else href
        title = link_tag.get_text(strip=True)

        cells = tr.find_all("td", class_=lambda c: c and "msga2-o" in c)
        details = [c.get_text(strip=True) for c in cells]

        if len(details) < 7:
            continue

        street  = details[0]
        rooms   = details[1]
        area    = details[2]
        floor   = details[3]
        series  = details[4]
        ppm2    = details[5]
        price   = details[6]

        ads.append({
            "id": ad_id,
            "url": ad_url,
            "title": title,
            "street": street,
            "rooms": rooms,
            "area": area,
            "floor": floor,
            "series": series,
            "price_m2": ppm2,
            "price": price,
        })

    return ads


def send_telegram(ad: dict, region: str) -> bool:
    """Suta vienkarsu HTML formatētu Telegram ziņu."""
    def esc(s: str) -> str:
        # HTML escape - vienkarsaks neka MarkdownV2
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    text = (
        f"🏠 <b>Jauns sludinajums — {esc(region)}</b>\n\n"
        f"📍 {esc(ad['street'])}\n"
        f"🚪 {esc(ad['rooms'])} ist. | 📐 {esc(ad['area'])} m² | 🪜 {esc(ad['floor'])}\n"
        f"🏗 {esc(ad['series'])}\n"
        f"💰 <b>{esc(ad['price'])}</b> ({esc(ad['price_m2'])}/m²)\n\n"
        f"📝 {esc(ad['title'][:200])}\n\n"
        f'<a href="{ad["url"]}">Skatit sludinajumu</a>'
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(api_url, json=payload, timeout=15)
        if r.status_code == 200:
            return True
        log.error(f"Telegram kluda: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"Telegram suttiisanas kluda: {e}")
    return False


def collect_ads(region: str, url: str) -> list[dict]:
    log.info(f"Parbaudu: {region}")
    html = fetch_page(url)
    if not html:
        return []

    all_ads = parse_ads(html)
    log.info(f"  Atrasti {len(all_ads)} sludinajumi (visi istabu skaiti)")

    filtered = [a for a in all_ads if a["rooms"] in WANTED_ROOMS]
    log.info(f"  No tiem {len(filtered)} ar 3-4 istabam")
    return filtered


def run_once(seen: set) -> set:
    new_count = 0
    for region, url in SEARCH_URLS.items():
        ads = collect_ads(region, url)
        for ad in ads:
            if ad["id"] in seen:
                continue
            if send_telegram(ad, region):
                seen.add(ad["id"])
                new_count += 1
                time.sleep(1)
        time.sleep(3)

    if new_count > 0:
        log.info(f"Nosutiti {new_count} jauni sludinajumi")
        save_seen(seen)
    else:
        log.info("Jaunu sludinajumu nav")
    return seen


def main():
    log.info("=== SS.lv Telegram bots (v2) startejas ===")
    if TELEGRAM_TOKEN.startswith("IELIEC") or TELEGRAM_CHAT_ID.startswith("IELIEC"):
        log.error("Ludzu, iestatiet TELEGRAM_TOKEN un TELEGRAM_CHAT_ID!")
        return

    seen = load_seen()
    log.info(f"Ieladeti {len(seen)} jau redzeti sludinajumi")

    if not seen:
        log.info("Pirma palaisana - iezimeju esosos sludinajumus ka redzetus...")
        for region, url in SEARCH_URLS.items():
            ads = collect_ads(region, url)
            for ad in ads:
                seen.add(ad["id"])
            time.sleep(2)
        save_seen(seen)
        log.info(f"Sakuma stavoklis: {len(seen)} sludinajumi atzimeti ka redzeti")

    while True:
        try:
            seen = run_once(seen)
        except Exception as e:
            log.exception(f"Negaidita kluda: {e}")
        log.info(f"Gulu {CHECK_INTERVAL_SECONDS // 60} min...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
