import requests
import re
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger("rental-radar.vuokraovi")

class VuokraoviScraper:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.search_cfg = config.get("search", {})
        self.city = self.search_cfg.get("city", "helsinki")
        self.district = self.search_cfg.get("district", "taka-toolo")
        self.user_agent = config.get("scraper", {}).get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fi,en-US;q=0.7,en;q=0.3",
        })

    def fetch_listings(self) -> List[Dict[str, Any]]:
        url = f"https://www.vuokraovi.com/vuokra-asunnot/{self.city}/{self.district}"
        logger.info("Fetching Vuokraovi from %s...", url)
        
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.error("Failed to fetch Vuokraovi page: %s", e)
            return []

        # Extract __NEXT_DATA__ JSON script
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            logger.warning("Could not find __NEXT_DATA__ in Vuokraovi page")
            return []

        try:
            data = json.loads(m.group(1))
            page_props = data.get("props", {}).get("pageProps", {})
            ann_container = page_props.get("initialAnnouncements", {})
            announcements = ann_container.get("announcements", [])
            logger.info("Extracted %d raw announcements from Vuokraovi NEXT_DATA", len(announcements))
        except Exception as e:
            logger.error("Error parsing Vuokraovi NEXT_DATA JSON: %s", e)
            return []

        price_max = self.search_cfg.get("price_max", 1050)
        price_min = self.search_cfg.get("price_min", 600)
        size_min = self.search_cfg.get("size_min", 27)
        size_max = self.search_cfg.get("size_max", 38)
        allowed_rooms = self.search_cfg.get("room_counts", [1, 2])

        listings = []
        for ann in announcements:
            rent = ann.get("searchRent")
            area = ann.get("area") or ann.get("totalArea")
            rooms = ann.get("roomCount")

            # Apply filters
            if rent is not None and (rent > price_max or rent < price_min):
                continue
            if area is not None and (area > size_max or area < size_min):
                continue
            if rooms is not None and rooms not in allowed_rooms:
                continue

            parsed = self._parse_announcement(ann)
            if parsed:
                listings.append(parsed)

        logger.info("Vuokraovi matched %d listings after filtering", len(listings))
        return listings

    def _parse_announcement(self, ann: Dict[str, Any]) -> Dict[str, Any]:
        ext_id = str(ann.get("friendlyId") or ann.get("id", ""))
        url = f"https://www.vuokraovi.com/kohde/{ext_id}"
        
        thumb = ann.get("mainImageUri")
        image_urls = [thumb] if thumb else []

        address = ann.get("addressLine1", "")
        district = ann.get("location") or "Taka-Töölö"

        return {
            "id": f"vuokraovi_{ext_id}",
            "source": "vuokraovi",
            "external_id": ext_id,
            "url": url,
            "title": f"{ann.get('propertyType', 'Kerrostalo')} {ann.get('roomStructure', '')}",
            "address": address,
            "district": district,
            "price": ann.get("searchRent"),
            "size": ann.get("area"),
            "rooms": ann.get("roomCount"),
            "room_structure": ann.get("roomStructure"),
            "floor": ann.get("floorLevel"),
            "total_floors": ann.get("housingCompanyFloorCount"),
            "build_year": ann.get("constructionFinishedYear"),
            "description": "",
            "landlord_type": "company" if ann.get("isCompanyAnnouncement") else "private",
            "thumbnail_url": thumb,
            "image_urls": image_urls,
            "image_count": len(image_urls),
        }
