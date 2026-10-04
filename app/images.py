import os
import requests
import logging
from datetime import datetime
from typing import List, Dict, Any
from app.db import get_db_connection

logger = logging.getLogger("rental-radar.images")
PHOTO_DIR = os.environ.get("PHOTO_DIR", "/app/data/photos")

def download_listing_images(listing_id: str, image_urls: List[str], max_images: int = 12):
    if not image_urls:
        return

    dest_folder = os.path.join(PHOTO_DIR, listing_id)
    os.makedirs(dest_folder, exist_ok=True)
    
    conn = get_db_connection()
    cur = conn.cursor()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://asunnot.oikotie.fi/"
    }

    saved_count = 0
    for idx, url in enumerate(image_urls[:max_images]):
        if not url:
            continue
            
        file_ext = ".jpg"
        if ".png" in url.lower():
            file_ext = ".png"
        elif ".webp" in url.lower():
            file_ext = ".webp"
            
        file_name = f"{idx:02d}{file_ext}"
        local_path = os.path.join(dest_folder, file_name)

        # Check if already downloaded
        if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
            saved_count += 1
            continue

        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                
                now = datetime.now().isoformat()
                cur.execute('''
                INSERT INTO images (listing_id, original_url, local_path, downloaded_at)
                VALUES (?, ?, ?, ?)
                ''', (listing_id, url, local_path, now))
                saved_count += 1
        except Exception as e:
            logger.warning("Failed to download image %s for %s: %s", url, listing_id, e)

    conn.commit()
    conn.close()
    logger.info("Saved %d images for listing %s", saved_count, listing_id)
