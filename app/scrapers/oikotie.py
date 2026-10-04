import requests
import re
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger("rental-radar.oikotie")

class OikotieScraper:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.search_cfg = config.get("search", {})
        self.user_agent = config.get("scraper", {}).get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fi,en-US;q=0.7,en;q=0.3",
        })

    def fetch_listings(self) -> List[Dict[str, Any]]:
        logger.info("Starting Oikotie scrape for %s...", self.search_cfg.get("location_name", "Taka-Töölö"))
        
        # Build search URL
        base_page_url = (
            "https://asunnot.oikotie.fi/vuokra-asunnot"
            "?pagination=1"
            "&locations=%5B%5B1652,4,%22Taka-T%C3%B6%C3%B6l%C3%B6,%20Helsinki%22%5D%5D"
            f"&price%5Bmax%5D={self.search_cfg.get('price_max', 1050)}"
            f"&size%5Bmin%5D={self.search_cfg.get('size_min', 27)}"
            f"&size%5Bmax%5D={self.search_cfg.get('size_max', 38)}"
            "&roomCount%5B%5D=1&roomCount%5B%5D=2"
            "&cardType=101"
            "&secondarySearchType=1"
        )

        try:
            resp = self.session.get(base_page_url, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.error("Failed to load Oikotie search page: %s", e)
            return []

        # Extract OTA tokens for internal cards API
        api_token = self._extract_meta(html, "api-token")
        loaded_token = self._extract_meta(html, "loaded")
        cuid_token = self._extract_meta(html, "cuid")

        headers = {
            "OTA-token": api_token or "",
            "OTA-loaded": loaded_token or "",
            "OTA-cuid": cuid_token or "",
            "Accept": "application/json, text/plain, */*",
            "Referer": base_page_url,
        }

        # Query cards API
        api_url = (
            "https://asunnot.oikotie.fi/api/cards"
            "?cardType=101"
            "&limit=50"
            "&offset=0"
            "&sortBy=published_sort_desc"
            "&locations=%5B%5B1652,4,%22Taka-T%C3%B6%C3%B6l%C3%B6,%20Helsinki%22%5D%5D"
            f"&price%5Bmax%5D={self.search_cfg.get('price_max', 1050)}"
            f"&size%5Bmin%5D={self.search_cfg.get('size_min', 27)}"
            f"&size%5Bmax%5D={self.search_cfg.get('size_max', 38)}"
            "&roomCount%5B%5D=1&roomCount%5B%5D=2"
        )

        listings = []
        try:
            api_resp = self.session.get(api_url, headers=headers, timeout=15)
            if api_resp.status_code == 200:
                data = api_resp.json()
                cards = data.get("cards", [])
                for card in cards:
                    parsed = self._parse_card(card)
                    if parsed:
                        listings.append(parsed)
                logger.info("Found %d listings from Oikotie API", len(listings))
            else:
                logger.warning("Oikotie API returned status %d. Falling back to HTML regex extract.", api_resp.status_code)
                listings = self._parse_from_html(html)
        except Exception as e:
            logger.warning("Error querying Oikotie cards API (%s), attempting HTML parse", e)
            listings = self._parse_from_html(html)

        return listings

    def _extract_meta(self, html: str, name: str) -> str:
        m = re.search(rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\']([^"\']+)["\']', html)
        return m.group(1) if m else ""

    def _parse_card(self, c: Dict[str, Any]) -> Dict[str, Any]:
        ext_id = str(c.get("id", ""))
        url = c.get("url") or f"https://asunnot.oikotie.fi/vuokrattavat-asunnot/helsinki/{ext_id}"
        
        # Primary image & media
        medias = c.get("medias", [])
        image_urls = []
        thumb = None
        for m in medias:
            if m.get("type") in ["IMAGE", "image"] and m.get("url"):
                image_urls.append(m["url"])
        if not image_urls and c.get("mainMedia", {}).get("url"):
            image_urls.append(c["mainMedia"]["url"])
        if image_urls:
            thumb = image_urls[0]

        price = None
        raw_price = c.get("price") or c.get("rent")
        if raw_price:
            try:
                price = float(raw_price)
            except (ValueError, TypeError):
                pass

        size = None
        raw_size = c.get("size")
        if raw_size:
            try:
                size = float(raw_size)
            except (ValueError, TypeError):
                pass

        return {
            "id": f"oikotie_{ext_id}",
            "source": "oikotie",
            "external_id": ext_id,
            "url": url,
            "title": c.get("title") or c.get("buildingType"),
            "address": c.get("location", {}).get("address") or c.get("streetAddress", ""),
            "district": c.get("location", {}).get("district") or "Taka-Töölö",
            "price": price,
            "size": size,
            "rooms": c.get("rooms"),
            "room_structure": c.get("roomConfiguration"),
            "floor": c.get("floor"),
            "total_floors": c.get("floors"),
            "build_year": c.get("buildYear"),
            "description": c.get("description", ""),
            "landlord_type": "company" if c.get("broker", {}).get("id") else "private",
            "thumbnail_url": thumb,
            "image_urls": image_urls,
            "image_count": len(image_urls),
        }

    def _parse_from_html(self, html: str) -> List[Dict[str, Any]]:
        """Fallback parser if API requires browser emulation"""
        listings = []
        matches = re.findall(r'href=["\'](/vuokrattavat-asunnot/helsinki/(\d+))["\']', html)
        seen = set()
        for link, ext_id in matches:
            if ext_id in seen:
                continue
            seen.add(ext_id)
            listings.append({
                "id": f"oikotie_{ext_id}",
                "source": "oikotie",
                "external_id": ext_id,
                "url": f"https://asunnot.oikotie.fi{link}",
                "district": "Taka-Töölö",
                "landlord_type": "unknown",
                "image_urls": [],
                "image_count": 0,
            })
        return listings
