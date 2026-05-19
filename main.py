"""
SS.lv -> Telegram pazinojumu bots (v4 - GitHub Actions versija)
Vienreizeja izpilde - bez "while True" cikla.
GitHub Actions palaiz so skriptu reizi stunda automatiski.
"""

import os
import json
import sys
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# === KONFIGURACIJA NO VIDES MAINIGAJIEM ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SEARCH_URLS = {
    "Agenskalns": "https://www.ss.com/lv/real-estate/flats/riga/agenskalns/sell/",
    "Imanta":     "https://www.ss.com/lv/real-estate/flats/riga/imanta/sell/",
    "Zolitude":   "https://www.ss.com/lv/real-estate/flats/riga/zolitude/sell/",
    "Ilguciems":  "https://www.ss.com/lv/real-estate/flats/riga/ilguciems/sell/",
}
WANTED_ROOMS = {"3", "4"}
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
        ads.append({
            "id": ad_id,
            "url": ad_url,
            "title": title,
            "street": details[0],
            "rooms": details[1],
            "area": details[2],
            "floor": details[3],
            "series": details[4],
            "price_m2": details[5],
            "price": details[6],
        })
    return ads


def send_telegram(ad: dict, region: str) -> bool:
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

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
    log.info(f"  Atrasti {len(all_ads)} sludinajumi (visi)")
    filtered = [a for a in all_ads if a["rooms"] in WANTED_ROOMS]
    log.info(f"  No tiem {len(filtered)} ar 3-4 istabam")
    return filtered


def main():
    log.info("=== SS.lv Telegram bots (GitHub Actions) ===")

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Nav iestatits TELEGRAM_TOKEN vai TELEGRAM_CHAT_ID!")
        sys.exit(1)

    log.info(f"Token garums: {len(TELEGRAM_TOKEN)}, Chat ID: {TELEGRAM_CHAT_ID}")

    seen = load_seen()
    log.info(f"Ieladeti {len(seen)} jau redzeti sludinajumi")

    # Pirma palaisana - tikai apzimet visus kā redzetus, NEsuta
    first_run = len(seen) == 0
    if first_run:
        log.info("Pirma palaisana - tikai iezimeju esosos sludinajumus...")

    new_count = 0
    for region, url in SEARCH_URLS.items():
        ads = collect_ads(region, url)
        for ad in ads:
            if ad["id"] in seen:
                continue
            if first_run:
                seen.add(ad["id"])
            else:
                if send_telegram(ad, region):
                    seen.add(ad["id"])
                    new_count += 1

    save_seen(seen)

    if first_run:
        log.info(f"Sakuma stavoklis: {len(seen)} sludinajumi atzimeti ka redzeti")
    elif new_count > 0:
        log.info(f"Nosutiti {new_count} jauni sludinajumi")
    else:
        log.info("Jaunu sludinajumu nav")

    log.info("=== Pabeidzu ===")


if __name__ == "__main__":
    main()
